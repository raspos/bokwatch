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


class OisProd:
    """합성 KOFR OIS 단독(운영 코드 awm_data.ois_model 그대로). 2023-02 이후 회의만."""
    name = "M1 합성 OIS 단독"

    def __init__(self):
        from bokwatch import awm_data
        self.ad = awm_data
        self.inp = awm_data.Inputs()

    def predict(self, ctx):
        if ctx["meeting"] < pd.Timestamp("2023-02-01"):
            return None
        obs, mt = ctx["obs"].date(), ctx["meeting"].date()
        r0 = self.inp.base(obs)
        if r0 is None:
            return None
        o = self.ad.ois_model(self.inp, obs, r0, mt, self.inp.ois_policy)
        if not o.get("ok"):
            return None
        p = o["p"]
        return {"hike": p["hike"], "hold": p["hold"], "cut": p["cut"]}, float(o.get("expected", r0) - r0)


class Blend50:
    """운영 50:50: 합성 OIS와 통안채 91일의 세 범주 확률을 단순 평균한다."""
    name = "M3 운영 50:50(OIS+통안채)"

    def __init__(self, a, b):
        self.a, self.b = a, b

    def predict(self, ctx):
        x, y = self.a.predict(ctx), self.b.predict(ctx)
        if x is None or y is None:
            return None
        p = {k: 0.5 * x[0][k] + 0.5 * y[0][k] for k in CL}
        return p, 0.5 * (x[1] + y[1])


class Shrink:
    """모형 확률을 과거 빈도 쪽으로 시계별로 축소한다. 가중치 w_D는 이전 회의의 Brier를 최소화하는 값(0.1 격자)."""

    def __init__(self, base, freq, name, min_meetings=20):
        self.base, self.freq, self.name, self.min_n = base, freq, name, min_meetings
        self.hist = {}          # D → [(p_base, p_freq, actual)]
        self.pending = {}       # (meeting) → [(D, p_base, p_freq)]

    def weight(self, D):
        h = self.hist.get(D, [])
        if len(h) < self.min_n:
            return 0.5
        best, bw = 9e9, 0.5
        for w in [i / 10 for i in range(11)]:
            e = 0.0
            for pb, pf, a in h:
                for c in CL:
                    q = w * pb[c] + (1 - w) * pf[c]
                    e += (q - (1.0 if c == a else 0.0)) ** 2
            if e < best - 1e-12:
                best, bw = e, w
        return bw

    def predict(self, ctx):
        r = self.base.predict(ctx)
        if r is None:
            return None
        pf, ef = self.freq.predict(ctx)
        w = self.weight(ctx.get("D"))
        p = {k: w * r[0][k] + (1 - w) * pf[k] for k in CL}
        self.pending.setdefault(ctx["meeting"], []).append((ctx.get("D"), r[0], pf))
        return p, w * r[1] + (1 - w) * ef

    def update(self, meeting, actual):
        for D, pb, pf in self.pending.pop(meeting, []):
            self.hist.setdefault(D, []).append((pb, pf, actual))


class MaxEntMeetings:
    """M8: 통안채 91일 금리 한 식으로 만기 안의 모든 회의를 날짜·적용 일수로 직접 풀이한다.
    식 L = Σ a_k·Δ_k (L = T·(y − s − r0), a_k = 회의 k부터 만기까지 일수)는 회의가 둘 이상이면 해가 유일하지 않다.
    회의마다 독립인 과거 빈도 사전분포에서 출발해 제약을 만족하며 KL이 가장 작은 분포(지수 기울임)를 쓴다."""
    name = "M8 회의일 기반 풀이(최대 엔트로피)"
    STEPS = (-0.25, 0.0, 0.25)

    def __init__(self, rows, meetings_all, freq):
        self.rows, self.meetings_all, self.freq = rows, meetings_all, freq

    def predict(self, ctx):
        obs, r0, mt = ctx["obs"].date(), ctx["r0"], ctx["meeting"].date()
        v = ctx["yields"].get("msb91")
        if v is None or np.isnan(v):
            return None
        sp = market.pit_spread(self.rows, "msb91", obs)
        sp = 0.0 if sp is None else sp
        T = 91
        start = model.settlement_start(obs)
        ms = sorted(m for m in self.meetings_all if start <= m < start + timedelta(days=T))
        if mt not in ms:
            return None
        a = np.array(model.exposure_days(start, T, ms), float)
        L = T * (float(v) - sp - r0)
        pf, _ = self.freq.predict(ctx)
        prior = np.array([pf["cut"], pf["hold"], pf["hike"]])
        st = np.array(self.STEPS)

        def dist(lam):
            out = []
            for ak in a:
                w = prior * np.exp(np.clip(lam * ak * st, -50, 50))
                out.append(w / w.sum())
            return out

        def g(lam):
            return float(sum(ak * (d * st).sum() for ak, d in zip(a, dist(lam)))) - L

        lo, hi = -400.0, 400.0
        if g(lo) > 0:
            lam = lo
        elif g(hi) < 0:
            lam = hi
        else:
            for _ in range(80):
                mid = (lo + hi) / 2
                if g(mid) > 0:
                    hi = mid
                else:
                    lo = mid
            lam = (lo + hi) / 2
        d = dist(lam)[ms.index(mt)]
        p = {"cut": float(d[0]), "hold": float(d[1]), "hike": float(d[2])}
        return p, float((d * st).sum())


class Ensemble:
    """M11: 구성원 확률을 시계별 과거 평균 Brier로 가중(가중치 ∝ exp(−η·평균 Brier)). 이전 회의가 10개 미만이면 균등."""

    def __init__(self, members, name, eta=10.0, min_n=10):
        self.members, self.name, self.eta, self.min_n = members, name, eta, min_n
        self.hist = {}          # (D, member name) → [brier]
        self.pending = {}

    def weights(self, D, names):
        sc = {}
        for n in names:
            h = self.hist.get((D, n), [])
            sc[n] = float(np.mean(h)) if len(h) >= self.min_n else None
        if any(v is None for v in sc.values()):
            return {n: 1.0 / len(names) for n in names}
        w = {n: np.exp(-self.eta * v) for n, v in sc.items()}
        z = sum(w.values())
        return {n: x / z for n, x in w.items()}

    def predict(self, ctx):
        preds = {}
        for m in self.members:
            try:
                r = m.predict(ctx)
            except Exception:  # noqa: BLE001
                r = None
            if r is not None:
                preds[m.name] = r
        if len(preds) < len(self.members):
            return None
        D = ctx.get("D")
        w = self.weights(D, list(preds))
        p = {k: sum(w[n] * preds[n][0][k] for n in preds) for k in CL}
        ed = sum(w[n] * preds[n][1] for n in preds)
        self.pending.setdefault(ctx["meeting"], []).append((D, {n: preds[n][0] for n in preds}))
        return p, ed

    def update(self, meeting, actual):
        for D, pm in self.pending.pop(meeting, []):
            for n, p in pm.items():
                b = sum((p[c] - (1.0 if c == actual else 0.0)) ** 2 for c in CL)
                self.hist.setdefault((D, n), []).append(b)


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
            ctx = {"meeting": m, "obs": obs, "r0": r0, "yields": yd.iloc[j].to_dict(), "past_actuals": past, "D": D}
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
        for mdl in models:
            if hasattr(mdl, "update"):
                mdl.update(m, act)
        actuals.append(act)
        if progress and k % 20 == 0:
            print("meeting", m.date(), len(cells), flush=True)
    return pd.DataFrame(cells)
