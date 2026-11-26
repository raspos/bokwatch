"""BOK WATCH 3.0 워크포워드 평가 엔진(프로토콜: docs/engine3/03-protocol.md).

- 표본: 금통위 2008-01-10~2026-10-22, 결과는 회의일 기준금리 변화.
- 시계 D(달력일 60·30·14·7·1), 관측일 = 회의일 − D 이전 마지막 영업일 종가.
- 모든 모형은 관측일까지의 자료만 쓴다. 확률 변환은 운영 코드의 model.move_distribution.
"""
from __future__ import annotations

import sys
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bokwatch import market, model  # noqa: E402

FAILS, FAIL_EX = {}, {}
HORIZONS = (60, 30, 14, 7, 1)
CL = ("hike", "hold", "cut")
EVAL_START, FINAL_START, LAST_MEETING = "2012-01-01", "2023-01-01", "2026-10-22"
MAT = np.array([0.25, 1.0, 3.0, 5.0, 10.0])      # 곡선 모형 만기(연)
CURVE = ["msb91", "ktb1y", "ktb3y", "ktb5y", "ktb10y"]


# ------------------------------------------------------------------ 자료
def load():
    y = pd.read_csv(ROOT / "research" / "yields_long.csv", parse_dates=["date"]).set_index("date")
    base = y["base"].ffill()
    yd = y.dropna(subset=["ktb3y"]).drop(columns=["base"])
    meet = pd.to_datetime(pd.read_csv(ROOT / "data" / "meetings_history.csv")["date"])
    meet = [m for m in meet if pd.Timestamp("2008-01-01") <= m <= pd.Timestamp(LAST_MEETING)]
    return yd, base, meet


def outcome(base: pd.Series, m: pd.Timestamp) -> tuple[str, float] | None:
    if m not in base.index:
        return None
    prev = base.loc[: m - pd.Timedelta(days=1)]
    if prev.empty:
        return None
    d = float(base.loc[m] - prev.iloc[-1])
    return ("hike" if d > 1e-9 else "cut" if d < -1e-9 else "hold"), d


def rows_for_market(yd: pd.DataFrame, base: pd.Series) -> list[dict]:
    """운영 코드(market.pit_spread)가 읽는 형식. 통안채 91일과 기준금리만 쓴다."""
    out = []
    for dt, v in yd["msb91"].dropna().items():
        out.append({"date": dt.date().isoformat(), "id": "msb91", "value": float(v), "source": "ECOS"})
    for dt, v in base.items():
        out.append({"date": dt.date().isoformat(), "id": "base", "value": float(v), "source": "ECOS"})
    return out


def probs_from_delta(delta: float) -> dict:
    dist = model.move_distribution(float(delta))
    hike = sum(v for k, v in dist.items() if k > 0)
    cut = sum(v for k, v in dist.items() if k < 0)
    return {"hike": hike, "hold": max(0.0, 1 - hike - cut), "cut": cut}


# ------------------------------------------------------------------ 모형
class Hold:
    name = "M0 항상 동결"

    def predict(self, ctx):
        return {"hike": 0.0, "hold": 1.0, "cut": 0.0}, 0.0


class Frequency:
    name = "M0b 과거 빈도"

    def predict(self, ctx):
        past = [a for a in ctx["past_actuals"]]
        n = len(past)
        c = {k: (sum(1 for a in past if a == k) + 1) / (n + 3) for k in CL}      # 라플라스 평활
        return c, 0.25 * (c["hike"] - c["cut"])


class Msb91:
    """통안채 91일 단독. 운영 산식(model.solve, 당시까지 자료로 추정한 정상 스프레드)을 그대로 쓴다."""
    name = "M2 통안채 91일 단독"

    def __init__(self, rows, meetings_all):
        self.rows, self.meetings_all = rows, meetings_all

    def predict(self, ctx):
        obs, r0, mt = ctx["obs"].date(), ctx["r0"], ctx["meeting"].date()
        v = ctx["yields"].get("msb91")
        if v is None or np.isnan(v):
            return None
        sp = market.pit_spread(self.rows, "msb91", obs)
        sp = 0.0 if sp is None else sp
        ms = [m for m in self.meetings_all if m > obs]
        res = model.solve(obs, r0, [model.Instrument("msb91", float(v), 91, sp, "ECOS")], ms, "auto")
        m = next((x for x in res.meetings if x.date == mt and x.in_range), None)
        if m is None:
            return None
        return {"hike": m.p_hike, "hold": m.p_hold, "cut": m.p_cut}, float(m.expected - r0)


def _weekly(yd):
    w = yd.resample("W-FRI").last().dropna(subset=CURVE)
    return w


class DnsVar:
    """Dynamic Nelson-Siegel(λ 고정) 요인의 VAR(1) 예측으로 단기금리 기대 변화를 낸다."""
    name = "M7 DNS-VAR"
    LAM = 0.0609          # 월 단위(사전 고정)

    def __init__(self, yd, min_weeks=156, refit=13):
        self.w = _weekly(yd)
        self.min_weeks, self.refit = min_weeks, refit
        tau = MAT * 12
        f1 = (1 - np.exp(-self.LAM * tau)) / (self.LAM * tau)
        self.B = np.column_stack([np.ones_like(tau), f1, f1 - np.exp(-self.LAM * tau)])
        self.cache = {}

    def factors(self, y):
        return np.linalg.lstsq(self.B, y, rcond=None)[0]

    def fit_for(self, obs):
        idx = [i for i in range(self.min_weeks, len(self.w), self.refit) if self.w.index[i] <= obs]
        if not idx:
            return None
        end = idx[-1]
        if end not in self.cache:
            sub = self.w.iloc[: end + 1][CURVE].values
            F = np.array([self.factors(r) for r in sub])
            Z = np.column_stack([np.ones(len(F) - 1), F[:-1]])
            c, *_ = np.linalg.lstsq(Z, F[1:], rcond=None)
            self.cache[end] = (c[0], c[1:].T)
        return self.cache[end]

    def predict(self, ctx):
        fit = self.fit_for(ctx["obs"])
        if fit is None:
            return None
        mu, Phi = fit
        y = np.array([ctx["yields"][c] for c in CURVE], float)
        if np.isnan(y).any():
            return None
        f = self.factors(y)
        weeks = max(1, round((ctx["meeting"] - ctx["obs"]).days / 7)) + 1
        fh = f.copy()
        for _ in range(weeks):
            fh = mu + Phi @ fh
        d = (fh[0] + fh[1]) - (f[0] + f[1])         # τ→0 극한(수준+기울기)의 변화
        return probs_from_delta(d), float(d)


class AcmVar:
    """ACM의 P측도 기대 정책금리(VAR 예측). research/acm_backtest.py의 ACM 클래스를 쓴다."""
    name = "M5 ACM-VAR"

    def __init__(self, yd, base, min_weeks=156, refit=13):
        import importlib
        self.mod = importlib.import_module("research.acm_backtest")
        self.cols = self.mod.COLS
        yy = yd[self.cols].dropna()
        self.w = yy.resample("W-FRI").last().dropna()
        self.base_w = base.resample("W-FRI").last().reindex(self.w.index).ffill()
        self.min_weeks, self.refit = min_weeks, refit
        self.cache = {}

    def fit_for(self, obs):
        idx = [i for i in range(self.min_weeks, len(self.w), self.refit) if self.w.index[i] <= obs]
        if not idx:
            return None
        end = idx[-1]
        if end not in self.cache:
            self.cache[end] = self.mod.ACM(self.w.iloc[: end + 1].values, self.base_w.iloc[: end + 1].values)
        return self.cache[end]

    def predict(self, ctx):
        acm = self.fit_for(ctx["obs"])
        if acm is None:
            return None
        y = np.array([ctx["yields"][c] for c in self.cols], float)
        if np.isnan(y).any():
            return None
        x = acm.pcs(y)
        weeks = max(1, round((ctx["meeting"] - ctx["obs"]).days / 7)) + 1
        d = acm.expected_rate(x, weeks) - ctx["r0"]
        return probs_from_delta(d), float(d)


# ------------------------------------------------------------------ 칸 생성
def build_cells(models, yd, base, meet, progress=False):
    idx = yd.index
    meet_ts = sorted(meet)
    actuals = []
    cells = []
    for k, m in enumerate(meet_ts):
        out = outcome(base, m)
        if out is None:
            continue
        act, delta = out
        past = [a for a in actuals]
        for D in HORIZONS:
            cut = m - pd.Timedelta(days=D)
            j = bisect_right(idx, cut) - 1
            if j < 0:
                continue
            obs = idx[j]
            if obs >= m:
                continue
            r0 = float(base.loc[:obs].iloc[-1])
            ctx = {"meeting": m, "obs": obs, "r0": r0, "yields": yd.iloc[j].to_dict(), "past_actuals": past}
            for mdl in models:
                try:
                    res = mdl.predict(ctx)
                except Exception as e:  # noqa: BLE001
                    FAILS[mdl.name] = FAILS.get(mdl.name, 0) + 1
                    FAIL_EX.setdefault(mdl.name, repr(e))
                    res = None
                if res is None:
                    continue
                p, ed = res
                cells.append({"meeting": m.date().isoformat(), "D": D, "actual": act, "delta": delta, "model": mdl.name,
                              "p_hike": p["hike"], "p_hold": p["hold"], "p_cut": p["cut"], "exp_delta": ed,
                              "prior12": float(base.loc[:obs].iloc[-1] - base.loc[:obs - pd.Timedelta(days=365)].iloc[-1])
                              if obs - pd.Timedelta(days=365) >= base.index[0] else np.nan})
        actuals.append(act)
        if progress and k % 20 == 0:
            print("meeting", m.date(), len(cells), flush=True)
    return pd.DataFrame(cells)
