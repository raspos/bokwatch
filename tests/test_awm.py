"""AWM 2.0 핵심 성질 검사: 확률 합·범위, 미래정보 차단, 누락 처리, 군집 부트스트랩, 변수 표준화."""
from datetime import date

import numpy as np
import pytest

from bokwatch import awm, awm_backtest, awm_data


def cell(meeting_idx, D, actual, ois=(0.1, 0.9, 0.0), msb=(0.2, 0.8, 0.0), feat=None):
    pv = lambda t: None if t is None else np.array(t, float)
    return awm.Cell(f"2025-{meeting_idx + 1:02d}-15", meeting_idx, D, actual,
                    {"ois": pv(ois), "msb91": pv(msb), "cd91": pv(msb)},
                    feat or {"s91_chg10_bp": 1.0, "ois_delta_chg5_bp": 0.5},
                    {"ois_source": "ois_1m", "ois_stale": 0, "obs_date": "2025-01-01", "streak": 0, "last_dir": None, "since": None})


def make_cells(n=14):
    out = []
    for i in range(n):
        actual = "hike" if i % 5 == 4 else "hold"
        for D in (30, 20, 10, 5, 3, 1):
            ois = (0.6, 0.4, 0.0) if actual == "hike" else (0.1, 0.9, 0.0)
            out.append(cell(i, D, actual, ois=ois, msb=(0.3, 0.7, 0.0) if actual == "hike" else (0.05, 0.95, 0.0)))
    return out


def all_models():
    return awm_backtest.models_all()


def test_probabilities_sum_to_one_and_in_range():
    recs = awm.walk_forward(make_cells(), all_models())
    assert recs
    for r in recs:
        p = np.array(r["p"])
        assert abs(p.sum() - 1) < 1e-9, r["model"]
        assert (p >= 0).all() and (p <= 1).all(), r["model"]


def test_no_future_information_in_training():
    """i번째 금통위의 예측은 i번째 결과를 바꿔도 달라지지 않는다(학습에 그 회의가 들어가지 않음)."""
    base = make_cells()
    a = awm.walk_forward(base, all_models())
    changed = [awm.Cell(c.meeting, c.idx, c.D, ("cut" if c.idx == 9 else c.actual), c.preds, c.feat, c.meta) for c in base]
    b = awm.walk_forward(changed, all_models())
    key = lambda r: (r["model"], r["meeting"], r["D"])
    da = {key(r): r["p"] for r in a}
    db = {key(r): r["p"] for r in b}
    for k in da:
        idx = int(k[1][5:7]) - 1
        if idx <= 9:   # 9번째 회의 결과를 바꿔도 9번째까지의 예측은 같아야 한다
            assert np.allclose(da[k], db[k]), k
    assert any(not np.allclose(da[k], db[k]) for k in da if int(k[1][5:7]) - 1 > 9)   # 그 뒤 예측은 달라진다(학습에 쓰임)


def test_missing_ois_means_no_prediction_for_ois_models():
    cells = [cell(i, 3, "hold", ois=None) for i in range(10)]
    recs = awm.walk_forward(cells, all_models())
    names = {r["model"] for r in recs}
    assert "M2 합성 OIS 단독" not in names and "M5 OIS+통안채 50:50" not in names     # OIS를 CD91로 채우지 않는다
    assert "M3 통안채 91일 단독" in names and "M0 항상 동결" in names


def test_standardization_uses_only_training_data():
    m = awm.SignalWeight(["abs_s91_chg10"], "t")
    train = [cell(i, 3, "hold", feat={"s91_chg10_bp": float(i)}) for i in range(8)]
    m.fit(train)
    far = cell(99, 3, "hold", feat={"s91_chg10_bp": 1000.0})
    assert abs(m.mu[0] - np.mean(np.abs(range(8)))) < 1e-9       # 평균은 학습 칸에서만 계산
    w = m.weight(far)
    assert 0.0 <= w <= 1.0


def test_two_stage_probabilities():
    cells = make_cells(24)
    m = awm.TwoStage()
    m.fit(cells[:-6])
    p = m.predict(cells[-1])
    assert abs(p.sum() - 1) < 1e-9 and (p >= 0).all()


def test_cluster_bootstrap_unit_is_meeting():
    """같은 금통위의 6칸을 독립으로 보지 않는다: 금통위가 3개 미만이면 CI를 내지 않는다."""
    mk = lambda mt, b: {"meeting": mt, "D": 1, "actual": "hold", "p": b}
    a = [mk("2025-01-15", [0, 1, 0]), mk("2025-02-15", [0, 1, 0])]
    b = [mk("2025-01-15", [0.5, 0.5, 0]), mk("2025-02-15", [0.5, 0.5, 0])]
    assert awm_backtest.cluster_diff(a, b)["n_meetings"] == 2 and "ci95" not in awm_backtest.cluster_diff(a, b)
    a += [mk(f"2025-0{i}-15", [0, 1, 0]) for i in range(3, 9)]
    b += [mk(f"2025-0{i}-15", [0.5, 0.5, 0]) for i in range(3, 9)]
    r = awm_backtest.cluster_diff(a, b, B=500)
    assert r["n_meetings"] == 8 and r["mean_diff"] < 0 and r["ci95"][1] < 0       # 항상 동결이 확실히 낫다


def test_meeting_table_and_obs_selection():
    cfg = {"past_decisions": [{"date": "2025-01-16", "rate": 3.0}, {"date": "2025-02-25", "rate": 2.75},
                              {"date": "2025-04-17", "rate": 2.75}, {"date": "2025-05-29", "rate": 2.5}]}
    t = awm_data.meeting_table(cfg)
    assert [x["actual"] for x in t] == ["cut", "hold", "cut"]
    assert t[1]["last_change_dir"] == "cut" and t[2]["streak"] == 1 and t[1]["days_since_change"] == 51
    avail = [date(2025, 2, 3), date(2025, 2, 4), date(2025, 2, 7)]
    assert awm_data.obs_on_or_before(avail, date(2025, 2, 5)) == date(2025, 2, 4)      # 목표일 이하 마지막 자료일
    assert awm_data.obs_on_or_before(avail, date(2025, 2, 20)) is None                  # 5일 넘게 공백이면 없음
    assert awm_data.obs_on_or_before(avail, date(2025, 2, 1)) is None


def test_metrics_basic():
    recs = [{"meeting": "2025-01-15", "D": 1, "actual": "hold", "p": [0.1, 0.9, 0.0]},
            {"meeting": "2025-02-15", "D": 1, "actual": "hike", "p": [0.6, 0.4, 0.0]},
            {"meeting": "2025-03-15", "D": 1, "actual": "hold", "p": [0.4, 0.4, 0.2]}]
    s = awm_backtest.summarize(recs)
    assert s["n_meetings"] == 3 and s["hit_rate"] == round(2 / 3, 4)               # 동률(0.4,0.4)은 적중이 아니다
    assert s["alert_0.5"]["recall"] == 1.0 and s["alert_0.5"]["false_alarm_rate"] == 0.5
    assert s["hit_rate_change"] == 1.0


def test_offgrid_horizon_bucket_and_live_state():
    c = cell(0, 28, "hold")
    assert c.bucket == "far" and cell(0, 7, "hold").bucket == "mid" and cell(0, 2, "hold").bucket == "near"
    from bokwatch import awm_live
    cfg = {"past_decisions": [{"date": "2025-01-16", "rate": 3.0}, {"date": "2025-02-25", "rate": 2.75}, {"date": "2025-04-17", "rate": 2.75}]}
    st = awm_live._state_after(cfg)
    assert st["last_dir"] == "cut" and st["streak"] == 1 and st["last_change"] == date(2025, 2, 25)


def test_live_log_keeps_first_value_of_day(tmp_path, monkeypatch):
    from bokwatch import awm_live
    monkeypatch.setattr(awm_live, "AWM_LOG", tmp_path / "awm_log.csv")
    live = {"meeting": "2026-11-26", "D": 28, "obs_date": "2026-10-28", "ois_source": "ois_3m",
            "models": {"M5 OIS+통안채 50:50": {"ok": True, "p": {"hike": 0.7, "hold": 0.3, "cut": 0.0}, "w_ois": 0.5}}}
    awm_live.append_log(live, date(2026, 10, 29))
    live["models"]["M5 OIS+통안채 50:50"]["p"]["hike"] = 0.9
    awm_live.append_log(live, date(2026, 10, 29))
    rows = (tmp_path / "awm_log.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2 and "0.7" in rows[1] and "0.9" not in rows[1]
