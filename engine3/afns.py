"""독립요인형 AFNS(Christensen·Diebold·Rudebusch 2011) — 칼만필터 최대우도(프로토콜 v3 §D).

요인 X=(수준 L, 기울기 S, 곡률 C). Q측도: dX = K^Q(0−X)dt + Σ dW^Q, K^Q=[[0,0,0],[0,λ,−λ],[0,0,λ]], Σ 대각.
수익률(만기 τ) y = L + S·l2(τ) + C·l3(τ) − A(τ)/τ, A(τ)=½Σσ_i²∫0^τ B_i(s)² ds, B_i(s)=s·loading_i(s)  (수치 적분).
P측도: 요인별 독립 AR(1)(평균회귀 κ_i, 평균 θ_i, 같은 σ_i). 측정오차 표준편차 한 개(모든 만기 공통).
단기금리 r = L + S (τ→0 극한). 주간 자료(Δ=1/52).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

DT = 1.0 / 52
_GL_X, _GL_W = np.polynomial.legendre.leggauss(60)


def loadings(tau, lam):
    tau = np.asarray(tau, float)
    e = np.exp(-lam * tau)
    l2 = (1 - e) / (lam * tau)
    return np.column_stack([np.ones_like(tau), l2, l2 - e])


def adjustment(tau, lam, sig):
    """−A(τ)/τ (퍼센트 단위가 아닌 소수 단위). A는 Gauss-Legendre 수치 적분."""
    out = np.zeros(len(tau))
    for j, t in enumerate(tau):
        s = 0.5 * t * (_GL_X + 1)
        w = 0.5 * t * _GL_W
        ld = loadings(s, lam)
        B = s[:, None] * ld                       # (n,3)
        out[j] = 0.5 * float(((B ** 2 * np.asarray(sig) ** 2).sum(1)) @ w)
    return -out / np.asarray(tau, float)


class Afns:
    def __init__(self, mat):
        self.mat = np.asarray(mat, float)
        self.par = None

    # ---- 파라미터 ↔ 벡터
    @staticmethod
    def unpack(p):
        lam = np.exp(p[0])
        kap = np.exp(p[1:4])
        th = p[4:7]
        sig = np.exp(p[7:10])
        sd = np.exp(p[10])
        return lam, kap, th, sig, sd

    def _model(self, p):
        lam, kap, th, sig, sd = self.unpack(p)
        B = loadings(self.mat, lam)
        a = adjustment(self.mat, lam, sig)
        return lam, kap, th, sig, sd, B, a

    def loglik(self, p, Y):
        """Y: (T,N) 수익률(소수 단위, 예 0.035)."""
        lam, kap, th, sig, sd, B, a = self._model(p)
        phi = np.exp(-kap * DT)
        Qv = sig ** 2 * (1 - phi ** 2) / (2 * kap)
        P = sig ** 2 / (2 * kap)                    # 정상 분포 분산
        x = th.copy()
        P = np.diag(P)
        Phi, Q, R = np.diag(phi), np.diag(Qv), np.eye(len(self.mat)) * sd ** 2
        ll = 0.0
        for t in range(len(Y)):
            x = th + phi * (x - th) if t else x
            P = Phi @ P @ Phi.T + Q if t else P
            v = Y[t] - (B @ x + a)
            F = B @ P @ B.T + R
            try:
                Fi = np.linalg.inv(F)
            except np.linalg.LinAlgError:
                return -1e12
            sgn, logdet = np.linalg.slogdet(F)
            if sgn <= 0:
                return -1e12
            ll += -0.5 * (logdet + v @ Fi @ v + len(v) * np.log(2 * np.pi))
            K = P @ B.T @ Fi
            x = x + K @ v
            P = P - K @ B @ P
        return ll

    def filter_state(self, p, Y):
        lam, kap, th, sig, sd, B, a = self._model(p)
        phi = np.exp(-kap * DT)
        Qv = sig ** 2 * (1 - phi ** 2) / (2 * kap)
        x, P = th.copy(), np.diag(sig ** 2 / (2 * kap))
        Phi, Q, R = np.diag(phi), np.diag(Qv), np.eye(len(self.mat)) * sd ** 2
        for t in range(len(Y)):
            if t:
                x = th + phi * (x - th)
                P = Phi @ P @ Phi.T + Q
            v = Y[t] - (B @ x + a)
            F = B @ P @ B.T + R
            K = P @ B.T @ np.linalg.inv(F)
            x = x + K @ v
            P = P - K @ B @ P
        return x

    def fit(self, Y, p0=None, maxiter=300):
        if p0 is None:
            p0 = np.array([np.log(0.6), np.log(0.5), np.log(0.5), np.log(0.5), 0.045, -0.02, 0.0, np.log(0.008), np.log(0.01), np.log(0.02), np.log(0.0008)])
            p0[4] = float(Y[:, -1].mean())
        res = minimize(lambda p: -self.loglik(p, Y), p0, method="L-BFGS-B",
                       bounds=[(np.log(0.1), np.log(3.0)), (np.log(0.01), np.log(5)), (np.log(0.01), np.log(5)), (np.log(0.01), np.log(5)),
                               (-0.05, 0.2), (-0.15, 0.15), (-0.15, 0.15), (np.log(1e-4), np.log(0.1)), (np.log(1e-4), np.log(0.1)), (np.log(1e-4), np.log(0.1)),
                               (np.log(1e-5), np.log(0.01))], options={"maxiter": maxiter, "maxfun": 4000})
        self.par = res.x
        self.nll = float(res.fun)
        self.conv = {"success": bool(res.success), "nit": int(res.nit), "nll": float(res.fun), "msg": str(res.message)}
        return res

    def expected_short_avg(self, x, weeks_start, weeks_len):
        """P측도 단기금리 r=L+S의 기대 평균(소수): 지금부터 weeks_start주 뒤 시작, weeks_len주 동안."""
        lam, kap, th, sig, sd = self.unpack(self.par)
        ws = np.arange(weeks_start, weeks_start + weeks_len + 1)
        out = []
        for w in ws:
            xh = th + np.exp(-kap * DT * w) * (x - th)
            out.append(xh[0] + xh[1])
        return float(np.mean(out))

    def short_now(self, x):
        return float(x[0] + x[1])
