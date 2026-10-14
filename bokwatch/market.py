"""시장금리 → 모델 투입 → 확률 결과 (스냅샷·추이·백테스트)."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import model
from .common import d
from .fetch_rates import load_rates, manual_rows, series, value_on


def all_rate_rows() -> list[dict]:
    """ECOS 값 우선, 같은 날짜·id에 ECOS가 없을 때만 수동 입력."""
    rows = load_rates()
    have = {(r["date"], r["id"]) for r in rows}
    return rows + [r for r in manual_rows() if (r["date"], r["id"]) not in have]


def item_defs(cfg) -> dict:
    out = {}
    for it in cfg["ecos"]["market"]["items"]:
        out[it["id"]] = {"label": it["label"], "tenor_days": it["tenor_days"], "kind": "market"}
    for it in cfg["ecos"]["ois"]["items"]:
        out[it["id"]] = {"label": it["label"], "tenor_days": it["tenor_days"], "kind": "ois"}
    return out


def base_rate_on(rows, day: date, cfg):
    v, k = value_on(series(rows, "base"), day, max_back=40)
    if v is not None:
        return v, f"ECOS/수동 base ({k})"
    # 기준금리 시계열이 없으면 결정 기록에서
    past = [x for x in cfg.get("past_decisions", []) if d(x["date"]) <= day]
    if past:
        x = max(past, key=lambda x: x["date"])
        return float(x["rate"]), f"결정 기록 {x['date']}"
    return None, None


def estimate_spreads(rows, cfg) -> dict:
    """장기 동결 국면 y - r0 중앙값. override > 추정 > fallback."""
    mc = cfg["model"]
    base = series(rows, "base")
    out = {}
    for iid in item_defs(cfg):
        if iid in (mc.get("spread_override") or {}):
            out[iid] = {"value": float(mc["spread_override"][iid]), "how": "config 지정"}
            continue
        ser = series(rows, iid)
        obs = []
        for a, b in mc.get("hold_windows", []):
            for day, y in ser.items():
                if a <= day <= b:
                    r0, _ = value_on(base, d(day), 40)
                    if r0 is not None:
                        obs.append((y - r0) * 100)
        if len(obs) >= 20:
            out[iid] = {"value": round(model.normal_spread(obs), 4),
                        "how": f"동결 국면 중앙값({len(obs)}일)"}
        elif iid in (mc.get("spread_fallback") or {}):
            out[iid] = {"value": float(mc["spread_fallback"][iid]), "how": "기본 가정(이력 부족)"}
    return out


def meetings_after(cfg, day: date) -> list[date]:
    ms = {d(x) for ys in cfg["meetings"].values() for x in (ys or [])}
    ms |= {d(x["date"]) for x in cfg.get("past_decisions", [])}
    return sorted(m for m in ms if m > day)


def instruments_on(rows, cfg, day: date, spreads: dict):
    """그날 투입할 상품. OIS가 있으면 OIS 우선. (instruments, input_table, warnings)"""
    defs = item_defs(cfg)
    known = d(cfg["schedule_known_through"])
    start = model.settlement_start(day)
    table, warns = [], []
    ois_ids = [i for i, x in defs.items() if x["kind"] == "ois" and day.isoformat() in series(rows, i)]
    use = ois_ids or list(cfg["model"]["use"])
    insts = []
    for iid, df in defs.items():
        ser = series(rows, iid)
        v, used_day = value_on(ser, day, 7)
        if v is None:
            continue
        prev_v, prev_day = value_on(ser, d(used_day) - timedelta(days=1), 10)
        sp = spreads.get(iid, {"value": 0.0, "how": "없음"})
        mat = start + timedelta(days=df["tenor_days"])
        in_sched = mat <= known
        used = iid in use and in_sched
        if iid in use and not in_sched:
            warns.append(f"{df['label']} 만기({mat})가 확정 일정({known}) 밖 — 계산 제외")
        src = next((r["source"] for r in rows if r["id"] == iid and r["date"] == used_day), "")
        table.append({"id": iid, "label": df["label"], "rate": v, "date": used_day,
                      "tenor_days": df["tenor_days"], "spread": sp["value"], "spread_how": sp["how"],
                      "chg_bp": round((v - prev_v) * 100, 1) if prev_v is not None else None,
                      "prev_date": prev_day, "source": src, "used": used, "kind": df["kind"]})
        if used:
            insts.append(model.Instrument(iid, v, df["tenor_days"], sp["value"], src))
    return insts, table, warns


def run_day(rows, cfg, day: date, spreads: dict, shifts=(-5, 0, 5)):
    r0, r0_src = base_rate_on(rows, day, cfg)
    insts, table, warns = instruments_on(rows, cfg, day, spreads)
    for t in table:
        t["vs_base_bp"] = round((t["rate"] - r0) * 100, 1) if r0 is not None else None
    if r0 is None or not insts:
        return None
    ms = meetings_after(cfg, day)
    sens = model.sensitivity(day, r0, insts, ms, cfg["model"]["method"], shifts)
    return {
        "asof": day.isoformat(), "r0": r0, "r0_source": r0_src,
        "inputs": table, "warnings": warns,
        "scenarios": {str(k): model.result_to_dict(v) for k, v in sens.items()},
    }


def data_dates(rows, cfg) -> list[date]:
    ids = set(cfg["model"]["use"]) | {i["id"] for i in cfg["ecos"]["ois"]["items"]}
    return sorted({d(r["date"]) for r in rows if r["id"] in ids})


# ---------------------------------------------------------------- 백테스트
def business_days_before(day: date, n: int, available: list[date]) -> date | None:
    prior = [x for x in available if x < day]
    return prior[-n] if len(prior) >= n else None


def backtest(rows, cfg, spreads, start_year=2021, n_before=3) -> dict:
    avail = data_dates(rows, cfg)
    decisions = sorted(cfg.get("past_decisions", []), key=lambda x: x["date"])
    out, prev_rate = [], None
    for x in decisions:
        md = d(x["date"])
        actual_prev = prev_rate
        prev_rate = float(x["rate"])
        if md.year < start_year or actual_prev is None:
            continue
        obs = business_days_before(md, n_before, avail)
        if obs is None or (md - obs).days > 10:
            continue
        res = run_day(rows, cfg, obs, spreads, shifts=(0,))
        if not res:
            continue
        m = next((m for m in res["scenarios"]["0"]["meetings"] if m["date"] == md.isoformat()), None)
        if not m or not m["in_range"]:
            continue
        move = round((float(x["rate"]) - actual_prev) * 100)
        actual = "hike" if move > 0 else "cut" if move < 0 else "hold"
        p = {"hike": m["p_hike"], "hold": m["p_hold"], "cut": m["p_cut"]}
        pred = max(p, key=p.get)
        brier = sum((p[k] - (1.0 if k == actual else 0.0)) ** 2 for k in p)
        out.append({"meeting": md.isoformat(), "obs_date": obs.isoformat(), **{f"p_{k}": v for k, v in p.items()},
                    "pred": pred, "actual": actual, "move_bp": move, "hit": pred == actual,
                    "brier": round(brier, 4)})
    n = len(out)
    return {
        "n": n, "rule": f"회의 {n_before}영업일 전 종가, 기본 스프레드",
        "hit_rate": round(sum(r["hit"] for r in out) / n, 4) if n else None,
        "brier": round(statistics.mean(r["brier"] for r in out), 4) if n else None,
        "rows": out,
        "note": None if n else "과거 시장금리 이력이 없어 산출하지 못함 (ECOS --full 수집 후 자동 산출)",
    }
