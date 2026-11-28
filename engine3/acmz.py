"""ACM(Adrian-Crump-Moench) 3요인 — 만기 격자를 인수로 받는 판(제로 수익률 패널용). research/acm_backtest.py의 클래스를 일반화."""
import numpy as np

TAU = 1 / 52
K = 3
MAT = np.array([0.25, 1.0, 3.0, 5.0, 10.0])


class ACM:
    def __init__(self, Y: np.ndarray, r: np.ndarray, mat=None):
        self.mat = np.asarray(mat if mat is not None else MAT, float)
        """Y: (T,N) 주간 수익률(%), r: (T,) 기준금리(%)."""
        T, N = Y.shape
        self.mean = Y.mean(0)
        U, S, Vt = np.linalg.svd(Y - self.mean, full_matrices=False)
        self.W = Vt[:K]                                       # (K,N) 적재량
        self.sd = (U[:, :K] * S[:K]).std(0)
        X = (Y - self.mean) @ self.W.T / self.sd             # (T,K) 표준화 PC
        self.sd_scale = self.sd
        # VAR(1)
        Z = np.column_stack([np.ones(T - 1), X[:-1]])
        coef, *_ = np.linalg.lstsq(Z, X[1:], rcond=None)
        mu, Phi = coef[0], coef[1:].T
        V = X[1:] - Z @ coef
        Sigma = V.T @ V / (T - 1)
        # 보유수익률 초과수익(로그, 1주 보유)
        lnP = -self.mat * Y / 100                                  # (T,N)
        rx = np.zeros((T - 1, N))
        for t in range(T - 1):
            y_next = np.interp(np.maximum(self.mat - TAU, 1e-6), self.mat, Y[t + 1])
            lnPn = -(np.maximum(self.mat - TAU, 1e-6)) * y_next / 100
            rx[t] = lnPn - lnP[t] - r[t] / 100 * TAU
        Z2 = np.column_stack([np.ones(T - 1), V, X[:-1]])
        c2, *_ = np.linalg.lstsq(Z2, rx, rcond=None)
        a, beta, c = c2[0], c2[1:1 + K], c2[1 + K:].T         # a:(N), beta:(K,N), c:(N,K)
        e = rx - Z2 @ c2
        sig2 = float((e ** 2).mean())
        Bstar = np.array([np.outer(beta[:, i], beta[:, i]).ravel() for i in range(N)])   # (N,K*K)
        bb = beta @ beta.T
        lam0 = np.linalg.solve(bb, beta @ (a + 0.5 * (Bstar @ Sigma.ravel() + sig2)))
        lam1 = np.linalg.solve(bb, beta @ c)
        self.mu, self.Phi, self.Sigma, self.lam0, self.lam1 = mu, Phi, Sigma, lam0, lam1
        # 단기금리 r = d0 + d1'X
        Zr = np.column_stack([np.ones(T), X])
        d, *_ = np.linalg.lstsq(Zr, r, rcond=None)
        self.d0, self.d1 = d[0], d[1:]

    def pcs(self, y: np.ndarray) -> np.ndarray:
        return (y - self.mean) @ self.W.T / self.sd

    def expected_rate(self, x: np.ndarray, weeks: int) -> float:
        """P 측도 기대 정책금리(%) — weeks주 뒤."""
        xh = x.copy()
        for _ in range(weeks):
            xh = self.mu + self.Phi @ xh
        return float(self.d0 + self.d1 @ xh)

    def term_premium_3y(self, x: np.ndarray, y3: float) -> float:
        """3년물의 위험중립(Q) 수익률과 P 기대 평균금리의 차(참고용)."""
        n = int(3 / TAU)
        xs, tot = x.copy(), 0.0
        for _ in range(n):
            tot += self.d0 + self.d1 @ xs
            xs = self.mu + self.Phi @ xs
        return y3 - tot / n

    def tp_short(self, x, y_short, weeks=13):
        """짧은 만기(3개월) 수익률과 P 기대 평균 단기금리의 차(기간프리미엄)."""
        xs, tot = x.copy(), 0.0
        for _ in range(weeks):
            tot += self.d0 + self.d1 @ xs
            xs = self.mu + self.Phi @ xs
        return y_short - tot / weeks
