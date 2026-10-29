"""AWM 2.0 경쟁모형과 walk-forward 학습 엔진.

모든 모형은 '이전 금통위까지의 칸(cell)'만으로 학습하고(확장 창), 변수 표준화·하이퍼파라미터 선택도 과거 구간 안에서만 한다.
칸 = (금통위, 관측 시점 D). 확률 벡터 순서는 (인상, 동결, 인하). Brier는 세 범주 제곱오차의 합(저장소의 기존 정의와 같다).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

CL = ("hike", "hold", "cut")
BUCKET = {1: "near", 3: "near", 5: "mid", 10: "mid", 20: "far", 30: "far"}   # 표본이 작아 6개 구간을 3개로 병합
BUCKETS = ("near", "mid", "far")
HOLD = np.array([0.0, 1.0, 0.0])


def pv(p: dict | None):
    return None if p is None else np.array([p["hike"], p["hold"], p["cut"]], float)


def onehot(a: str):
    return np.array([a == "hike", a == "hold", a == "cut"], float)


def brier(p, a: str) -> float:
    return float(((p - onehot(a)) ** 2).sum())


def logloss(p, a: str) -> float:
    return float(-math.log(max(float(p[CL.index(a)]), 1e-6)))


def clip_norm(p, eps: float = 1e-6):
    q = np.clip(np.asarray(p, float), eps, 1.0)
    return q / q.sum()


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def logit(p, eps: float = 1e-4):
    p = min(max(float(p), eps), 1 - eps)
    return math.log(p / (1 - p))


@dataclass
class Cell:
    meeting: str
    idx: int                       # 금통위 순번(시간순)
    D: int
    actual: str
    preds: dict                    # {"ois","msb91","cd91"} → np.array 또는 None
    feat: dict
    meta: dict = field(default_factory=dict)

    @property
    def bucket(self) -> str:
        return BUCKET.get(self.D) or ("near" if self.D <= 3 else "mid" if self.D <= 10 else "far")   # 격자 밖 D(오늘 예측)는 가까운 구간으로


def prepare(panel: list[dict]) -> list[Cell]:
    order = {m: i for i, m in enumerate(sorted({r["meeting"] for r in panel}))}
    cells = []
    for r in panel:
        if r.get("missing") or not r.get("models"):
            continue
        ms = r["models"]
        preds = {k: (pv(ms[k]["p"]) if ms[k].get("ok") else None) for k in ("ois", "msb91", "cd91")}
        ois = ms["ois"]
        stale = None
        if ois.get("ok") and ois.get("input_date") and r.get("obs_date"):
            from datetime import date as _d
            stale = (_d.fromisoformat(r["obs_date"]) - _d.fromisoformat(ois["input_date"])).days
        cells.append(Cell(r["meeting"], order[r["meeting"]], r["horizon"], r["actual"], preds, r.get("features") or {},
                          {"ois_source": ois.get("source_type"), "ois_stale": stale, "obs_date": r["obs_date"],
                           "streak": r["streak"], "last_dir": r["last_change_dir"], "since": r["days_since_change"]}))
    return cells


# ---------------------------------------------------------------- 모형
class Model:
    name = ""
    needs = ()                     # 필요한 기본 예측(없으면 그 칸은 예측하지 않는다)

    def fit(self, train: list[Cell]) -> None:
        pass

    def available(self, c: Cell) -> bool:
        return all(c.preds.get(k) is not None for k in self.needs)

    def predict(self, c: Cell):
        raise NotImplementedError

    def params(self) -> dict | None:
        return None

    def weight_of(self, c: Cell):
        """OIS에 둔 가중치(두 전문가 혼합 모형만). 해당 없으면 None."""
        return None


class AlwaysHold(Model):
    name = "M0 항상 동결"

    def predict(self, c):
        return HOLD.copy()


class Frequency(Model):
    name = "M1 과거 결정 빈도"

    def fit(self, train):
        seen, cnt = set(), np.zeros(3)
        for c in train:
            if c.meeting not in seen:
                seen.add(c.meeting)
                cnt += onehot(c.actual)
        self.p = (cnt + 1) / (cnt.sum() + 3)               # 라플라스 보정

    def predict(self, c):
        return self.p.copy()


class Single(Model):
    def __init__(self, key: str, name: str):
        self.key, self.name, self.needs = key, name, (key,)

    def predict(self, c):
        return c.preds[self.key].copy()


class Fixed(Model):
    """두 기본 예측의 고정 비율 혼합."""

    def __init__(self, a: str, b: str, w: float = 0.5, name: str = "M5 OIS+통안채 50:50"):
        self.a, self.b, self.w, self.name, self.needs = a, b, w, name, (a, b)

    def predict(self, c):
        return self.w * c.preds[self.a] + (1 - self.w) * c.preds[self.b]

    def weight_of(self, c):
        return self.w


def mean_brier(cells: list[Cell], pred) -> float:
    return float(np.mean([brier(pred(c), c.actual) for c in cells])) if cells else float("nan")


class BucketWeight(Model):
    """M6: 남은 기간 구간별 고정 가중치. 과거 같은 구간에서 Brier가 낮았던 쪽에 비중을 주고, 표본이 적으면 50:50으로 수축한다."""

    def __init__(self, a="ois", b="msb91", n0: float = 8.0, name="M6 기간별 고정 가중치"):
        self.a, self.b, self.n0, self.name, self.needs = a, b, n0, name, (a, b)

    def fit(self, train):
        self.w = {}
        grid = np.linspace(0, 1, 11)
        for bk in BUCKETS:
            cs = [c for c in train if c.bucket == bk and self.available(c)]
            if not cs:
                self.w[bk] = 0.5
                continue
            best = min(grid, key=lambda w: mean_brier(cs, lambda c: w * c.preds[self.a] + (1 - w) * c.preds[self.b]))
            n = len({c.meeting for c in cs})
            lam = n / (n + self.n0)
            self.w[bk] = float(lam * best + (1 - lam) * 0.5)

    def predict(self, c):
        w = self.w.get(c.bucket, 0.5)
        return w * c.preds[self.a] + (1 - w) * c.preds[self.b]

    def params(self):
        return {"w_ois": {k: round(v, 3) for k, v in self.w.items()}}

    def weight_of(self, c):
        return self.w.get(c.bucket, 0.5)


class EWA(Model):
    """M7: 최근 금통위의 예측오차에 더 큰 비중을 두는 지수가중평균. 학습률·망각률은 과거 구간 안의 순차 검증으로 고른다."""

    def __init__(self, a="ois", b="msb91", name="M7 최근 오차 반영(EWA)"):
        self.a, self.b, self.name, self.needs = a, b, name, (a, b)
        self.grid = [(eta, gam) for eta in (1.0, 3.0, 8.0) for gam in (0.7, 0.9, 1.0)]

    def _weight(self, losses_a, losses_b, eta, gam):
        n = len(losses_a)
        if n == 0:
            return 0.5
        disc = np.array([gam ** (n - 1 - t) for t in range(n)])
        la, lb = float(np.dot(disc, losses_a)), float(np.dot(disc, losses_b))
        x = -eta * (la - lb) / max(disc.sum(), 1e-9)
        return float(sigmoid(x))

    def _meeting_losses(self, train):
        by = {}
        for c in train:
            if self.available(c):
                by.setdefault(c.idx, []).append(c)
        la, lb = [], []
        for i in sorted(by):
            cs = by[i]
            la.append(np.mean([brier(c.preds[self.a], c.actual) for c in cs]))
            lb.append(np.mean([brier(c.preds[self.b], c.actual) for c in cs]))
        return by, la, lb

    def fit(self, train):
        by, la, lb = self._meeting_losses(train)
        idxs = sorted(by)
        best, best_sc = (3.0, 0.9), None
        if len(idxs) >= 5:                                         # 과거 안의 순차 검증으로 (학습률, 망각률) 선택
            for eta, gam in self.grid:
                sc = []
                for t in range(3, len(idxs)):
                    w = self._weight(la[:t], lb[:t], eta, gam)
                    sc.append(np.mean([brier(w * c.preds[self.a] + (1 - w) * c.preds[self.b], c.actual) for c in by[idxs[t]]]))
                m = float(np.mean(sc))
                if best_sc is None or m < best_sc - 1e-9:
                    best, best_sc = (eta, gam), m
        n = len(idxs)
        w = self._weight(la, lb, *best)
        lam = n / (n + 8.0)                                        # 표본이 적으면 50:50으로 수축
        self.w = float(lam * w + (1 - lam) * 0.5)
        self.hyper = best

    def predict(self, c):
        return self.w * c.preds[self.a] + (1 - self.w) * c.preds[self.b]

    def params(self):
        h = getattr(self, "hyper", (None, None))
        return {"w_ois": round(self.w, 3), "eta": h[0], "gamma": h[1]}

    def weight_of(self, c):
        return self.w


REGIME_DAYS = 200   # 직전 금리 변경이 이 일수 안이면 그 방향의 국면(인상·인하). 관측일 기준.


def _since_obs(c: Cell):
    """직전 금리 변경 후 관측일까지 경과일(관측일에 알 수 있는 값)."""
    since, obs = c.meta.get("since"), c.meta.get("obs_date")
    if since is None or not obs:
        return None
    from datetime import date as _d
    return since - (_d.fromisoformat(c.meeting) - _d.fromisoformat(obs)).days


def _feat_vec(c: Cell, names: list[str]) -> np.ndarray:
    out = []
    for n in names:
        v = c.feat.get(n)
        if n == "abs_s91_chg10":
            v = abs(c.feat.get("s91_chg10_bp")) if c.feat.get("s91_chg10_bp") is not None else None
        elif n == "abs_ois_chg5":
            v = abs(c.feat.get("ois_delta_chg5_bp")) if c.feat.get("ois_delta_chg5_bp") is not None else None
        elif n == "lnD":
            v = math.log(c.D)
        elif n in ("hike_reg", "cut_reg"):
            v = 1.0 if (c.meta.get("last_dir") == n[:4] and _since_obs(c) is not None and _since_obs(c) <= REGIME_DAYS) else 0.0
        elif n == "streak":
            v = float(min(c.meta.get("streak") or 0, 4))
        elif n == "ois_1m":
            v = 1.0 if c.meta.get("ois_source") == "ois_1m" else 0.0
        elif n == "ois_stale":
            v = c.meta.get("ois_stale")
        elif n == "disagree":
            a, b = c.preds.get("ois"), c.preds.get("msb91")
            v = None if a is None or b is None else abs((1 - a[1]) - (1 - b[1]))
        out.append(np.nan if v is None else float(v))
    return np.array(out, float)


class SignalWeight(Model):
    """M8/M9: w_ois = σ(구간 절편 + Σ c_j z_j). z는 변화·신뢰도 변수(과거 평균·표준편차로 표준화). 릿지로 0·50:50 쪽으로 수축."""

    def __init__(self, names: list[str], name: str, a="ois", b="msb91", lams=(0.3, 1.0, 3.0)):
        self.names, self.name, self.a, self.b, self.needs, self.lams = names, name, a, b, (a, b), lams

    def _design(self, cs):
        X = np.array([_feat_vec(c, self.names) for c in cs]) if self.names else np.zeros((len(cs), 0))
        return X

    def _std(self, X):
        self.mu = np.nanmean(X, axis=0) if X.shape[1] else np.zeros(0)
        sd = np.nanstd(X, axis=0) if X.shape[1] else np.zeros(0)
        self.sd = np.where(sd < 1e-9, 1.0, sd)
        self.mu = np.where(np.isnan(self.mu), 0.0, self.mu)

    def _z(self, X):
        Z = (X - self.mu) / self.sd if X.shape[1] else X
        return np.nan_to_num(Z, nan=0.0)                           # 결측은 중립(0)

    def _fit_params(self, cs, lam):
        X = self._design(cs)
        self._std(X)
        Z = self._z(X)
        bk = np.array([BUCKETS.index(c.bucket) for c in cs])
        pa = np.array([c.preds[self.a] for c in cs])
        pb = np.array([c.preds[self.b] for c in cs])
        y = np.array([onehot(c.actual) for c in cs])
        k = Z.shape[1]

        def obj(th):
            a, cc = th[:3], th[3:]
            w = sigmoid(a[bk] + (Z @ cc if k else 0.0))
            p = w[:, None] * pa + (1 - w)[:, None] * pb
            return float(((p - y) ** 2).sum(axis=1).mean() + lam * (np.sum(cc ** 2) + 0.2 * np.sum(a ** 2)))

        res = minimize(obj, np.zeros(3 + k), method="L-BFGS-B")
        return res.x

    def fit(self, train):
        cs = [c for c in train if self.available(c)]
        self.theta = None
        if len({c.meeting for c in cs}) < 6:
            self.th, self.lam = np.zeros(3 + len(self.names)), None   # 표본 부족: 50:50
            self._std(self._design(cs) if cs else np.zeros((0, len(self.names))))
            return
        idxs = sorted({c.idx for c in cs})
        best, best_sc = self.lams[-1], None
        if len(idxs) >= 8:                                          # 과거 안의 순차 검증으로 수축 강도 선택
            for lam in self.lams:
                sc = []
                for t in range(5, len(idxs)):
                    tr = [c for c in cs if c.idx < idxs[t]]
                    th = self._fit_params(tr, lam)
                    te = [c for c in cs if c.idx == idxs[t]]
                    Z = self._z(self._design(te))
                    w = sigmoid(th[[BUCKETS.index(c.bucket) for c in te]] + (Z @ th[3:] if Z.shape[1] else 0.0))
                    sc.append(np.mean([brier(wi * c.preds[self.a] + (1 - wi) * c.preds[self.b], c.actual) for wi, c in zip(w, te)]))
                m = float(np.mean(sc))
                if best_sc is None or m < best_sc - 1e-9:
                    best, best_sc = lam, m
        self.lam = best
        self.th = self._fit_params(cs, best)

    def weight(self, c):
        Z = self._z(self._design([c]))
        th = self.th
        return float(sigmoid(th[BUCKETS.index(c.bucket)] + (Z[0] @ th[3:] if Z.shape[1] else 0.0)))

    def predict(self, c):
        w = self.weight(c)
        return w * c.preds[self.a] + (1 - w) * c.preds[self.b]

    def params(self):
        th = getattr(self, "th", None)
        if th is None:
            return None
        return {"lambda": self.lam, "intercept": {b: round(float(th[i]), 3) for i, b in enumerate(BUCKETS)},
                "coef": {n: round(float(v), 3) for n, v in zip(self.names, th[3:])}}

    def weight_of(self, c):
        return self.weight(c)


class TwoStage(Model):
    """M10: P(변경)을 릿지 로지스틱으로, 변경 때 방향을 따로 릿지 로지스틱으로 추정해 곱한다."""

    CH = ["lg_ois", "lg_msb", "abs_s91_chg10", "abs_ois_chg5", "near", "far", "streak"]
    DR = ["ois_delta_bp", "s91_bp", "s91_chg10_bp", "last_dir"]
    name = "M10 변경·방향 2단계"
    needs = ("ois", "msb91")

    def __init__(self, lam_ch: float = 1.0, lam_dr: float = 3.0):
        self.lam_ch, self.lam_dr = lam_ch, lam_dr

    def _xc(self, c):
        a, b = c.preds["ois"], c.preds["msb91"]
        base = _feat_vec(c, ["abs_s91_chg10", "abs_ois_chg5"])
        return np.array([logit(1 - a[1]), logit(1 - b[1]), base[0], base[1], c.bucket == "near", c.bucket == "far",
                         float(c.meta.get("streak") or 0)], float)

    def _xd(self, c):
        ld = {"hike": 1.0, "cut": -1.0, None: 0.0}[c.meta.get("last_dir")]
        f = c.feat
        return np.array([f.get("ois_delta_bp"), f.get("s91_bp"), f.get("s91_chg10_bp"), ld], float)

    @staticmethod
    def _fit_logit(X, y, lam):
        mu = np.nanmean(X, axis=0)
        mu = np.where(np.isnan(mu), 0.0, mu)
        sd = np.nanstd(X, axis=0)
        sd = np.where((sd < 1e-9) | np.isnan(sd), 1.0, sd)
        Z = np.nan_to_num((X - mu) / sd, nan=0.0)

        def obj(th):
            p = sigmoid(th[0] + Z @ th[1:])
            p = np.clip(p, 1e-6, 1 - 1e-6)
            return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean() + lam * np.sum(th[1:] ** 2))

        th = minimize(obj, np.zeros(1 + Z.shape[1]), method="L-BFGS-B").x
        return th, mu, sd

    def fit(self, train):
        cs = [c for c in train if self.available(c)]
        self.ok = len({c.meeting for c in cs}) >= 8
        if not self.ok:
            return
        Xc = np.array([self._xc(c) for c in cs])
        yc = np.array([c.actual != "hold" for c in cs], float)
        self.thc = self._fit_logit(Xc, yc, self.lam_ch)
        ch = [c for c in cs if c.actual != "hold"]
        self.has_dir = len({c.meeting for c in ch}) >= 4 and len({c.actual for c in ch}) == 2
        if self.has_dir:
            Xd = np.array([self._xd(c) for c in ch])
            yd = np.array([c.actual == "hike" for c in ch], float)
            self.thd = self._fit_logit(Xd, yd, self.lam_dr)
        else:
            self.prior_hike = (sum(c.actual == "hike" for c in ch) + 1) / (len(ch) + 2) if ch else 0.5

    def predict(self, c):
        a, b = c.preds["ois"], c.preds["msb91"]
        if not getattr(self, "ok", False):
            return 0.5 * a + 0.5 * b                                  # 표본 부족: 50:50
        th, mu, sd = self.thc
        z = np.nan_to_num((self._xc(c) - mu) / sd, nan=0.0)
        pc = float(sigmoid(th[0] + z @ th[1:]))
        if self.has_dir:
            th, mu, sd = self.thd
            z = np.nan_to_num((self._xd(c) - mu) / sd, nan=0.0)
            ph = float(sigmoid(th[0] + z @ th[1:]))
        else:
            ph = self.prior_hike
        return np.array([pc * ph, 1 - pc, pc * (1 - ph)])


# ---------------------------------------------------------------- walk-forward
def walk_forward(cells: list[Cell], models: list[Model], burn_in: int = 6, params_log: list | None = None) -> list[dict]:
    """금통위 순서대로: 그 회의 이전 칸으로만 학습 → 그 회의 칸 예측. 반환은 칸별 예측 기록.
    burn_in: 평가 대상에서 빼는 앞쪽 금통위 수(모형이 쓸 수 있는 칸이 생긴 뒤부터 센다)."""
    out = []
    for i in sorted({c.idx for c in cells}):
        train = [c for c in cells if c.idx < i]
        test = [c for c in cells if c.idx == i]
        for m in models:
            m.fit(train)
            if params_log is not None and test:
                pr = m.params()
                if pr is not None:
                    params_log.append({"meeting": test[0].meeting, "model": m.name, "n_train_meetings": len({c.idx for c in train}), **pr})
            for c in test:
                if not m.available(c):
                    continue
                p = clip_norm(m.predict(c))
                rec = {"meeting": c.meeting, "idx": c.idx, "D": c.D, "model": m.name, "actual": c.actual,
                       "p": [float(x) for x in p], "obs_date": c.meta.get("obs_date")}
                w = m.weight_of(c)
                if w is not None:
                    rec["w_ois"] = round(float(w), 4)
                out.append(rec)
    return out
