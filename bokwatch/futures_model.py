"""KOFR 3개월 선물 → 금통위 회의별 확률 (CME FedWatch·SOFR 선물 방식). 순수 함수만 둔다.

선물 c의 가격 P_c = 100 − R_c. R_c는 기준기간 [a_c, b_c)의 KOFR 일별 복리금리(연율, ACT/365).
  기준기간: 결제월 셋째 수요일 3개월 전 ~ 결제월 셋째 수요일 (config.futures.window로 바꿀 수 있다)
복리 R을 같은 기간의 단순평균 KOFR로 바꾸면  avg ≈ 365/N · ln(1 + R·N/365)  (오차 0.1bp 미만)

기준일 t에서 기준기간은 이미 지난 날(공시된 KOFR)과 남은 날로 나뉜다.
  N·avg = Σ(지난 날 KOFR) + Σ(남은 날 기대 KOFR)
남은 날 기대 KOFR = (그날 적용되는 기대 기준금리) + s.  s = KOFR − 기준금리 정상 차이(최근 관측 중앙값).
그날 기대 기준금리는 회의 k 뒤부터 E_k(회의 당일부터 적용), 첫 회의 전은 r0.

미지수 E_k를 결제월 여러 개로 동시에 푼다(최소제곱). 확정 일정 밖 회의가 기준기간에 걸리는 선물은 쓰지 않는다.
회의 k의 Δ_k = E_k − E_{k−1}를 model.move_distribution으로 확률로 바꾼다(기존 CD 모델과 같은 규칙).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from . import model


def third_wednesday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(2 - d.weekday()) % 7)  # 첫 수요일
    return d + timedelta(days=14)


def add_months(y: int, m: int, k: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def ref_window(contract: str) -> tuple[date, date]:
    """'2026-11' → [8월 셋째 수요일, 11월 셋째 수요일)."""
    y, m = map(int, contract.split("-"))
    py, pm = add_months(y, m, -3)
    return third_wednesday(py, pm), third_wednesday(y, m)


def compounded_to_average(R: float, start: date, end: date) -> float:
    """복리 연율 R(%) → 같은 기간 단순평균 금리(%)."""
    n = (end - start).days
    return 365.0 / n * math.log(1 + R / 100 * n / 365) * 100


@dataclass
class Contract:
    month: str          # 'YYYY-MM' 결제월
    price: float        # 정산가격 (100 − 금리)
    volume: int = 0     # 거래량(계약)
    oi: int = 0         # 미결제약정

    @property
    def rate(self) -> float:
        return 100.0 - self.price


def carry_fixings(fixings: dict[str, float], start: date, end: date) -> list[float]:
    """[start, end) 각 날짜의 KOFR. 휴일은 직전 공시값을 쓴다(없으면 None)."""
    out, last = [], None
    for k in sorted(x for x in fixings if x < start.isoformat()):
        last = fixings[k]
    d = start
    while d < end:
        v = fixings.get(d.isoformat())
        if v is not None:
            last = v
        out.append(last)
        d += timedelta(days=1)
    return out


def solve(asof: date, r0: float, contracts: list[Contract], fixings: dict[str, float], meetings: list[date],
          spread: float, known_through: date, ridge: float = 1e-4) -> dict:
    """회의별 기대 기준금리와 확률.

    fixings: {'YYYY-MM-DD': KOFR(%)} 기준일까지 공시분. spread: KOFR − 기준금리 정상 차이(%p).
    반환: {"meetings": [...], "used": [...], "skipped": [...]}  (meetings 항목 형식은 model.result_to_dict와 같다)
    """
    import numpy as np
    from scipy.optimize import lsq_linear

    ms = sorted(m for m in meetings if m > asof and m <= known_through)
    used, skipped, rows, rhs = [], [], [], []
    for c in sorted(contracts, key=lambda c: c.month):
        a, b = ref_window(c.month)
        if b <= asof + timedelta(days=1):
            skipped.append({"month": c.month, "why": "기준기간 종료"})
            continue
        if b - timedelta(days=1) > known_through:
            skipped.append({"month": c.month, "why": f"기준기간({a}~{b - timedelta(days=1)})이 확정 일정({known_through}) 밖"})
            continue
        n = (b - a).days
        avg = compounded_to_average(c.rate, a, b)
        past_end = min(b, asof + timedelta(days=1))  # 기준일까지는 공시분(기준일 당일 포함)
        past = carry_fixings(fixings, a, past_end) if past_end > a else []
        if any(v is None for v in past):
            skipped.append({"month": c.month, "why": "기준기간 앞부분 KOFR 공시값 없음"})
            continue
        fut_start = max(a, asof + timedelta(days=1))
        # 남은 날을 회의 구간별 일수로: [r0 구간, 회의1 뒤, 회의2 뒤, ...]
        days = model.segment_days(fut_start, (b - fut_start).days, ms)
        target = n * avg - sum(past) - (b - fut_start).days * spread - days[0] * r0
        rows.append(days[1:])
        rhs.append(target)
        used.append({"month": c.month, "start": a.isoformat(), "end": (b - timedelta(days=1)).isoformat(),
                     "price": c.price, "rate": round(c.rate, 4), "avg": round(avg, 4),
                     "past_days": len(past), "future_days": (b - fut_start).days,
                     "volume": c.volume, "oi": c.oi})
    out = {"meetings": [], "used": used, "skipped": skipped, "spread": spread, "r0": r0, "asof": asof.isoformat()}
    if not rows or not ms:
        return out
    A, y = np.array(rows, float), np.array(rhs, float)
    active = [k for k in range(len(ms)) if A[:, k].any()]
    A = A[:, active]
    # 누적 표현 E_k = r0 + Σ_{j≤k} Δ_j 로 바꿔 Δ에 약한 능선 벌점(식보다 미지수가 많을 때 안정화)
    L = np.tril(np.ones((len(active), len(active))))
    M = A @ L
    scale = max(1.0, float(np.abs(M).max()))
    Mr = np.vstack([M / scale, math.sqrt(ridge) * np.eye(len(active))])
    yr = np.concatenate([(y - A.sum(axis=1) * r0) / scale, np.zeros(len(active))])
    sol = lsq_linear(Mr, yr, lsmr_tol="auto")
    deltas = sol.x
    resid = (M @ deltas - (y - A.sum(axis=1) * r0)) / np.array([max(1, sum(r)) for r in rows])
    out["fit_bp"] = [round(float(x) * 100, 2) for x in resid]
    prev = r0
    for j, k in enumerate(active):
        E = r0 + float(deltas[: j + 1].sum())
        delta = E - prev
        mv = model.move_distribution(delta)
        out["meetings"].append({
            "date": ms[k].isoformat(), "expected": round(E, 4), "delta_bp": round(delta * 100, 2),
            "p_hike": round(sum(v for kk, v in mv.items() if kk > 0), 4), "p_hold": round(mv.get(0, 0.0), 4),
            "p_cut": round(sum(v for kk, v in mv.items() if kk < 0), 4),
            "moves": {str(kk): round(v, 4) for kk, v in sorted(mv.items())},
            "levels": {f"{kk:.2f}": round(v, 4) for kk, v in sorted(model.level_distribution(E, r0).items())},
            "method": "kofr_futures", "in_range": True})
        prev = E
    return out


def price_for_path(contract_month: str, path, fixings: dict[str, float], asof: date, spread: float) -> float:
    """검증용: 기준금리 경로 path(date→기준금리)로 선물 가격을 만든다(복리)."""
    a, b = ref_window(contract_month)
    past = carry_fixings(fixings, a, min(b, asof + timedelta(days=1))) if asof >= a else []
    rates = list(past)
    d = max(a, asof + timedelta(days=1))
    while d < b:
        rates.append(path(d) + spread)
        d += timedelta(days=1)
    comp = 1.0
    for r in rates:
        comp *= 1 + r / 100 / 365
    n = (b - a).days
    return 100 - (comp - 1) * 365 / n * 100
