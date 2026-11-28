"""액면 이표채 수익률(par yield) → 무이표(제로) 수익률 변환(프로토콜 v3 §D).

- 입력: 통안채 91일(0.25년)·국고채 1년은 이미 무이표로 취급, 국고채 3·5·10년은 연 2회 이자 par 수익률로 취급.
- 0.5년 격자에서 par 수익률을 PCHIP 보간(매듭 1·3·5·10년)한 뒤 부트스트래핑, 연속복리 제로 수익률(%)로 낸다.
- 0.5년 제로는 통안채 91일(0.25년)과 국고채 1년 제로 사이를 선형 보간한다. 국고채 곡선과 통안채를 합친 곡선이 아니라,
  1년 이하 구간만 통안채 91일로 잇는다(두 시장을 한 곡선으로 보지 않는 한계는 결과 문서에 적는다).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

COLS = ["msb91", "ktb1y", "ktb3y", "ktb5y", "ktb10y"]
KNOT = np.array([1.0, 3.0, 5.0, 10.0])
GRID = np.arange(0.5, 10.0 + 1e-9, 0.5)


def cc(y):
    """반기복리 수익률(%) → 연속복리(%)."""
    return 200.0 * np.log(1.0 + y / 200.0)


def par_to_zero_row(msb91: float, k1: float, k3: float, k5: float, k10: float) -> dict[float, float]:
    """한 날짜의 제로 수익률(%, 연속복리) 사전. 키는 만기(연)."""
    pchip = PchipInterpolator(KNOT, np.array([k1, k3, k5, k10]) / 100.0)
    # 1년 이하(통안채 91일·국고채 1년)는 무이표로 보되, 호가 수익률을 반기복리 기준으로 보고 연속복리로 바꾼다(par 3·5·10년과 같은 관행)
    m_cc, k1_cc = cc(msb91), cc(k1)
    z = {0.25: m_cc, 0.5: m_cc + (k1_cc - m_cc) * (0.25 / 0.75), 1.0: k1_cc}
    df = {0.5: np.exp(-z[0.5] / 100 * 0.5), 1.0: np.exp(-k1_cc / 100 * 1.0)}
    for T in GRID[2:]:
        c = float(pchip(T))
        n = int(round(T / 0.5))
        s = sum(df[GRID[i]] for i in range(n - 1))          # t=0.5 … T−0.5
        d = (1.0 - c / 2.0 * s) / (1.0 + c / 2.0)
        df[T] = d
        z[T] = -np.log(d) / T * 100.0
    return z


def par_to_zero(y: pd.DataFrame) -> pd.DataFrame:
    """열 msb91·ktb1y·ktb3y·ktb5y·ktb10y를 같은 이름의 제로 수익률로 바꾼 표(그 외 열은 버린다)."""
    out = []
    idx = []
    for dt, r in y[COLS].dropna().iterrows():
        z = par_to_zero_row(*[float(r[c]) for c in COLS])
        out.append([z[0.25], z[1.0], z[3.0], z[5.0], z[10.0]])
        idx.append(dt)
    return pd.DataFrame(out, index=pd.DatetimeIndex(idx), columns=COLS)


def compare(y: pd.DataFrame, z: pd.DataFrame) -> dict:
    """par − zero 차이(bp) 요약."""
    """par − zero(bp)를 둘로 나눠 적는다: (a) 복리 관행(반기→연속)만, (b) 이표채→무이표 부트스트랩."""
    out = {}
    for c in ("msb91", "ktb1y", "ktb3y", "ktb5y", "ktb10y"):
        par = y.loc[z.index, c]
        comp = par - cc(par)                       # (a) 복리 관행 차이(%)
        boot = cc(par) - z[c]                      # (b) 부트스트랩 차이(%)
        out[c] = {"total_bp": float((par - z[c]).mean() * 100), "compounding_bp": float(comp.mean() * 100), "bootstrap_bp": float(boot.mean() * 100),
                  "bootstrap_max_abs_bp": float(boot.abs().max() * 100)}
    return out
