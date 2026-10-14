"""금통위 회의별 금리 확률 계산 (FedWatch 방식 한국판). 순수 함수만 둔다.

기호
  r0   현재 기준금리(%)
  t_k  회의 k의 날짜 (결정은 회의 당일부터 적용)
  E_k  회의 k 뒤 기대 기준금리,  D_k = E_k - r0  (누적 변화, %p)
  Δ_k  = E_k - E_{k-1}

상품 i(금리 y_i, 정상 스프레드 s_i, 만기 T_i일)는
  T_i·(y_i - s_i) = Σ_k E_k · (구간 k의 일수)
를 만족한다고 본다. 구간은 결제일(기준일 다음 날)부터 센다.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

STEP = 0.25  # 금리 단위 %p
EPS = 1e-9


@dataclass
class Instrument:
    name: str
    rate: float          # %
    tenor_days: int
    spread: float = 0.0  # 정상 스프레드 %p
    source: str = ""

    @property
    def adj_rate(self) -> float:
        return self.rate - self.spread


@dataclass
class MeetingResult:
    date: date
    expected: float               # E_k
    delta: float                  # Δ_k (%p)
    move_probs: dict              # {bp 변화: 확률}
    p_hike: float
    p_hold: float
    p_cut: float
    level_probs: dict             # {금리 수준(%): 확률}
    method: str                   # bootstrap | min_hike | lsq | out_of_range
    in_range: bool = True


@dataclass
class ModelResult:
    asof: date
    start: date
    r0: float
    meetings: list = field(default_factory=list)
    method: str = ""
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------- 기초 함수
def settlement_start(asof: date) -> date:
    """기준일 종가 금리는 다음 날부터 [start, start+T) 구간을 덮는다고 본다."""
    return asof + timedelta(days=1)


def segment_days(start: date, tenor_days: int, meetings: list[date]) -> list[int]:
    """[r0 구간, 회의1 뒤, 회의2 뒤, ...] 일수. 만기 밖 회의는 0."""
    end = start + timedelta(days=tenor_days)
    bounds = [start] + [max(start, m) for m in meetings] + [end]
    out = []
    for k in range(len(meetings) + 1):
        a = min(bounds[k], end)
        # 다음 회의 시작 전까지 (회의가 만기 밖이면 만기까지)
        b = min(bounds[k + 1], end) if k < len(meetings) else end
        out.append(max(0, (b - a).days))
    return out


def exposure_days(start: date, tenor_days: int, meetings: list[date]) -> list[int]:
    """회의 k의 Δ_k가 영향을 주는 일수 = max(0, 만기 - 회의일)."""
    end = start + timedelta(days=tenor_days)
    return [max(0, (end - max(start, m)).days) for m in meetings]


def move_distribution(delta: float, step: float = STEP) -> dict:
    """Δ를 0.25%p 단위 이동 확률로. 25bp 이상이면 25bp 확정 + 초과분을 50bp로."""
    if abs(delta) < EPS:
        return {0: 1.0}
    sign = 1 if delta > 0 else -1
    x = abs(delta) / step
    n = math.floor(x + EPS)
    frac = x - n
    if frac < EPS:
        return {sign * n * 25: 1.0}
    out = {sign * n * 25: 1 - frac, sign * (n + 1) * 25: frac}
    return {k: v for k, v in out.items() if v > EPS}


def level_distribution(expected: float, r0: float, step: float = STEP) -> dict:
    """회의 뒤 목표금리 분포. 트리의 경로를 금리 수준별로 합산하면
    기대값 E_k를 갖는 최소분산 분포(인접 두 격자점)가 된다(FedWatch 수준 방식)."""
    x = (expected - r0) / step
    lo = math.floor(x + EPS)
    frac = x - lo
    lv_lo = round(r0 + lo * step, 4)
    if frac < EPS or frac > 1 - EPS:
        return {round(r0 + round(x) * step, 4): 1.0}
    return {lv_lo: 1 - frac, round(lv_lo + step, 4): frac}


# ---------------------------------------------------------------- 풀이
def _fill_min_hike(weights: list[float], resid: float, base: float, step: float = STEP):
    """새 회의들의 누적변화 D를 base에서 출발해 '최소 인상 경로'로 채운다.
    resid = Σ w_k (D_k - base) 가 되도록, 늦은 회의부터 격자 상한(base 위 m단계)까지 채우고
    모자라면 m을 늘린다. 음수면 인하 방향으로 대칭."""
    n = len(weights)
    if n == 0:
        return []
    sign = 1 if resid >= 0 else -1
    target = abs(resid)
    if target < EPS or all(w <= 0 for w in weights):
        return [base] * n
    m = 1
    while True:
        cap = m * step
        inc = [0.0] * n
        left = target
        for k in range(n - 1, -1, -1):
            if weights[k] <= 0:
                continue
            inc[k] = min(cap, left / weights[k])
            left -= inc[k] * weights[k]
            if left <= EPS:
                break
        if left <= EPS or m > 40:
            # 단조성: 앞 회의 누적이 뒤 회의보다 크면 안 됨 (채우는 순서상 보장)
            return [base + sign * v for v in inc]
        m += 1


def solve(asof: date, r0: float, instruments: list[Instrument], meetings: list[date],
          method: str = "auto", step: float = STEP) -> ModelResult:
    """회의별 기대 기준금리 E_k와 확률을 구한다.

    method
      auto      : 짧은 만기부터 부트스트래핑. 한 구간에 새 회의가 2개 이상이면 최소 인상 경로
      min_hike  : 모든 미지수를 최소 인상 경로로 (가장 긴 만기 묶음 기준)
      lsq       : scipy.optimize.lsq_linear, Δ 부호 제약 비음수(인하 국면은 비양수) 최소제곱
    """
    start = settlement_start(asof)
    meetings = sorted(m for m in meetings if m >= start - timedelta(days=0))
    meetings = [m for m in meetings if m > asof]
    res = ModelResult(asof=asof, start=start, r0=r0)
    if not instruments:
        res.notes.append("투입 금리 없음")
        return res

    # 만기 묶음(7일 이내는 같은 묶음, 금리는 평균)
    ins = sorted(instruments, key=lambda i: i.tenor_days)
    buckets: list[list[Instrument]] = []
    for i in ins:
        if buckets and i.tenor_days - buckets[-1][0].tenor_days <= 7:
            buckets[-1].append(i)
        else:
            buckets.append([i])

    def bucket_eq(b):
        T = round(sum(i.tenor_days for i in b) / len(b))
        y = sum(i.adj_rate for i in b) / len(b)
        return T, y

    D = [None] * len(meetings)
    how = [None] * len(meetings)
    max_T = bucket_eq(buckets[-1])[0]

    if method == "lsq":
        D, how = _solve_lsq(start, r0, buckets, meetings, bucket_eq)
    elif method == "min_hike":
        T, y = bucket_eq(buckets[-1])
        w = exposure_days(start, T, meetings)
        idx = [k for k, x in enumerate(w) if x > 0]
        seg = _seg_for_new(start, T, meetings, idx)
        vals = _fill_min_hike(seg, T * (y - r0), 0.0, step)
        for k, v in zip(idx, vals):
            D[k], how[k] = v, "min_hike"
    else:
        solved = 0  # 앞에서부터 확정된 회의 수
        for b in buckets:
            T, y = bucket_eq(b)
            w = exposure_days(start, T, meetings)
            new = [k for k in range(solved, len(meetings)) if w[k] > 0]
            known = sum(w[k] * (D[k] - (D[k - 1] if k > 0 else 0.0)) for k in range(solved))
            # Σ_k w_k Δ_k = T(y - r0)  (Δ 표현)
            resid = T * (y - r0) - known
            base = D[solved - 1] if solved > 0 else 0.0
            if not new:
                continue  # 같은 회의 범위 → 앞 묶음이 이미 결정 (중복 정보)
            # Δ 표현을 누적 D 표현으로: Σ_{k∈new} seg_k·(D_k - base) = resid
            seg = _seg_for_new(start, T, meetings, new)
            if len(new) == 1:
                D[new[0]] = base + resid / seg[0]
                how[new[0]] = "bootstrap"
            else:
                vals = _fill_min_hike(seg, resid, base, step)
                for k, v in zip(new, vals):
                    D[k], how[k] = v, "min_hike"
            solved = new[-1] + 1

    prev = 0.0
    for k, m in enumerate(meetings):
        if D[k] is None:
            res.meetings.append(MeetingResult(m, float("nan"), float("nan"), {}, float("nan"),
                                              float("nan"), float("nan"), {}, "out_of_range", False))
            continue
        delta = D[k] - prev
        mv = move_distribution(delta, step)
        E = r0 + D[k]
        res.meetings.append(MeetingResult(
            date=m, expected=E, delta=delta, move_probs=mv,
            p_hike=sum(v for kk, v in mv.items() if kk > 0),
            p_hold=mv.get(0, 0.0),
            p_cut=sum(v for kk, v in mv.items() if kk < 0),
            level_probs=level_distribution(E, r0, step), method=how[k]))
        prev = D[k]
    used = sorted({mr.method for mr in res.meetings if mr.in_range})
    res.method = "+".join(used) if used else "none"
    if any(not mr.in_range for mr in res.meetings):
        res.notes.append(f"투입 상품 최장 만기({max_T}일) 밖 회의는 계산하지 않음")
    return res


def _seg_for_new(start, T, meetings, new):
    """새 회의들 각각의 '누적 D_k가 유지되는 구간' 일수(다음 회의 또는 만기까지)."""
    end = start + timedelta(days=T)
    out = []
    for j, k in enumerate(new):
        a = max(start, meetings[k])
        b = meetings[new[j + 1]] if j + 1 < len(new) else end
        out.append(max(0, (min(b, end) - a).days))
    return out


def _solve_lsq(start, r0, buckets, meetings, bucket_eq):
    import numpy as np
    from scipy.optimize import lsq_linear

    rows, rhs = [], []
    for b in buckets:
        T, y = bucket_eq(b)
        w = exposure_days(start, T, meetings)
        rows.append([x / T for x in w])
        rhs.append(y - r0)
    A, r = np.array(rows, float), np.array(rhs, float)
    active = [k for k in range(len(meetings)) if A[:, k].any()]
    A = A[:, active]
    sign = 1 if r.mean() >= 0 else -1
    lb, ub = (0, np.inf) if sign > 0 else (-np.inf, 0)
    sol = lsq_linear(A, r, bounds=(lb, ub), lsmr_tol="auto")
    D = [None] * len(meetings)
    how = [None] * len(meetings)
    acc = 0.0
    for j, k in enumerate(active):
        acc += float(sol.x[j])
        D[k], how[k] = acc, "lsq"
    return D, how


# ---------------------------------------------------------------- 스프레드·민감도
def normal_spread(spreads_bp: list[float]) -> float:
    """장기 동결 국면 (y - r0) 관측치의 중앙값 → %p."""
    vals = [x for x in spreads_bp if x is not None and not math.isnan(x)]
    if not vals:
        raise ValueError("정상 스프레드 추정용 관측치 없음")
    return statistics.median(vals) / 100.0


def sensitivity(asof, r0, instruments, meetings, method="auto", shifts_bp=(-5, 0, 5)):
    """스프레드 −5bp·기본·+5bp 결과."""
    out = {}
    for s in shifts_bp:
        shifted = [Instrument(i.name, i.rate, i.tenor_days, round(i.spread + s / 100.0, 6), i.source)
                   for i in instruments]
        out[s] = solve(asof, r0, shifted, meetings, method)
    return out


def result_to_dict(res: ModelResult) -> dict:
    def r(x, n=4):
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)
    return {
        "asof": res.asof.isoformat(), "start": res.start.isoformat(), "r0": res.r0,
        "method": res.method, "notes": res.notes,
        "meetings": [{
            "date": m.date.isoformat(), "expected": r(m.expected), "delta_bp": r(m.delta * 100 if m.in_range else None, 2),
            "p_hike": r(m.p_hike), "p_hold": r(m.p_hold), "p_cut": r(m.p_cut),
            "moves": {str(k): r(v) for k, v in sorted(m.move_probs.items())},
            "levels": {f"{k:.2f}": r(v) for k, v in sorted(m.level_probs.items())},
            "method": m.method, "in_range": m.in_range,
        } for m in res.meetings],
    }
