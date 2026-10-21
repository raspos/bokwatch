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


TAIL_DAYS = 7  # 3개월 만기 직전 회의의 뒤 구간이 이 일수 이하면 그 회의는 변화 없음으로 둔다(영향이 작아 풀 수 없음)


def _probs(delta: float) -> dict:
    dist = model.move_distribution(delta)
    p = {"hike": sum(v for k, v in dist.items() if k > 0), "cut": sum(v for k, v in dist.items() if k < 0)}
    p["hold"] = 1 - p["hike"] - p["cut"]
    return {f"p_{k}": round(v, 4) for k, v in p.items()}


def solve_path(c: dict, r0: float, k_spread: float, meetings: list[date], assumed: set[date] | None = None) -> list[dict]:
    """1개월 OIS로 다음 회의, 3개월 OIS로 그다음 회의를 차례로 푼다(부트스트래핑).
    회의별 확률은 Δ_k = E_k − E_(k−1)로 CD 91일 모형과 같은 규칙. 미지수가 둘 이상 남으면 풀지 않는다.
    assumed(일정 공지 전 가정 회의)는 만기 안 남은 일수와 상관없이 변화 없음 꼬리로 둔다."""
    known: dict[date, float] = {}
    out = []
    first = next_meeting(c, r0, k_spread, meetings)
    if first:
        known[d(first["meeting"])] = first["expected"]
        out.append({**first, "source": "1개월 OIS"})
    x = c.get("m3")
    if not x:
        return out
    start = model.settlement_start(d(x["cd_date"]))
    T = x["tenor_days"]
    end = start + timedelta(days=T)
    ms = [m for m in sorted(meetings) if start <= m < end]
    if not ms:
        return out
    unknown = [m for m in ms if m not in known]
    tail = [m for m in unknown[1:] if (end - m).days <= TAIL_DAYS or m in (assumed or ())]
    core = [m for m in unknown if m not in tail]
    if len(core) != 1:
        return out
    target = core[0]
    # T×OIS = 회의 전×(r0+k) + Σ 구간 일수×(E_i + k). 대상 회의와 그 뒤 꼬리 회의 구간은 같은 E로 둔다.
    bounds = ms + [end]
    lhs = T * x["ois"] - (ms[0] - start).days * (r0 + k_spread)
    coef, level = 0, r0
    for i, m in enumerate(ms):
        days = (bounds[i + 1] - m).days
        if m in known:
            level = known[m]
            lhs -= days * (level + k_spread)
        elif m == target or m in tail:
            coef += days
            lhs -= days * k_spread
        else:
            return out
    if coef <= 0:
        return out
    e = lhs / coef
    prev_m = max((m for m in known if m < target), default=None)
    prev = known[prev_m] if prev_m else r0
    out.append({"meeting": target.isoformat(), "source": "3개월 OIS" + (" + 1개월 OIS" if known else ""), "post_days": coef, "tenor_days": T,
                "kofr_base": round(k_spread, 4), "expected": round(e, 4), "delta_bp": round((e - prev) * 100, 2),
                "tail_assumed": [m.isoformat() for m in tail], **_probs(e - prev)})
    return out


def compute(o: OIS, day: date, r0: float, k_spread: float, meetings: list[date], max_stale: int = 5,
            assumed: set[date] | None = None) -> dict | None:
    c = o.curve_on(day, max_stale)
    if not c:
        return None
    path = solve_path(c, r0, k_spread, meetings, assumed)
    return {"curve": c, "next": next_meeting(c, r0, k_spread, meetings), "path": path}


# ---------------------------------------------------------------- 백테스트
def backtest(o: OIS, kspread_on, meetings: list[date], decisions: list[dict], cd91_rows: list[dict], n_before: int = 3,
             cd91_second=None) -> dict:
    from .market import _score
    days = sorted(d(k) for k in o.curve)
    cd91 = {r["meeting"]: r for r in cd91_rows}
    rows, prev, prior = [], None, []
    dec_sorted = sorted(decisions, key=lambda z: z["date"])
    move_of = {}
    for a, b in zip(dec_sorted, dec_sorted[1:]):
        mv2 = round((float(b["rate"]) - float(a["rate"])) * 100)
        move_of[b["date"]] = (mv2, "hike" if mv2 > 0 else "cut" if mv2 < 0 else "hold")
    second = []
    for x in dec_sorted:
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
        # 두 번째 회의: 같은 관측일의 경로에서 다음다음 회의
        nxt = next((z for z in dec_sorted if z["date"] > x["date"]), None)
        if res and nxt and nxt["date"] in move_of:
            p2 = next((z for z in res["path"] if z["meeting"] == nxt["date"]), None)
            if p2:
                mv2, act2 = move_of[nxt["date"]]
                q = {k: p2[f"p_{k}"] for k in ("hike", "hold", "cut")}
                pr2, br2 = _score(q, act2)
                hold_br = _score({"hike": 0.0, "hold": 1.0, "cut": 0.0}, act2)[1]
                r2 = {"meeting": nxt["date"], "obs_date": obs.isoformat(), "actual": act2, "move_bp": mv2,
                      "ois": {**{f"p_{k}": v for k, v in q.items()}, "hit": pr2 == act2, "brier": round(br2, 4), "delta_bp": p2["delta_bp"], "expected": p2["expected"]},
                      "always_hold": {"hit": act2 == "hold", "brier": hold_br}}
                if cd91_second:
                    c2 = cd91_second(obs, nxt["date"])
                    if c2:
                        qc = {k: c2[f"p_{k}"] for k in ("hike", "hold", "cut")}
                        prc, brc = _score(qc, act2)
                        r2["cd91"] = {**{f"p_{k}": v for k, v in qc.items()}, "hit": prc == act2, "brier": round(brc, 4)}
                second.append(r2)
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
    sec = {"n": len(second), "rows": second}
    if second:
        sec["ois"] = {"hits": sum(r["ois"]["hit"] for r in second), "brier": round(statistics.mean(r["ois"]["brier"] for r in second), 4)}
        sec["always_hold"] = {"hits": sum(r["always_hold"]["hit"] for r in second),
                              "brier": round(statistics.mean(r["always_hold"]["brier"] for r in second), 4)}
        both = [r for r in second if "cd91" in r]
        if both:
            sec["same_as_cd91"] = {"n": len(both), **{k: round(statistics.mean(r[k]["brier"] for r in both), 4)
                                                       for k in ("ois", "cd91", "always_hold")}}
    return {"n": len(rows), "first": rows[0]["meeting"] if rows else None, "rule": f"회의 {n_before}영업일 전 공시값",
            "summary": summ, "rows": rows, "second": sec}


def _summ(rows, g) -> dict:
    by = {}
    for a in ("hike", "hold", "cut"):
        rs = [r for r in rows if r["actual"] == a]
        by[a] = {"n": len(rs), "hits": sum(bool(g(r)["hit"]) for r in rs),
                 "p_actual": round(statistics.mean(g(r)[f"p_{a}"] for r in rs), 4) if rs else None}
    return {"hits": sum(bool(g(r)["hit"]) for r in rows), "brier": round(statistics.mean(g(r)["brier"] for r in rows), 4),
            "by_actual": by}


def write(o: OIS, kspread_on, meetings, decisions, cd91_rows, current=None, cd91_second=None) -> dict:
    out = backtest(o, kspread_on, meetings, decisions, cd91_rows, cd91_second=cd91_second)
    out["current"] = current
    write_json(SITE_DATA / "kofr_ois.json", out)
    return out
