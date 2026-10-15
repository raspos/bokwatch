"""자체 산출 KOFR OIS 추정치 — 한국예탁결제원 'KOFR OIS 추정금리' 산식을 따라 만든 값(실험값).

  KOFR OIS(만기 T) = CD(만기 T) − 스프레드(T)
  CD: 7일·15일·1개월 = 금융투자협회 CD 시가평가수익률(AAA 5사 평균), 3개월 = CD 91일(ECOS)
  스프레드(T) = 과거 각 날짜 d의 'CD_T(d) − 그 기간(d+1부터 T일) 실제 KOFR 일복리'의 중앙값
               (ISDA 방식: 최대 5년. 그날까지 기간이 끝나고 KOFR가 공시된 관측만 쓴다)

다음 회의 역산(1개월물 기준):
  T × OIS = 회의 전 일수 × (r0 + k) + 회의 뒤 일수 × (E + k),  k = KOFR − 기준금리 정상 차이(60일 중앙값)
  Δ = E − r0 → CD 91일 모형과 같은 규칙으로 확률.

예탁원 공시값(2025-04-14~2025-10-24)과의 차이는 방법 탭에 적는다. 예탁원 값은 재배포 금지라 저장·게시하지 않는다.
"""
from __future__ import annotations

import bisect
import math
import statistics
from datetime import date, timedelta

from . import model
from .common import SITE_DATA, d, write_json

TENORS = {"w1": ("d7", 7, "1주"), "w2": ("d15", 15, "2주(15일)"), "m1": ("m1", 30, "1개월"), "m3": ("m3", 91, "3개월")}
YEARS, MIN_OBS = 5, 60


class Kofr:
    """KOFR 일복리 누적 지수(달력일, 휴일은 직전 영업일 금리)."""

    def __init__(self, kofr: dict[str, float]):
        ks = sorted(kofr)
        self.first, self.last = d(ks[0]), d(ks[-1])
        n = (self.last - self.first).days + 1
        self.cum = [0.0] * (n + 1)
        cur = None
        j = 0
        for i in range(n):
            day = (self.first + timedelta(days=i)).isoformat()
            while j < len(ks) and ks[j] <= day:
                cur = kofr[ks[j]]
                j += 1
            self.cum[i + 1] = self.cum[i] + math.log(1 + cur / 100 / 365)

    def comp(self, start: date, days: int) -> float | None:
        a = (start - self.first).days
        b = a + days
        if a < 0 or b > len(self.cum) - 1:
            return None
        return (math.exp(self.cum[b] - self.cum[a]) - 1) * 365 / days * 100


def _obs(curve: dict, cd91: dict, kofr: Kofr, key: str) -> list[tuple[str, str, float]]:
    """(관측일, 기간 끝, CD − 실현 KOFR 복리)."""
    col, tenor, _ = TENORS[key]
    src = cd91 if key == "m3" else {k: v[col] for k, v in curve.items()}
    out = []
    for k in sorted(src):
        st = model.settlement_start(d(k))
        c = kofr.comp(st, tenor)
        if c is not None:
            out.append((k, (st + timedelta(days=tenor)).isoformat(), src[k] - c))
    return out


class OIS:
    def __init__(self, curve: dict, cd91: dict, kofr_ser: dict):
        self.curve, self.cd91 = curve, cd91
        self.kofr = Kofr(kofr_ser)
        self.obs = {k: _obs(curve, cd91, self.kofr, k) for k in TENORS}
        self.ends = {k: sorted((e, v, s) for s, e, v in self.obs[k]) for k in TENORS}

    def spread(self, key: str, day: date):
        """그날 쓸 수 있는 스프레드: 기간이 그 전날까지 끝난 관측, 최근 5년 중앙값."""
        lo = (day - timedelta(days=365 * YEARS)).isoformat()
        vals = [v for e, v, s in self.ends[key] if e < day.isoformat() and s >= lo]
        if len(vals) < MIN_OBS:
            return None, len(vals)
        return statistics.median(vals), len(vals)

    def curve_on(self, day: date, max_stale: int = 5) -> dict | None:
        """그날 자체 산출 OIS 곡선. CD 값은 그날 이하 가장 가까운 공시일."""
        ck = max((k for k in self.curve if k <= day.isoformat()), default=None)
        out = {}
        for key, (col, tenor, label) in TENORS.items():
            if key == "m3":
                k = max((x for x in self.cd91 if x <= day.isoformat()), default=None)
                y = self.cd91.get(k) if k else None
            else:
                k, y = ck, (self.curve[ck][col] if ck else None)
            if y is None or (day - d(k)).days > max_stale:
                continue
            s, n = self.spread(key, d(k))
            if s is None:
                continue
            out[key] = {"label": label, "tenor_days": tenor, "cd_date": k, "cd": y, "spread": round(s, 4), "n_obs": n,
                        "ois": round(y - s, 4)}
        return out or None


def next_meeting(ois_row: dict, r0: float, k_spread: float, meetings: list[date]) -> dict | None:
    """1개월 OIS로 다음 회의 뒤 기대 기준금리를 푼다(만기 안 회의가 하나일 때만)."""
    x = ois_row.get("m1")
    if not x:
        return None
    start = model.settlement_start(d(x["cd_date"]))
    T = x["tenor_days"]
    ms = [m for m in meetings if start <= m < start + timedelta(days=T)]
    if len(ms) != 1:
        return None
    pre = (ms[0] - start).days
    post = T - pre
    e = (T * x["ois"] - pre * (r0 + k_spread)) / post - k_spread
    dist = model.move_distribution(e - r0)
    p = {"hike": sum(v for k, v in dist.items() if k > 0), "cut": sum(v for k, v in dist.items() if k < 0)}
    p["hold"] = 1 - p["hike"] - p["cut"]
    return {"meeting": ms[0].isoformat(), "pre_days": pre, "post_days": post, "kofr_base": round(k_spread, 4),
            "expected": round(e, 4), "delta_bp": round((e - r0) * 100, 2), **{f"p_{k}": round(v, 4) for k, v in p.items()}}


def compute(o: OIS, day: date, r0: float, k_spread: float, meetings: list[date], max_stale: int = 5) -> dict | None:
    c = o.curve_on(day, max_stale)
    if not c:
        return None
    return {"curve": c, "next": next_meeting(c, r0, k_spread, meetings)}


# ---------------------------------------------------------------- 백테스트
def backtest(o: OIS, kspread_on, meetings: list[date], decisions: list[dict], cd91_rows: list[dict], n_before: int = 3) -> dict:
    from .market import _score
    days = sorted(d(k) for k in o.curve)
    cd91 = {r["meeting"]: r for r in cd91_rows}
    rows, prev, prior = [], None, []
    for x in sorted(decisions, key=lambda z: z["date"]):
        md, rate = d(x["date"]), float(x["rate"])
        if prev is None:
            prev = rate
            continue
        mv = round((rate - prev) * 100)
        actual = "hike" if mv > 0 else "cut" if mv < 0 else "hold"
        r0, prev = prev, rate
        freq = {k: (prior.count(k) + 1) / (len(prior) + 3) for k in ("hike", "hold", "cut")}
        prior.append(actual)
        i = bisect.bisect_left(days, md)
        if i < n_before or (md - days[i - 1]).days > 10:
            continue
        obs = days[i - n_before]
        res = compute(o, obs, r0, kspread_on(obs), meetings, max_stale=0)
        if not res or not res["next"] or res["next"]["meeting"] != md.isoformat():
            continue
        nx = res["next"]
        p = {k: nx[f"p_{k}"] for k in ("hike", "hold", "cut")}
        pr, br = _score(p, actual)
        bpr, bbr = _score(freq, actual)
        row = {"meeting": md.isoformat(), "obs_date": obs.isoformat(), "actual": actual, "move_bp": mv,
               "ois": {**{f"p_{k}": v for k, v in p.items()}, "hit": pr == actual, "brier": round(br, 4),
                       "ois_1m": res["curve"]["m1"]["ois"], "cd_1m": res["curve"]["m1"]["cd"],
                       "spread_bp": round(res["curve"]["m1"]["spread"] * 100, 1), "delta_bp": nx["delta_bp"]},
               "base_rate": {**{f"p_{k}": round(v, 4) for k, v in freq.items()}, "hit": bpr == actual, "brier": round(bbr, 4)}}
        c = cd91.get(md.isoformat())
        if c:
            row["cd91"] = {"p_hike": c["p_hike"], "p_hold": c["p_hold"], "p_cut": c["p_cut"], "hit": c["hit"], "brier": c["brier"]}
        rows.append(row)
    summ = {}
    if rows:
        hold = {"hike": 0.0, "hold": 1.0, "cut": 0.0}
        get = {"ois": lambda r: r["ois"], "base_rate": lambda r: r["base_rate"],
               "always_hold": lambda r: {"hit": r["actual"] == "hold", "brier": _score(hold, r["actual"])[1],
                                         **{f"p_{k}": hold[k] for k in hold}}}
        for name, g in get.items():
            summ[name] = _summ(rows, g)
        both = [r for r in rows if "cd91" in r]
        if both:
            summ["same_as_cd91"] = {"n": len(both), **{n: _summ(both, g) for n, g in {**get, "cd91": lambda r: r["cd91"]}.items()}}
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


def write(o: OIS, kspread_on, meetings, decisions, cd91_rows, current=None) -> dict:
    out = backtest(o, kspread_on, meetings, decisions, cd91_rows)
    out["current"] = current
    write_json(SITE_DATA / "kofr_ois.json", out)
    return out
