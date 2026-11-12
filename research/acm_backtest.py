"""ACM(Adrian-Crump-Moench) 기간프리미엄 모형 백테스트(연구용, 공식 확률에는 쓰지 않음).

사전 등록한 설계(결과를 보고 바꾸지 않는다)
  자료: ECOS 일별 통안증권 91일, 국고채 1·3·5·10년, 통안증권 2년 수익률 + 한은 기준금리(research/yields_long.csv, 2006-09~)
  표본: 금요일 주간. 요인 K=3(수익률 주성분). 정책금리(기준금리)를 단기금리로 둔다.
  추정: 기준일 t까지 자료만으로 13주마다 다시 추정(확장 창, 최소 156주). 미래 자료를 쓰지 않는다.
  예측: 회의일 뒤의 기준금리 기대 E_t[r] (ACM의 P 측도 = VAR 예측) → 현재 기준금리와의 차이 Δ → 확률(model.move_distribution)
  평가: 3분류 Brier(인상·동결·인하), 2021-01 이후 금통위, 기준 확률은 awm_panel.json의 합성 OIS·통안채 91일·50:50 결합과 항상 동결
        (1) 다음 회의 horizon 10·20·30영업일 (2) 그다음 회의(회의 40~100일 전)
결과는 docs/research-notes.md에 기록한다.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bokwatch import model  # noqa: E402

COLS = ["msb91", "ktb1y", "msb2y", "ktb3y", "ktb5y", "ktb10y"]
MAT = np.array([0.25, 1.0, 2.0, 3.0, 5.0, 10.0])      # 연
TAU = 1 / 52
K = 3
MIN_WEEKS, REFIT = 156, 13


def load() -> pd.DataFrame:
    d = pd.read_csv(ROOT / "research" / "yields_long.csv", parse_dates=["date"]).set_index("date")
    d["base"] = d["base"].ffill()
    return d.dropna(subset=COLS).assign(base=lambda x: x["base"])


def interp_curve(y: np.ndarray, n: np.ndarray) -> np.ndarray:
    """수익률 곡선 선형 보간(양 끝은 평평하게 잇는다)."""
    return np.interp(n, MAT, y)


class ACM:
    def __init__(self, Y: np.ndarray, r: np.ndarray):
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
        lnP = -MAT * Y / 100                                  # (T,N)
        rx = np.zeros((T - 1, N))
        for t in range(T - 1):
            y_next = interp_curve(Y[t + 1], np.maximum(MAT - TAU, 1e-6))
            lnPn = -(np.maximum(MAT - TAU, 1e-6)) * y_next / 100
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


def fwd_delta(y: np.ndarray, t1: float, t2: float) -> float:
    """기간프리미엄을 빼지 않은 선도금리 기준 Δ: 회의2 뒤 3개월 선도 − 회의1 뒤 3개월 선도(연 단위 t1<t2)."""
    def f(a: float) -> float:
        b = a + 0.25
        ya, yb = np.interp(a, MAT, y), np.interp(b, MAT, y)
        return (yb * b - ya * a) / (b - a)
    return f(t2) - f(t1)


def weekly(d: pd.DataFrame) -> pd.DataFrame:
    return d.resample("W-FRI").last().dropna(subset=COLS)


def move_probs(delta: float) -> dict[str, float]:
    dist = model.move_distribution(float(delta))
    return {"hike": sum(v for k, v in dist.items() if k > 0), "cut": sum(v for k, v in dist.items() if k < 0),
            "hold": max(0.0, 1 - sum(v for k, v in dist.items() if k != 0))}


def brier(p: dict, actual: str) -> float:
    return sum((p[c] - (1.0 if c == actual else 0.0)) ** 2 for c in ("hike", "hold", "cut"))


def main() -> None:
    d = load()
    wk = weekly(d)
    cfg = __import__("yaml").safe_load((ROOT / "data" / "config.yaml").read_text(encoding="utf-8"))
    dec = sorted(cfg["past_decisions"], key=lambda z: z["date"])
    hist = pd.read_csv(ROOT / "data" / "meetings_history.csv")["date"].tolist()
    # 결정(금리) 연쇄로 각 회의의 변화폭
    chg, prev = {}, None
    for x in dec:
        if prev is not None:
            chg[x["date"]] = round((x["rate"] - prev) * 100)
        prev = x["rate"]
    meetings = [m for m in sorted(chg) if m >= "2021-01-01"]
    all_meet = sorted(set(m["date"] for m in dec))
    panel = json.loads((ROOT / "data" / "awm_panel.json").read_text(encoding="utf-8"))["panel"]
    pan = {(p["meeting"], p["horizon"]): p for p in panel}
    models: dict[date, ACM] = {}
    model_dates = [wk.index[i] for i in range(MIN_WEEKS, len(wk), REFIT)]

    def fit_for(t: pd.Timestamp) -> ACM:
        end = max(m for m in model_dates if m <= t) if any(m <= t for m in model_dates) else None
        if end is None:
            return None
        if end not in models:
            sub = wk.loc[:end]
            models[end] = ACM(sub[COLS].values, sub["base"].values)
        return models[end]

    def actual_of(m):
        return {1: "hike", 0: "hold", -1: "cut"}[int(np.sign(chg[m]))] if True else None

    res_first, res_second = [], []
    bdays = d.index
    for m in meetings:
        md = pd.Timestamp(m)
        for h in (10, 20, 30):
            # h영업일 전 기준일
            idx = bdays.searchsorted(md) - h
            if idx < 0:
                continue
            t = bdays[idx]
            acm = fit_for(t)
            if acm is None:
                continue
            row = d.loc[t]
            y = row[COLS].values.astype(float)
            r0 = float(row["base"])
            x = acm.pcs(y)
            weeks = max(1, round((md - t).days / 7)) + 1
            rhat = acm.expected_rate(x, weeks)
            p = move_probs(rhat - r0)
            act = actual_of(m)
            rec = {"meeting": m, "h": h, "actual": act, "acm": brier(p, act), "hold": brier({"hike": 0, "hold": 1, "cut": 0}, act),
                   "dr": rhat - r0}
            c = pan.get((m, h))
            if c:
                ms = c["models"]
                if ms.get("ois", {}).get("ok") and ms.get("msb91", {}).get("ok"):
                    po, pm = ms["ois"]["p"], ms["msb91"]["p"]
                    p5 = {k: 0.5 * po[k] + 0.5 * pm[k] for k in ("hike", "hold", "cut")}
                    rec.update(ois=brier(po, act), msb91=brier(pm, act), m5=brier(p5, act))
            res_first.append(rec)
        # 그다음 회의: 회의 40~100일 전 기준일 가운데 사이에 다른 회의가 하나 이상 있는 날
        for lead in (45, 60, 75, 90):
            t = md - pd.Timedelta(days=lead)
            idx = bdays.searchsorted(t, side="right") - 1
            if idx < 0:
                continue
            t = bdays[idx]
            between = [x for x in all_meet if t < pd.Timestamp(x) < md]
            if not between:
                continue
            acm = fit_for(t)
            if acm is None:
                continue
            row = d.loc[t]
            y = row[COLS].values.astype(float)
            x = acm.pcs(y)
            w_m1 = max(1, round((pd.Timestamp(between[-1]) - t).days / 7)) + 1
            w_m2 = max(1, round((md - t).days / 7)) + 1
            delta = acm.expected_rate(x, w_m2) - acm.expected_rate(x, w_m1)
            p = move_probs(delta)
            act = actual_of(m)
            t1 = max((pd.Timestamp(between[-1]) - t).days, 7) / 365
            t2 = (md - t).days / 365
            pf = move_probs(fwd_delta(y, t1, t2))
            res_second.append({"meeting": m, "lead": lead, "actual": act, "acm": brier(p, act), "fwd": brier(pf, act),
                               "hold": brier({"hike": 0, "hold": 1, "cut": 0}, act), "dr": delta})
    f = pd.DataFrame(res_first)
    s = pd.DataFrame(res_second)
    out = {"sample_first": {"cells": len(f), "meetings": int(f["meeting"].nunique()), "hikes": int((f.drop_duplicates('meeting')["actual"] == "hike").sum())}}
    cmp_cols = [c for c in ("acm", "hold", "ois", "msb91", "m5") if c in f]
    fm = f.dropna(subset=[c for c in ("ois", "msb91", "m5") if c in f])
    out["first_all_cells_brier"] = {c: round(float(f[c].mean()), 4) for c in ("acm", "hold")}
    out["first_matched_with_panel"] = {"cells": len(fm), **{c: round(float(fm[c].mean()), 4) for c in cmp_cols}}
    out["first_by_h"] = {int(h): {c: round(float(g[c].mean()), 4) for c in cmp_cols if c in g and g[c].notna().all()} for h, g in fm.groupby("h")}
    if len(s):
        out["second"] = {"cells": len(s), "meetings": int(s["meeting"].nunique()), "hikes": int((s.drop_duplicates('meeting')["actual"] == "hike").sum()),
                         "acm": round(float(s["acm"].mean()), 4), "fwd(기간프리미엄 미보정)": round(float(s["fwd"].mean()), 4), "hold": round(float(s["hold"].mean()), 4)}
        out["second_by_lead"] = {int(k): {"n": len(g), "acm": round(float(g["acm"].mean()), 4), "fwd": round(float(g["fwd"].mean()), 4), "hold": round(float(g["hold"].mean()), 4)} for k, g in s.groupby("lead")}
        for name, lo, hi in (("2021-2022 인상기", "2021-01-01", "2022-12-31"), ("2023-2026", "2023-01-01", "2026-12-31")):
            g = s[(s["meeting"] >= lo) & (s["meeting"] <= hi)]
            if len(g):
                out.setdefault("second_by_period", {})[name] = {"cells": len(g), "meetings": int(g["meeting"].nunique()), "hikes": int((g.drop_duplicates('meeting')["actual"] == "hike").sum()),
                                                                 "acm": round(float(g["acm"].mean()), 4), "fwd": round(float(g["fwd"].mean()), 4), "hold": round(float(g["hold"].mean()), 4)}
    # 방향성: 인상 회의 vs 동결 회의에서 예측 변화폭 평균
    out["dr_mean_by_actual_first"] = {k: round(float(g["dr"].mean() * 100), 1) for k, g in f.groupby("actual")}
    if len(s):
        out["dr_mean_by_actual_second"] = {k: round(float(g["dr"].mean() * 100), 1) for k, g in s.groupby("actual")}
    # 기간프리미엄(참고): 최신 3년물
    last = fit_for(wk.index[-1])
    if last is not None:
        t = wk.index[-1]
        y = wk.loc[t, COLS].values.astype(float)
        out["latest_term_premium_3y_pct"] = round(last.term_premium_3y(last.pcs(y), float(y[3])), 3)
    f.to_csv(ROOT / "research" / "acm_first_cells.csv", index=False)
    s.to_csv(ROOT / "research" / "acm_second_cells.csv", index=False)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
