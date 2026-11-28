"""3.0 4차: 제로 커브 기반 모형(M5z·M7z), AFNS(M6·M13), TP 보정 M8(M12), M8 사전분포 변형(프로토콜 v3 §D·§E)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np

import wf
from wf import CL, CURVE, model, market
import afns
import acmz

ZMAT = np.array([0.25, 1.0, 3.0, 5.0, 10.0])


def _wk_until(yz, obs):
    """관측일까지 값으로 만든 주간(금요일) 표. 마지막 주는 관측일 값으로 채워 미래 정보를 쓰지 않는다."""
    return yz.loc[:obs].resample("W-FRI").last().dropna()


class DnsZero(wf.DnsVar):
    """M7z: M7(DNS-VAR)을 제로 수익률 패널로. ctx['yields']에 제로 값을 넣어 호출한다."""
    name = "M7z DNS-VAR(제로)"


class AcmZero:
    """M5z: ACM-VAR을 제로 수익률로(만기 격자 0.25·1·3·5·10)."""
    name = "M5z ACM-VAR(제로)"

    def __init__(self, yz, base, min_weeks=156, refit=13):
        self.cols = CURVE
        self.w = yz[self.cols].dropna().resample("W-FRI").last().dropna()
        self.base_w = base.resample("W-FRI").last().reindex(self.w.index).ffill()
        self.min_weeks, self.refit, self.cache = min_weeks, refit, {}
        self.tp_cache = {}

    def fit_for(self, obs):
        idx = [i for i in range(self.min_weeks, len(self.w), self.refit) if self.w.index[i] <= obs]
        if not idx:
            return None, None
        end = idx[-1]
        if end not in self.cache:
            self.cache[end] = acmz.ACM(self.w.iloc[: end + 1].values, self.base_w.iloc[: end + 1].values, ZMAT)
        return end, self.cache[end]

    def tp_mean(self, end, acm):
        """훈련 구간의 3개월 기간프리미엄 평균(제로 91일 수익률 − P 기대 평균 단기금리)."""
        if end not in self.tp_cache:
            Y = self.w.iloc[: end + 1].values
            tps = [acm.tp_short(acm.pcs(Y[i]), Y[i][0]) for i in range(len(Y))]
            self.tp_cache[end] = float(np.mean(tps))
        return self.tp_cache[end]

    def predict(self, ctx):
        end, acm = self.fit_for(ctx["obs"])
        if acm is None:
            return None
        y = np.array([ctx["yz"][c] for c in self.cols], float)
        if np.isnan(y).any():
            return None
        x = acm.pcs(y)
        weeks = max(1, round((ctx["meeting"] - ctx["obs"]).days / 7)) + 1
        d = acm.expected_rate(x, weeks) - ctx["r0"]
        return wf.probs_from_delta(d), float(d)

    def tp_dev(self, ctx):
        end, acm = self.fit_for(ctx["obs"])
        if acm is None:
            return None
        y = np.array([ctx["yz"][c] for c in self.cols], float)
        if np.isnan(y).any():
            return None
        return acm.tp_short(acm.pcs(y), y[0]) - self.tp_mean(end, acm)


class AfnsFit:
    """AFNS 추정·상태 필터를 맡는 도우미. 확장 창, 연 1회(52주) 재추정, 최소 156주."""

    def __init__(self, yz, cols, mat, min_weeks=156, refit=52, maxiter=300):
        self.yz, self.cols, self.mat = yz[cols].dropna(), cols, mat
        self.w = self.yz.resample("W-FRI").last().dropna()
        self.min_weeks, self.refit, self.maxiter = min_weeks, refit, maxiter
        self.fits, self.last_p = {}, None
        self.state_cache = {}

    def fit_for(self, obs):
        idx = [i for i in range(self.min_weeks, len(self.w), self.refit) if self.w.index[i] <= obs]
        if not idx:
            return None
        end = idx[-1]
        if end not in self.fits:
            a = afns.Afns(self.mat)
            Y = self.w.iloc[: end + 1].values / 100
            a.fit(Y, p0=self.last_p, maxiter=self.maxiter)
            self.last_p = a.par.copy()
            self.fits[end] = a
        return self.fits[end]

    def state(self, obs):
        key = obs
        if key in self.state_cache:
            return self.state_cache[key]
        a = self.fit_for(obs)
        if a is None:
            return None, None
        Y = _wk_until(self.yz[self.cols], obs).values / 100
        out = (a, a.filter_state(a.par, Y))
        self.state_cache[key] = out
        return out


class AfnsDirect:
    """M6: AFNS의 P측도 기대 단기금리 변화를 25bp 격자 확률로 바로 변환."""
    name = "M6 AFNS-직접"

    def __init__(self, fit: AfnsFit):
        self.f = fit

    def predict(self, ctx):
        a, x = self.f.state(ctx["obs"])
        if a is None:
            return None
        h = max(1, round((ctx["meeting"] - ctx["obs"]).days / 7)) + 1
        lam, kap, th, sig, sd = a.unpack(a.par)
        xh = th + np.exp(-kap * afns.DT * h) * (x - th)
        d = float((xh[0] + xh[1]) - (x[0] + x[1])) * 100
        return wf.probs_from_delta(d), d


class MaxEntGen:
    """M8 일반형. 사전분포·제약식 L(percent·일)을 바깥에서 바꿀 수 있다."""

    STEPS = (-0.25, 0.0, 0.25)

    def __init__(self, rows, meetings_all, freq, name, prior="freq", l_fn=None, T=91):
        self.rows, self.meetings_all, self.freq, self.name = rows, meetings_all, freq, name
        self.prior, self.l_fn, self.T = prior, l_fn, T

    def prior_vec(self, ctx):
        pf, _ = self.freq.predict(ctx)
        if self.prior == "freq":
            return np.array([pf["cut"], pf["hold"], pf["hike"]])
        if self.prior == "uniform":
            return np.ones(3) / 3
        if self.prior == "hold90":
            return np.array([0.05, 0.90, 0.05])
        if self.prior == "context":                      # 직전 결정과 같은 분류 뒤에 나온 결정의 빈도(라플라스)
            pa = ctx["past_actuals"]
            if len(pa) < 2:
                return np.array([pf["cut"], pf["hold"], pf["hike"]])
            last = pa[-1]
            nxt = [pa[i + 1] for i in range(len(pa) - 1) if pa[i] == last]
            n = len(nxt)
            c = {k: (sum(1 for a in nxt if a == k) + 1) / (n + 3) for k in CL}
            return np.array([c["cut"], c["hold"], c["hike"]])
        raise ValueError(self.prior)

    def window(self, ctx):
        obs, mt = ctx["obs"].date(), ctx["meeting"].date()
        start = model.settlement_start(obs)
        ms = sorted(m for m in self.meetings_all if start <= m < start + timedelta(days=self.T))
        if mt not in ms:
            return None
        return obs, mt, start, ms, np.array(model.exposure_days(start, self.T, ms), float)

    def L_default(self, ctx, obs):
        v = ctx["yields"].get("msb91")
        if v is None or np.isnan(v):
            return None
        sp = market.pit_spread(self.rows, "msb91", obs)
        sp = 0.0 if sp is None else sp
        return self.T * (float(v) - sp - ctx["r0"])

    def solve(self, ctx):
        w = self.window(ctx)
        if w is None:
            return None
        obs, mt, start, ms, a = w
        L = self.l_fn(self, ctx, obs, start) if self.l_fn else self.L_default(ctx, obs)
        if L is None:
            return None
        prior = self.prior_vec(ctx)
        st = np.array(self.STEPS)

        def dist(lam):
            out = []
            for ak in a:
                ww = prior * np.exp(np.clip(lam * ak * st, -50, 50))
                out.append(ww / ww.sum())
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
        return d, st, (a, ms, mt, L)

    def predict(self, ctx):
        r = self.solve(ctx)
        if r is None:
            return None
        d, st, _ = r
        return {"cut": float(d[0]), "hold": float(d[1]), "hike": float(d[2])}, float((d * st).sum())

    def ident_range(self, ctx, eps_bp=2.0):
        """식별 범위: 다른 회의의 변화를 자유롭게 둘 때 대상 회의 인상 확률의 [최소, 최대]. 허용오차 ε=eps_bp·T."""
        r = self.solve(ctx)
        if r is None:
            return None
        _, st, (a, ms, mt, L) = r
        k = ms.index(mt)
        tol = eps_bp / 100.0 * self.T
        others = float(sum(a[j] * 0.25 for j in range(len(a)) if j != k))
        lo_e = max(-0.25, (L - tol - others) / a[k])
        hi_e = min(0.25, (L + tol + others) / a[k])
        if lo_e > hi_e:
            return None
        return max(0.0, lo_e / 0.25), (1 + hi_e / 0.25) / 2, len(ms)


def l_tp(zmodel):
    """M12: 정상 스프레드에 ACM 기간프리미엄의 훈련 평균 대비 편차를 더해 L을 보정."""
    def fn(self, ctx, obs, start):
        base = self.L_default(ctx, obs)
        if base is None:
            return None
        dev = zmodel.tp_dev(ctx)
        if dev is None:
            return base
        return base - self.T * dev
    return fn


def l_afns(fit: AfnsFit):
    """M13: 통안채 91일 금리 대신 AFNS P측도 기대 평균 단기금리(만기 구간)를 L에 쓴다."""
    def fn(self, ctx, obs, start):
        a, x = fit.state(ctx["obs"])
        if a is None:
            return None
        ws = max(0.0, (start - obs).days / 7.0)
        avg = a.expected_short_avg(x, int(round(ws)), 13) * 100
        return self.T * (avg - (x[0] + x[1]) * 100)
    return fn
