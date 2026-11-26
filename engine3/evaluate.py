"""3.0 백테스트 실행·집계(프로토콜 docs/engine3/03-protocol.md). 결과: engine3/results/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine3"))
import wf  # noqa: E402

OUT = ROOT / "engine3" / "results"
OUT.mkdir(exist_ok=True)
BASE = "M0b 과거 빈도"
FLOOR = 1e-3


def brier(r):
    return sum((r[f"p_{c}"] - (1.0 if r["actual"] == c else 0.0)) ** 2 for c in wf.CL)


def logloss(r):
    return -np.log(max(r[f"p_{r['actual']}"], FLOOR))


def prep(df):
    df = df.copy()
    df["brier"] = df.apply(brier, axis=1)
    df["logloss"] = df.apply(logloss, axis=1)
    df["pchg"] = df["p_hike"] + df["p_cut"]
    df["changed"] = df["actual"] != "hold"
    df["pred"] = df[["p_hike", "p_hold", "p_cut"]].values.argmax(axis=1)
    df["pred"] = df["pred"].map({0: "hike", 1: "hold", 2: "cut"})
    df["mae"] = (df["exp_delta"] - df["delta"]).abs()
    df["regime"] = np.where(df["prior12"] > 0.1, "인상기", np.where(df["prior12"] < -0.1, "인하기", "동결기"))
    df["period"] = np.where(df["meeting"] >= wf.FINAL_START, "최종(2023~)", np.where(df["meeting"] >= wf.EVAL_START, "개발·검증(2012~2022)", "학습(2008~2011)"))
    return df


def bal_acc(g):
    rec = []
    for c in wf.CL:
        s = g[g["actual"] == c]
        if len(s):
            rec.append((s["pred"] == c).mean())
    return float(np.mean(rec)) if rec else np.nan


def summarize(df, by):
    rows = []
    base = df[df["model"] == BASE].set_index(["meeting", "D"])["brier"]
    for keys, g in df.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        b0 = g.merge(base.rename("b0").reset_index(), on=["meeting", "D"], how="left")["b0"].mean()
        alert = g["pchg"] >= 0.5
        tp = int((alert & g["changed"]).sum())
        fp = int((alert & ~g["changed"]).sum())
        fn = int((~alert & g["changed"]).sum())
        rows.append({**dict(zip(by, keys)), "meetings": g["meeting"].nunique(), "cells": len(g), "change_meetings": g[g["changed"]]["meeting"].nunique(),
                     "brier": g["brier"].mean(), "bss": 1 - g["brier"].mean() / b0 if b0 else np.nan, "logloss": g["logloss"].mean(),
                     "bal_acc": bal_acc(g), "precision": tp / (tp + fp) if tp + fp else np.nan, "recall": tp / (tp + fn) if tp + fn else np.nan,
                     "sharp": float((g["p_hike"] + g["p_cut"]).std()), "mae_bp": g["mae"].mean() * 100})
    return pd.DataFrame(rows)


def boot_diff(df, a, b, mask, B=10000, seed=7):
    """모형 a − 모형 b의 회의 단위 평균 Brier 차이와 95% 구간(시계 평균 뒤 회의 재표본)."""
    x = df[mask].groupby(["model", "meeting"])["brier"].mean().unstack(0)
    if a not in x or b not in x:
        return None
    d = (x[a] - x[b]).dropna().values
    if len(d) < 5:
        return None
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(d, len(d)).mean() for _ in range(B)])
    return {"n": len(d), "mean": float(d.mean()), "lo": float(np.percentile(means, 2.5)), "hi": float(np.percentile(means, 97.5))}


def calibration(df, model_name):
    g = df[df["model"] == model_name]
    bins = [(0, 0.05), (0.05, 0.2), (0.2, 0.5), (0.5, 0.8), (0.8, 1.0001)]
    out = []
    for lo, hi in bins:
        s = g[(g["p_hike"] >= lo) & (g["p_hike"] < hi)]
        out.append({"bin": f"{lo:.2f}~{min(hi, 1):.2f}", "n": len(s), "mean_p": float(s["p_hike"].mean()) if len(s) else None,
                    "observed": float((s["actual"] == "hike").mean()) if len(s) else None})
    return out


def main():
    yd, base, meet = wf.load()
    rows = wf.rows_for_market(yd, base)
    models = [wf.Hold(), wf.Frequency(), wf.Msb91(rows, [m.date() for m in meet] + [m.date() for m in pd.to_datetime(["2026-11-26", "2027-01-14"])]),
              wf.DnsVar(yd), wf.AcmVar(yd, base)]
    df = wf.build_cells(models, yd, base, meet, progress=True)
    df = prep(df)
    df.to_csv(OUT / "cells.csv", index=False, encoding="utf-8")
    ev = df[df["period"] != "학습(2008~2011)"]
    res = {"generated": pd.Timestamp.today().date().isoformat(), "n_meetings": int(df["meeting"].nunique()),
           "by_period": summarize(ev, ["period", "model"]).to_dict("records"),
           "by_period_horizon": summarize(ev, ["period", "model", "D"]).to_dict("records"),
           "by_regime": summarize(ev, ["period", "regime", "model"]).to_dict("records"),
           "change_meetings": summarize(ev[ev["changed"]], ["period", "model"]).to_dict("records"),
           "calibration": {m: calibration(ev[ev["period"] == "최종(2023~)"], m) for m in df["model"].unique()}}
    cmp = {}
    for per in ("개발·검증(2012~2022)", "최종(2023~)"):
        mask = ev["period"] == per
        for m in df["model"].unique():
            if m in (BASE,):
                continue
            cmp[f"{per}|{m} − {BASE}"] = boot_diff(ev, m, BASE, mask)
            cmp[f"{per}|{m} − M0 항상 동결"] = boot_diff(ev, m, "M0 항상 동결", mask)
            cmp[f"{per}|{m} − M2 통안채 91일 단독"] = boot_diff(ev, m, "M2 통안채 91일 단독", mask)
    res["paired_bootstrap"] = cmp
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: None if (isinstance(o, float) and np.isnan(o)) else o), encoding="utf-8")
    print("done", len(df), "fails", wf.FAILS, wf.FAIL_EX)


if __name__ == "__main__":
    main()
