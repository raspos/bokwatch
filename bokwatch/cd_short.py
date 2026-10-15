"""CD 단기물(1개월·15일) 모형 — 다음 금통위 하나만 보는 실험값.

CD 91일은 만기 안에 회의가 둘 이상 들어가 회의 사이 배분을 가정으로 정해야 한다.
1개월물(30일)·15일물은 만기 안 회의가 하나뿐이라 그 회의 뒤 기대 기준금리를 바로 푼다.

  T × (y − s) = pre × r0 + post × E
  y = 그날 CD 시가평가수익률(AAA 5사 평균), T = 30(1개월) 또는 15, pre = 회의 전 일수, post = 회의 뒤 일수
  s = 정상 스프레드: 그날 이전 1년 안에서 '만기 안에 회의가 없던 날'의 (CD 같은 만기 − 기준금리) 중앙값
      (회의가 없으면 기준금리 변화 기대가 없으므로 그 차이는 신용·기간 웃돈만 남는다. 미래 정보 없음)
  Δ = E − r0 → CD 91일 모형과 같은 규칙으로 인상·동결·인하 확률

한계: 공시값은 소수 둘째 자리(버림)라 1bp 단위다. 1개월물에서 1bp는 회의 확률 약 4~5%p에 해당한다.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import model
from .common import SITE_DATA, d, write_json

TENORS = {"m1": (30, "CD 1개월"), "d15": (15, "CD 15일")}
LOOKBACK, LOOKBACK_LONG, MIN_OBS = 365, 730, 10


def _value_on(ser: dict, day: date, back: int):
    for i in range(back + 1):
        k = (day - timedelta(days=i)).isoformat()
        if k in ser:
            return ser[k], k
    return None, None


def meeting_in(start: date, tenor: int, meetings: list[date]) -> list[date]:
    end = start + timedelta(days=tenor)
    return [m for m in meetings if start <= m < end]


_OBS: dict = {}


def _clean_obs(curve: dict, base: dict, meetings: list[date], key: str) -> list[tuple[str, float]]:
    """만기 안에 회의가 없던 날의 (날짜, CD − 기준금리). 같은 입력이면 한 번만 계산."""
    ck = (id(curve), len(curve), id(base), len(meetings), key)
    if ck not in _OBS:
        tenor, ms, out = TENORS[key][0], sorted(meetings), []
        for k in sorted(curve):
            dk = d(k)
            if meeting_in(model.settlement_start(dk), tenor, ms):
                continue
            b, _ = _value_on(base, dk, 40)
            if b is not None:
                out.append((k, curve[k][key] - b))
        _OBS.clear() if len(_OBS) > 8 else None
        _OBS[ck] = out
    return _OBS[ck]


def pit_spread(curve: dict, base: dict, meetings: list[date], day: date, key: str):
    """그날 이전, 만기 안에 회의가 없던 날들의 (CD − 기준금리) 중앙값. (값, 관측 수, 설명)"""
    allobs = _clean_obs(curve, base, meetings, key)
    for lb in (LOOKBACK, LOOKBACK_LONG):
        lo = (day - timedelta(days=lb)).isoformat()
        obs = [v for k, v in allobs if lo <= k < day.isoformat()]
        if len(obs) >= MIN_OBS:
            return round(statistics.median(obs), 4), len(obs), f"회의 없는 기간 {lb // 365}년 중앙값({len(obs)}일)"
    return None, 0, "관측 부족"


def solve(day: date, r0: float, y: float, s: float, tenor: int, meetings: list[date]):
    start = model.settlement_start(day)
    ms = meeting_in(start, tenor, meetings)
    if len(ms) != 1:
        return None
    m = ms[0]
    pre, post = (m - start).days, tenor - (m - start).days
    if post <= 0:
        return None
    e = r0 + tenor * (y - s - r0) / post
    dist = model.move_distribution(e - r0)
    p = {"hike": sum(v for k, v in dist.items() if k > 0), "cut": sum(v for k, v in dist.items() if k < 0)}
    p["hold"] = 1 - p["hike"] - p["cut"]
    return {"meeting": m.isoformat(), "pre_days": pre, "post_days": post, "expected": round(e, 4),
            "delta_bp": round((e - r0) * 100, 2), **{f"p_{k}": round(v, 4) for k, v in p.items()}}


def compute(curve: dict, base: dict, meetings: list[date], day: date, r0: float, max_stale: int = 5) -> dict | None:
    """그날 CD 단기물 실험값. 곡선 값은 그날 이하 가장 가까운 날(최대 max_stale일 전)."""
    row_day = max((k for k in curve if k <= day.isoformat()), default=None)
    if not row_day or (day - d(row_day)).days > max_stale:
        return None
    row = curve[row_day]
    out = {"curve_date": row_day, "source": row.get("source", ""), "inputs": {k: row[k] for k in ("d7", "d15", "m1", "m3")}}
    for key, (tenor, label) in TENORS.items():
        s, n, how = pit_spread(curve, base, meetings, d(row_day), key)
        if s is None:
            continue
        r = solve(d(row_day), r0, row[key], s, tenor, meetings)
        if r:
            out[key] = {"label": label, "tenor_days": tenor, "rate": row[key], "spread": s, "spread_how": how, **r}
    return out if any(k in out for k in TENORS) else None


# ---------------------------------------------------------------- 백테스트
def backtest(curve: dict, base: dict, meetings: list[date], decisions: list[dict], cd91_rows: list[dict],
             n_before: int = 3) -> dict:
    """회의 n영업일 전(곡선 공시일 기준) 값으로 그 회의를 예측. 과거 결정 빈도·항상 동결·CD 91일 모형과 같은 회의에서 비교."""
    from .market import _score
    days = sorted(d(k) for k in curve)
    dec = sorted(decisions, key=lambda x: x["date"])
    cd91 = {r["meeting"]: r for r in cd91_rows}
    rows, prev, prior = [], None, []
    for x in dec:
        md, rate = d(x["date"]), float(x["rate"])
        if prev is None:
            prev = rate
            continue
        mv = round((rate - prev) * 100)
        actual = "hike" if mv > 0 else "cut" if mv < 0 else "hold"
        r0, prev = prev, rate
        before = [z for z in days if z < md]
        obs = before[-n_before] if len(before) >= n_before and (md - before[-1]).days <= 10 else None
        res = None
        if obs is not None:
            res = compute(curve, base, meetings, obs, r0, max_stale=0)
        freq = {k: (prior.count(k) + 1) / (len(prior) + 3) for k in ("hike", "hold", "cut")}
        prior.append(actual)
        if not res or not all(k in res and res[k]["meeting"] == md.isoformat() for k in TENORS):
            continue
        row = {"meeting": md.isoformat(), "obs_date": obs.isoformat(), "actual": actual, "move_bp": mv}
        for key in TENORS:
            p = {k: res[key][f"p_{k}"] for k in ("hike", "hold", "cut")}
            pr, br = _score(p, actual)
            row[key] = {**{f"p_{k}": v for k, v in p.items()}, "hit": pr == actual, "brier": round(br, 4),
                        "spread_bp": round(res[key]["spread"] * 100, 1), "rate": res[key]["rate"], "delta_bp": res[key]["delta_bp"]}
        bpr, bbr = _score(freq, actual)
        row["base_rate"] = {**{f"p_{k}": round(v, 4) for k, v in freq.items()}, "hit": bpr == actual, "brier": round(bbr, 4)}
        c = cd91.get(md.isoformat())
        if c:
            row["cd91"] = {"p_hike": c["p_hike"], "p_hold": c["p_hold"], "p_cut": c["p_cut"], "hit": c["hit"], "brier": c["brier"]}
        rows.append(row)
    summ = {}
    if rows:
        hold = {"hike": 0.0, "hold": 1.0, "cut": 0.0}
        get = {"m1": lambda r: r["m1"], "d15": lambda r: r["d15"], "base_rate": lambda r: r["base_rate"],
               "always_hold": lambda r: {"hit": r["actual"] == "hold", "brier": _score(hold, r["actual"])[1],
                                         **{f"p_{k}": hold[k] for k in hold}}}
        both = [r for r in rows if "cd91" in r]
        for name, g in get.items():
            summ[name] = _summ(rows, g)
        if both:
            summ["same_as_cd91"] = {"n": len(both), **{name: _summ(both, g) for name, g in
                                                         {**get, "cd91": lambda r: r["cd91"]}.items()}}
    return {"n": len(rows), "first": rows[0]["meeting"] if rows else None, "rule": f"회의 {n_before}영업일 전 공시값",
            "summary": summ, "rows": rows}


def _summ(rows, g) -> dict:
    by = {}
    for a in ("hike", "hold", "cut"):
        rs = [r for r in rows if r["actual"] == a]
        by[a] = {"n": len(rs), "hits": sum(bool(g(r)["hit"]) for r in rs),
                 "p_actual": round(statistics.mean(g(r)[f"p_{a}"] for r in rs), 4) if rs else None}
    return {"hits": sum(bool(g(r)["hit"]) for r in rows), "brier": round(statistics.mean(g(r)["brier"] for r in rows), 4),
            "by_actual": by}


def write_backtest(curve, base, meetings, decisions, cd91_rows, current=None) -> dict:
    out = backtest(curve, base, meetings, decisions, cd91_rows)
    out["current"] = current
    write_json(SITE_DATA / "cd_short.json", out)
    return out
