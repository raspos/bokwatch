"""5차: 국면 조건부 빈도(M9a)·M8+국면 사전(M9b)·거시+시장 로지스틱(M10). 사양은 03-protocol.md 보충 2."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine3"))
import wf  # noqa: E402
import wf2  # noqa: E402
import run4  # noqa: E402
from wf import CL  # noqa: E402

OUT = ROOT / "engine3" / "results"


def regime_of(p12):
    return "인상기" if p12 > 0.1 else "인하기" if p12 < -0.1 else "동결기"


class _Ctx:
    """base 시계열에서 직전 12개월 변화를 구한다."""

    def __init__(self, base):
        self.base = base

    def prior12(self, obs):
        a = self.base.loc[:obs]
        b = self.base.loc[:obs - pd.Timedelta(days=365)]
        if a.empty or b.empty:
            return 0.0
        return float(a.iloc[-1] - b.iloc[-1])


class RegimeFreq(_Ctx):
    name = "M9a 국면 조건부 빈도"

    def __init__(self, base, min_n=10):
        super().__init__(base)
        self.min_n, self.hist, self.pending = min_n, [], {}

    def probs(self, ctx):
        reg = regime_of(self.prior12(ctx["obs"]))
        same = [a for r, a in self.hist if r == reg]
        pool = same if len(same) >= self.min_n else [a for _, a in self.hist]
        n = len(pool)
        return {k: (sum(1 for a in pool if a == k) + 1) / (n + 3) for k in CL}

    def predict(self, ctx):
        p = self.probs(ctx)
        if ctx["D"] == 30 or ctx["meeting"] not in self.pending:
            self.pending[ctx["meeting"]] = regime_of(self.prior12(ctx["obs"]))      # 회의의 국면은 D=30 관측일 기준(D=30이 먼저 오지 않으면 첫 관측일)
        if ctx["D"] == 30:
            self.pending[ctx["meeting"]] = regime_of(self.prior12(ctx["obs"]))
        return p, 0.25 * (p["hike"] - p["cut"])

    def update(self, meeting, actual):
        self.hist.append((self.pending.pop(meeting, "동결기"), actual))


class _RegimePrior:
    """M8 사전분포 자리에 M9a 확률을 넣기 위한 Frequency 대용품."""
    name = "regime-prior"

    def __init__(self, rf):
        self.rf = rf

    def predict(self, ctx):
        p = self.rf.probs(ctx)
        return p, 0.25 * (p["hike"] - p["cut"])


class Macro(_Ctx):
    name = "M10 거시+시장 로지스틱"

    def __init__(self, base, yd, cpi, min_meetings=40):
        super().__init__(base)
        self.yd, self.cpi, self.min_m = yd, cpi, min_meetings
        self.rows, self.pending, self.freq, self.model = [], {}, wf.Frequency(), None
        self.nfit = 0

    def cpi_gap(self, obs):
        avail = self.cpi[self.cpi["avail"] <= obs]
        if len(avail) < 13:
            return 0.0
        last = avail.iloc[-1]["cpi"]
        yago = avail.iloc[-13]["cpi"]
        return float(last / yago * 100 - 100 - 2.0)

    def feat(self, ctx):
        v = ctx["yields"].get("msb91")
        sp = (float(v) - ctx["r0"]) if v is not None and not np.isnan(v) else 0.0
        return [sp, self.cpi_gap(ctx["obs"]), self.prior12(ctx["obs"])]

    def predict(self, ctx):
        x = self.feat(ctx)
        self.pending.setdefault(ctx["meeting"], []).append(x)
        if self.model is None:
            c, _ = self.freq.predict(ctx)
            return c, 0.25 * (c["hike"] - c["cut"])
        pr = self.model.predict_proba([x])[0]
        p = {k: 1e-3 for k in CL}
        for cls, v in zip(self.model.classes_, pr):
            p[cls] = max(float(v), 1e-3)
        z = sum(p.values())
        p = {k: v / z for k, v in p.items()}
        return p, 0.25 * (p["hike"] - p["cut"])

    def update(self, meeting, actual):
        xs = self.pending.pop(meeting, [])
        self.rows.extend((x, actual) for x in xs)
        self.freq_hist = getattr(self, "freq_hist", [])
        self.freq_hist.append(actual)
        n_meet = len(self.freq_hist)
        if n_meet >= self.min_m and len({a for _, a in self.rows}) >= 2:
            from sklearn.linear_model import LogisticRegression
            X = np.array([x for x, _ in self.rows])
            y = np.array([a for _, a in self.rows])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.model = LogisticRegression(C=1.0, max_iter=500).fit(X, y)
            self.nfit += 1


def main():
    yd, base, meet = wf.load()
    yz = pd.read_csv(ROOT / "research" / "yields_zero.csv", index_col=0, parse_dates=True)
    rows = wf.rows_for_market(yd, base)
    allm = [m.date() for m in meet] + [m.date() for m in pd.to_datetime(["2026-11-26", "2027-01-14"])]
    freq = wf.Frequency()
    cpi = pd.read_csv(ROOT / "research" / "macro_cpi.csv", dtype={"month": str})
    cpi["avail"] = pd.to_datetime(cpi["month"] + "01", format="%Y%m%d") + pd.offsets.MonthBegin(1) + pd.Timedelta(days=9)
    rf = RegimeFreq(base)
    m9b = wf2.MaxEntGen(rows, allm, _RegimePrior(rf), "M9b M8+국면 사전", prior="freq")
    mac = Macro(base, yd, cpi)
    # M9b의 사전은 M9a와 같은 이력을 써야 하므로 M9a를 먼저 두어 update 순서를 맞춘다
    models = [rf, m9b, mac]
    # Frequency 대용 객체에 update가 없으므로 rf만 update 대상
    df, _ = run4.build_cells(models, yd, yz, base, meet, None)
    df.to_csv(OUT / "cells5.csv", index=False, encoding="utf-8")
    print("done", len(df), "fits", mac.nfit, "fails", wf.FAILS, wf.FAIL_EX)


if __name__ == "__main__":
    main()
