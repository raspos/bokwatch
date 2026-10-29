"""AWM 2.0 실시간 예측과 사이트 출력(site/data/awm.json).

학습 자료(지난 금통위의 점별 표)는 새 결정이 나올 때만 다시 만들고 data/awm_panel.json에 둔다.
오늘 예측은 그 표 전체로 학습한 모형에 오늘 칸을 넣어 낸다. 외부 API·LLM은 쓰지 않는다.
이 값은 시장가격이 아니라 두 상품 확률의 통계적 결합이다. 기본 확률(KOFR OIS)을 대체하지 않는다.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from . import awm, awm_backtest, awm_data
from .common import d

ROOT = Path(__file__).resolve().parent.parent
PANEL_CACHE = ROOT / "data" / "awm_panel.json"
AWM_LOG = ROOT / "data" / "awm_log.csv"
LOG_FIELDS = ["date", "obs_date", "meeting", "D", "model", "p_hike", "p_hold", "p_cut", "w_ois", "ois_source", "kind"]
PANEL_VERSION = 1

# 화면에 올리는 모형: 머리값 M5, 비교용 단독·적응형
LIVE = ("M2 합성 OIS 단독", "M3 통안채 91일 단독", "M5 OIS+통안채 50:50", "M6c 기간 연속형 가중치", "M7 최근 오차 반영(EWA)",
        "M8 기간+전환 신호 가중치")


def get_panel(inp: awm_data.Inputs) -> tuple[list[dict], bool]:
    """지난 금통위 표. 마지막 결정 회의가 같으면 저장본을 쓴다. (표, 새로 만들었는지)"""
    last = awm_data.meeting_table(inp.cfg)[-1]["meeting"].isoformat()
    if PANEL_CACHE.exists():
        c = json.loads(PANEL_CACHE.read_text(encoding="utf-8"))
        if c.get("last_decided") == last and c.get("version") == PANEL_VERSION and c.get("policy") == inp.ois_policy:
            return c["panel"], False
    panel = awm_data.build_panel(inp)
    PANEL_CACHE.write_text(json.dumps({"version": PANEL_VERSION, "last_decided": last, "policy": inp.ois_policy, "panel": panel},
                                      ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return panel, True


def _state_after(cfg: dict) -> dict:
    """마지막 결정 이후의 직전 변경 방향·연속 횟수·변경일(다음 회의에 적용)."""
    t = awm_data.meeting_table(cfg)[-1]
    if t["move_bp"] != 0:
        dr = t["actual"]
        return {"last_dir": dr, "streak": t["streak"] + 1 if t["last_change_dir"] == dr else 1, "last_change": t["meeting"]}
    from datetime import timedelta
    lc = t["meeting"] - timedelta(days=t["days_since_change"]) if t["days_since_change"] is not None else None
    return {"last_dir": t["last_change_dir"], "streak": t["streak"], "last_change": lc}


def live_row(inp: awm_data.Inputs, meeting: date, today: date) -> dict:
    """오늘 관측 시점의 칸(결과는 아직 없다)."""
    st = _state_after(inp.cfg)
    D = (meeting - today).days
    obs = awm_data.obs_on_or_before(inp.avail, today)
    row = {"meeting": meeting.isoformat(), "horizon": D, "target_date": today.isoformat(), "actual": "hold", "move_bp": 0,
           "last_change_dir": st["last_dir"], "streak": st["streak"],
           "days_since_change": (meeting - st["last_change"]).days if st["last_change"] else None,
           "obs_date": obs.isoformat() if obs else None, "models": {}}
    if obs is None:
        row["missing"] = "관측일 없음(자료 공백)"
        return row
    r0 = inp.base(obs)
    row["r0"] = r0
    if r0 is None:
        row["missing"] = "기준금리 없음"
        return row
    for iid in awm_data.SINGLE:
        row["models"][iid] = awm_data.single_model(inp, iid, obs, r0, meeting)
    row["models"]["ois"] = awm_data.ois_model(inp, obs, r0, meeting, inp.ois_policy)
    row["features"] = awm_data.features(inp, obs, r0, meeting, row["models"]["ois"])
    return row


def predict_live(today: date, meeting: date | None = None) -> dict | None:
    inp = awm_data.Inputs()
    meeting = meeting or next((m for m in inp.meetings_all if m > today), None)
    if meeting is None:
        return None
    panel, rebuilt = get_panel(inp)
    cells = awm.prepare(panel)
    row = live_row(inp, meeting, today)
    out = {"meeting": meeting.isoformat(), "D": row["horizon"], "obs_date": row["obs_date"], "ois_policy": inp.ois_policy,
           "panel_rebuilt": rebuilt, "n_train_meetings": len({c.meeting for c in cells}), "models": {}, "inputs": {}}
    if row.get("missing"):
        out["missing"] = row["missing"]
        return out
    for k, v in row["models"].items():
        out["inputs"][k] = ({"source_type": v.get("source_type"), "input_date": v.get("input_date"), "p": v["p"],
                             "solve": v.get("solve"), "spread_how": v.get("spread_how")} if v.get("ok") else {"ok": False, "why": v.get("why")})
    live = awm.prepare([row])
    if not live:
        out["missing"] = "예측 칸을 만들 수 없음"
        return out
    c = live[0]
    c.idx = max(x.idx for x in cells) + 1
    for m in awm_backtest.models_all():
        if m.name not in LIVE:
            continue
        m.fit(cells)
        if not m.available(c):
            out["models"][m.name] = {"ok": False, "why": "필요한 입력 없음(합성 OIS 또는 통안채 91일)"}
            continue
        p = awm.clip_norm(m.predict(c))
        rec = {"ok": True, "p": {"hike": round(float(p[0]), 4), "hold": round(float(p[1]), 4), "cut": round(float(p[2]), 4)}}
        w = m.weight_of(c)
        if w is not None:
            rec["w_ois"] = round(float(w), 4)
        out["models"][m.name] = rec
    out["ois_source"] = c.meta.get("ois_source")
    return out


def append_log(live: dict, today: date) -> None:
    """오늘 예측을 data/awm_log.csv에 덧붙인다. 그날 처음 값 고정(이미 있으면 쓰지 않는다). 수정 없음."""
    if not live or live.get("missing"):
        return
    day = today.isoformat()
    rows = list(csv.DictReader(open(AWM_LOG, encoding="utf-8"))) if AWM_LOG.exists() else []
    if any(r["date"] == day for r in rows):
        return
    for name, m in live["models"].items():
        if not m.get("ok"):
            continue
        rows.append({"date": day, "obs_date": live["obs_date"], "meeting": live["meeting"], "D": live["D"], "model": name,
                     "p_hike": m["p"]["hike"], "p_hold": m["p"]["hold"], "p_cut": m["p"]["cut"], "w_ois": m.get("w_ois", ""),
                     "ois_source": live.get("ois_source") or "", "kind": "stored"})
    with open(AWM_LOG, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)


def build_outputs(today: date, site_data: Path, write_log: bool = False) -> dict | None:
    live = predict_live(today)
    if live is None:
        return None
    if write_log:
        append_log(live, today)
    bt = site_data / "awm_backtest.json"
    payload = {"generated": today.isoformat(), "live": live,
               "label": "통계적 결합 실험값. 시장가격이 아니며 기본 확률(KOFR OIS)을 대체하지 않는다.",
               "backtest_file": "awm_backtest.json" if bt.exists() else None}
    (site_data / "awm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def write_backtest(path: Path, B: int = 10000) -> dict:
    """정적 백테스트 요약(site/data/awm_backtest.json). 새 결정이 나왔을 때만 다시 만든다(수 분 걸림).
    기준 burn-in은 6회로 고정하고 3·10회는 민감도로만 싣는다."""
    inp = awm_data.Inputs()
    panel, _ = get_panel(inp)
    res = awm_backtest.run(panel, burn_in=6, B=B)
    sens = {}
    for b in (3, 10):
        r = awm_backtest.run(panel, burn_in=b, B=100)
        sens[str(b)] = {"sample": r["sample_ois"], "brier": {n: s["brier"] for n, s in r["table_ois"].items()}}
    keep = ("M2 합성 OIS 단독", "M3 통안채 91일 단독", "M5 OIS+통안채 50:50", "M7 최근 오차 반영(EWA)", "M8 기간+전환 신호 가중치")
    rows = [r for r in res["rows"] if r["model"] in keep and r["D"] in (30, 10, 1)]
    recent = sorted({r["meeting"] for r in rows})[-8:]
    by = {}
    for r in rows:
        if r["meeting"] in recent:
            e = by.setdefault((r["meeting"], r["D"]), {"meeting": r["meeting"], "D": r["D"], "actual": r["actual"], "p_hike": {}})
            e["p_hike"][r["model"]] = round(r["p"][0], 3)
    out = {
        "generated": date.today().isoformat(), "primary_burn_in": 6, "sample": res["sample_ois"], "sample_long": res["sample_long"],
        "kind": {"formal": "금통위 순서의 확장 창 walk-forward(학습에 그 회의 이후 자료 없음)",
                 "post_hoc": "모형 후보·burn-in·구간 나누기는 자료를 본 뒤 정했다. 정식 표본 밖 검증이 아니다",
                 "exploratory": ["M8b", "M9b", "국면별·급변별 표", "OIS는 합성 추정(실제 OIS 호가 아님)"]},
        "table": res["table_ois"], "table_long": res["table_long"], "by_regime": res["by_regime_ois"], "by_volatility": res["by_volatility_ois"],
        "weight_by_horizon": res["weight_by_horizon"], "paired": res["paired_ois"], "sensitivity": sens,
        "recent": sorted(by.values(), key=lambda e: (e["meeting"], -e["D"])), "bootstrap": res["meta"]["bootstrap"],
        "data": {"first_obs": min(r["obs_date"] for r in panel if r.get("obs_date")), "last_obs": max(r["obs_date"] for r in panel if r.get("obs_date")),
                 "sources": "ECOS(CD91·통안증권 91일·기준금리), 한국은행 CD 시가평가 곡선, KOFR(자체 합성 OIS)"},
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    if "--backtest" in sys.argv:
        write_backtest(ROOT / "site" / "data" / "awm_backtest.json")
        print("백테스트 저장")
    else:
        print(json.dumps(predict_live(date.today()), ensure_ascii=False, indent=1))
