"""대표모형 전환(M5 종합 예측) 검사: 확률 합·평균, 입력 누락 처리, 사후 재계산/당시 저장 구분, 기존 기록 불변, 11/26·10/22 검산."""
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from bokwatch import awm_series, review

ROOT = Path(__file__).resolve().parent.parent
P = lambda h, o, c=0.0: {"hike": h, "hold": o, "cut": c}


def test_blend_is_equal_weight_mean_and_sums_to_one():
    b = awm_series.blend(P(0.5, 0.5), P(0.9, 0.1))
    assert b == {"hike": 0.7, "hold": 0.3, "cut": 0.0}
    b = awm_series.blend(P(0.1, 0.7, 0.2), P(0.3, 0.6, 0.1))
    assert abs(sum(b.values()) - 1) < 1e-3 and b["hike"] == 0.2


def _fake_inp():
    class I:
        cfg = {"past_decisions": [{"date": "2026-10-22", "rate": 3.0}], "meetings": {}}
        meetings_all = [date(2026, 10, 22), date(2026, 11, 26)]
        ois_policy = "flat"

        def base(self, day):
            return 3.0
    return I()


def test_missing_input_gives_no_m5_and_reason(monkeypatch):
    inp = _fake_inp()
    monkeypatch.setattr(awm_series.awm_data, "ois_model", lambda *a, **k: {"ok": False, "why": "풀리지 않음"})
    monkeypatch.setattr(awm_series.awm_data, "single_model", lambda *a, **k: {"ok": True, "p": P(0.2, 0.8)})
    r = awm_series.one_day(inp, date(2026, 11, 26), date(2026, 10, 28))
    assert r["m5"] is None and r["ois"] is None and "합성 OIS 없음" in r["why"]          # CD91 등으로 채우지 않는다
    monkeypatch.setattr(awm_series.awm_data, "ois_model", lambda *a, **k: {"ok": True, "p": P(0.6, 0.4), "source_type": "ois_3m"})
    monkeypatch.setattr(awm_series.awm_data, "single_model", lambda *a, **k: {"ok": False, "why": "금리 없음"})
    r = awm_series.one_day(inp, date(2026, 11, 26), date(2026, 10, 28))
    assert r["m5"] is None and r["ois"] and "통안채 91일 없음" in r["why"]


def test_retro_vs_stored_and_logs_untouched(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    (site / "history.csv").write_text("date,scenario,meeting,p_hike,p_hold,p_cut,expected\n"
                                      "2026-10-27,0,2026-11-26,0.59,0.41,0,3.1\n2026-10-28,0,2026-11-26,0.58,0.42,0,3.1\n", encoding="utf-8")
    log = tmp_path / "awm_log.csv"
    log.write_text("date,obs_date,meeting,D,model,p_hike,p_hold,p_cut,w_ois,ois_source,kind\n"
                   "2026-10-29,2026-10-28,2026-11-26,28,M5 OIS+통안채 50:50,0.7362,0.2638,0.0,0.5,ois_3m,stored\n", encoding="utf-8")
    before = hashlib.sha256(log.read_bytes()).hexdigest()
    hist_before = hashlib.sha256((site / "history.csv").read_bytes()).hexdigest()
    monkeypatch.setattr(awm_series, "one_day", lambda inp, mt, obs: {"ois": P(0.5, 0.5), "msb91": P(0.9, 0.1), "m5": P(0.7, 0.3), "why": None})
    s = awm_series.write_series(site, log, date(2026, 10, 29), "m5", inp=_fake_inp())
    days = s["meetings"]["2026-11-26"]
    assert days["2026-10-27"]["kind"] == "retro" and days["2026-10-28"]["kind"] == "stored"      # 저장된 날만 stored
    assert days["2026-10-28"]["m5"]["hike"] == 0.7362                                           # 저장 값을 그대로 쓴다
    assert hashlib.sha256(log.read_bytes()).hexdigest() == before                              # 기존 기록은 바뀌지 않는다
    assert hashlib.sha256((site / "history.csv").read_bytes()).hexdigest() == hist_before
    assert json.loads((site / "awm_series.json").read_text(encoding="utf-8"))["representative"] == "m5"


def test_review_m5_uses_series_and_labels_kind():
    series = {"meetings": {"2026-10-22": {"2026-10-20": {"m5": P(0.2, 0.8), "kind": "retro"},
                                          "2026-10-21": {"m5": P(0.17, 0.83), "kind": "retro"}}}}
    g = {"prev_rate": 3.0}
    rows = [{"asof": "2026-10-21"}]
    r = review._model_m5(series, "2026-10-22", rows, "hold", "2026-10-20", g)
    assert r["final"]["hit"] and r["final"]["kind"] == "retro" and r["d3"]["p"]["hike"] == 0.2
    assert abs(r["predicted_change_bp"] - 0.25 * 0.17 * 100) < 0.06   # 기대금리는 소수 셋째 자리까지 반올림
    assert review._model_m5({"meetings": {}}, "2026-10-22", rows, "hold", "x", g) is None


SERIES = ROOT / "site" / "data" / "awm_series.json"


@pytest.mark.skipif(not SERIES.exists(), reason="빌드 전")
def test_series_file_consistency():
    s = json.loads(SERIES.read_text(encoding="utf-8"))
    assert s["representative"] in ("m5", "ois")
    n = 0
    for ms, days in s["meetings"].items():
        for ds, e in days.items():
            if e["m5"]:
                n += 1
                assert abs(sum(e["m5"].values()) - 1) < 1e-3, (ms, ds)                         # 세 범주 합계 100%
                assert abs(e["m5"]["hike"] - 0.5 * (e["ois"]["hike"] + e["msb91"]["hike"])) < 6e-4
                assert e["kind"] in ("retro", "stored")
            else:
                assert e["why"]                                                                 # 산출 불가는 이유가 있다
            if e["ois"]:
                assert abs(e["ois"]["hike"] - e["site_ois_hike"]) < 0.006                      # 재계산 OIS가 사이트 기존 값과 같다
    assert n > 40
    d1021 = s["meetings"]["2026-10-22"]["2026-10-21"]
    assert d1021["m5"]["hike"] < 0.5 and d1021["m5"]["hold"] > 0.5                              # 10/22 결과(동결)와 같은 방향


def test_live_nov26_matches_site_ois_and_blend():
    """2026-11-26 회의의 10/28 기준 값 검산: OIS는 사이트 기존 값(58.4%)과 일치, M5는 그 평균."""
    from bokwatch import awm_data
    inp = awm_data.Inputs()
    r = awm_series.one_day(inp, date(2026, 11, 26), date(2026, 10, 28))
    assert abs(r["ois"]["hike"] - 0.5841) < 0.0006
    assert abs(r["m5"]["hike"] - 0.5 * (r["ois"]["hike"] + r["msb91"]["hike"])) < 6e-4
    assert abs(sum(r["m5"].values()) - 1) < 1e-3
