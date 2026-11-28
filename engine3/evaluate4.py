"""4차 평가·검증(프로토콜 v3). 결과 engine3/results/results4.json.

- 지표 정의는 프로토콜 v3 §A. Brier는 3분류 비정규화 합(0~2).
- 표본은 공통 격자(G1: 합성 OIS 계산 가능 칸, G2: 2012~ 비OIS 모형 공통 칸)와 모형별 최대 가용 표본을 구분한다.
- 자격 판정은 프로토콜 v3 §C를 그대로 적용한다.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine3"))
import evaluate as ev  # noqa: E402
import wf  # noqa: E402

RES = ROOT / "engine3" / "results"
BASE = ev.BASE
M3 = "M3 운영 50:50(OIS+통안채)"
HZ = list(wf.HORIZONS)
PERS = ["개발·검증(2012~2022)", "최종(2023~)"]


def load():
    a = pd.read_csv(RES / "cells.csv")
    b = pd.read_csv(RES / "cells4.csv")
    c = pd.read_csv(RES / "cells4_combo.csv")
    d = pd.concat([a, b, c], ignore_index=True)
    dmap = a.drop_duplicates("meeting").set_index("meeting")["delta"].to_dict()
    d["delta"] = d["meeting"].map(dmap)
    return d


def extra_metrics(df):
    df = df.copy()
    pa = df.apply(lambda r: r[f"p_{r['actual']}"], axis=1)
    df["extreme"] = pa < 0.05
    return df


def summ(df, by):
    s = ev.summarize(df, by)
    ex = df.groupby(by)["extreme"].mean().rename("extreme").reset_index()
    return s.merge(ex, on=by)


def stability(df):
    """같은 회의 인접 시계 사이 인상 확률 변화의 평균(모든 시계가 있는 회의만)."""
    out = {}
    for m, g in df.groupby("model"):
        piv = g.pivot_table(index="meeting", columns="D", values="p_hike")
        if not all(d in piv.columns for d in HZ):
            continue
        piv = piv[HZ].dropna()
        if len(piv) < 5:
            continue
        out[m] = {"meetings": int(len(piv)), "mean_abs_step": float(piv.diff(axis=1).abs().iloc[:, 1:].mean().mean())}
    return out


def horizon_boot(df, model, ref, period_mask, D):
    mask = period_mask & (df["D"] == D)
    return ev.boot_diff(df, model, ref, mask)


def main():
    df = ev.prep(extra_metrics(load()))
    df = df.drop_duplicates(["model", "meeting", "D"])
    evd = df[df["period"] != "학습(2008~2011)"].copy()
    models = sorted(evd["model"].unique())
    res = {"models": models}

    # 표본 표
    samp = evd.groupby(["model", "period"]).agg(cells=("brier", "size"), meetings=("meeting", "nunique")).reset_index()
    res["sample"] = samp.to_dict("records")

    # 최대 가용 표본
    res["by_period"] = summ(evd, ["period", "model"]).to_dict("records")
    res["by_horizon"] = summ(evd, ["period", "model", "D"]).to_dict("records")
    res["change_meetings"] = summ(evd[evd["changed"]], ["period", "model"]).to_dict("records")
    res["all_eval_change_meetings"] = summ(evd[evd["changed"]].assign(period="전체(2012~)"), ["period", "model"]).to_dict("records")
    res["all_eval"] = summ(evd.assign(period="전체(2012~)"), ["period", "model"]).to_dict("records")

    # 공통 격자 G1(OIS 가능)·G2(2012~ 비OIS 핵심 모형)
    def common(names):
        cnt = evd[evd["model"].isin(names)].groupby(["meeting", "D"])["model"].nunique()
        keys = set(cnt[cnt == len(names)].index)
        return evd[[(m, d) in keys for m, d in zip(evd["meeting"], evd["D"])]]

    ois_names = ["M1 합성 OIS 단독", M3, BASE, "M2 통안채 91일 단독"]
    g1 = common(ois_names)
    g1 = g1[g1["model"].isin(models)]
    res["G1"] = {"meetings": int(g1["meeting"].nunique()), "cells": int(len(g1) / g1["model"].nunique()),
                 "by_model": summ(g1, ["model"]).to_dict("records"), "change": summ(g1[g1["changed"]], ["model"]).to_dict("records")}
    core = ["M0b 과거 빈도", "M2 통안채 91일 단독", "M7 DNS-VAR", "M8 회의일 기반 풀이(최대 엔트로피)", "M11 동적 앙상블(빈도·통안채·DNS·M8)", "M7z DNS-VAR(제로)", "M5z ACM-VAR(제로)", "M6 AFNS-직접", "M13 AFNS 기대경로+M8"]
    core = [c for c in core if c in models]
    g2 = common(core)
    g2 = g2[g2["model"].isin(models)]
    res["G2"] = {"models": core, "meetings": int(g2["meeting"].nunique()), "cells": int(len(g2) / g2["model"].nunique()),
                 "by_period": summ(g2, ["period", "model"]).to_dict("records")}

    # 시계별 부트스트랩(vs 빈도 기준·vs M3)
    hb = {}
    for m in models:
        if m == BASE:
            continue
        for per in PERS:
            pm = evd["period"] == per
            for D in HZ:
                r = horizon_boot(evd, m, BASE, pm, D)
                if r:
                    hb[f"{per}|{m}|D={D}|vs M0b"] = r
    res["horizon_boot"] = hb
    pb = {}
    for m in models:
        if m == BASE:
            continue
        for per in PERS:
            r = ev.boot_diff(evd, m, BASE, evd["period"] == per)
            if r:
                pb[f"{per}|{m}"] = r
        r = ev.boot_diff(evd, m, BASE, pd.Series(True, index=evd.index))
        if r:
            pb[f"전체|{m}"] = r
    res["period_boot_vs_M0b"] = pb
    pm3 = {}
    for m in models:
        if m == M3:
            continue
        r = ev.boot_diff(g1, m, M3, pd.Series(True, index=g1.index))
        if r:
            pm3[m] = r
    res["g1_boot_vs_M3"] = pm3

    # 전환점 회의
    meet = evd.drop_duplicates("meeting").sort_values("meeting")[["meeting", "actual"]].reset_index(drop=True)
    full = df.drop_duplicates("meeting").sort_values("meeting")[["meeting", "actual"]].reset_index(drop=True)
    full["prev"] = full["actual"].shift(1)
    tp = set(full[(full["actual"] != full["prev"]) & full["prev"].notna()]["meeting"])
    evd["turning"] = evd["meeting"].isin(tp)
    res["turning_points"] = summ(evd[evd["turning"]].assign(period="전환점(2012~)"), ["period", "model"]).to_dict("records")
    res["turning_meetings"] = int(evd[evd["turning"]]["meeting"].nunique())
    res["stability"] = stability(evd)

    # 자격 판정(프로토콜 v3 §C)
    elig = {}
    ref_ex = g1[g1["model"] == M3]["extreme"].mean()
    for m in models:
        if m in (BASE, "M0 항상 동결"):
            continue
        row = {}
        dev = evd[(evd["model"] == m) & (evd["period"] == PERS[0])]
        # 1
        b1 = ev.boot_diff(evd, m, BASE, evd["period"] == PERS[0])
        row["c1_dev_diff_hi"] = None if not b1 else b1["hi"]
        row["c1"] = None if not b1 else bool(b1["hi"] <= 0.05)
        # 2
        ch = evd[(evd["model"] == m) & evd["changed"]]
        chb = evd[(evd["model"] == BASE) & evd["changed"]]
        if len(ch):
            alert = ch["pchg"] >= 0.5
            rec = float(alert.mean())
            j = ch.merge(chb[["meeting", "D", "brier"]].rename(columns={"brier": "b0"}), on=["meeting", "D"], how="left")
            row["c2_recall"], row["c2_brier"], row["c2_base"] = rec, float(j["brier"].mean()), float(j["b0"].mean())
            row["c2"] = bool(rec >= 0.40 and j["brier"].mean() < j["b0"].mean())
        else:
            row["c2"] = None
        # 3
        gm = g1[g1["model"] == m]
        row["c3_extreme"] = float(gm["extreme"].mean()) if len(gm) else None
        row["c3"] = None if not len(gm) else bool(gm["extreme"].mean() <= ref_ex + 1e-12)
        # 4
        ok4, worst = True, -9
        have = True
        for per in PERS:
            for D in HZ:
                b = hb.get(f"{per}|{m}|D={D}|vs M0b")
                if b is None:
                    have = False
                    continue
                worst = max(worst, b["mean"])
                if b["mean"] > 0.10:
                    ok4 = False
        row["c4_worst_h_diff"] = worst if worst > -9 else None
        row["c4"] = ok4 if have else None
        row["c5"] = "해당 없음(인위 조정 없음)" if "교정" not in m else "교정 모수 a만 학습 구간에서 선택"
        flags = [row.get("c1"), row.get("c2"), row.get("c3"), row.get("c4")]
        if any(f is False for f in flags):
            row["eligible"] = False
        elif any(f is None for f in flags):
            row["eligible"] = "판정 불가(개발·검증 구간 칸 없음 등)"
        else:
            row["eligible"] = True
        elig[m] = row
    res["eligibility"] = elig
    res["ois_ref_extreme_M3"] = float(ref_ex)

    # 파레토: 자격 있는 모형만, 비교 대상 모형이 모두 예측한 공통 격자(G3)에서 전체 Brier·변경 회의 Brier로 판정(§B)
    cand = [m for m in elig if elig[m]["eligible"] is True]
    res["eligible"] = cand
    res["undecidable"] = [m for m in elig if isinstance(elig[m]["eligible"], str)]
    if cand:
        g3 = common(cand)
        g3 = g3[g3["model"].isin(cand)]
        a3 = g3.groupby("model")["brier"].mean()
        c3 = g3[g3["changed"]].groupby("model")["brier"].mean()
        pts = {m: (float(a3[m]), float(c3[m])) for m in cand if m in a3 and m in c3}
        res["pareto_grid"] = {"meetings": int(g3["meeting"].nunique()), "cells": int(len(g3) / max(g3["model"].nunique(), 1)), "models": cand}
        res["pareto_points"] = pts
        res["pareto"] = [m for m, (a, b) in pts.items() if not any((a2 <= a and b2 <= b and (a2 < a or b2 < b)) for m2, (a2, b2) in pts.items() if m2 != m)]
    else:
        res["pareto"] = []
        res["pareto_points"] = {}

    # 교정 전후·보정표
    cal = {}
    for lab, base_m in (("M3", M3), ("M2", "M2 통안채 91일 단독"), ("M8", "M8 회의일 기반 풀이(최대 엔트로피)"), ("M11", "M11 동적 앙상블(빈도·통안채·DNS·M8)")):
        cm = f"{lab}c 교정(a)"
        if cm not in models:
            continue
        for per in PERS:
            a0 = evd[(evd["model"] == base_m) & (evd["period"] == per)]
            a1 = evd[(evd["model"] == cm) & (evd["period"] == per)]
            both = a0.merge(a1[["meeting", "D", "brier", "logloss"]], on=["meeting", "D"], suffixes=("", "_c"))
            if lab in ("M3",):
                cal[f"{lab}|{per}"] = {"note": "표본 부족으로 교정 불가(학습 칸 200개 미만, a=1 고정)", "cells": int(len(both))}
                continue
            cal[f"{lab}|{per}"] = {"cells": int(len(both)), "brier_before": float(both["brier"].mean()), "brier_after": float(both["brier_c"].mean()),
                                  "ll_before": float(both["logloss"].mean()), "ll_after": float(both["logloss_c"].mean())}
    res["calibration_effect"] = cal
    res["calibration_table"] = {m: ev.calibration(evd[evd["period"] == PERS[1]], m) for m in
                                [M3, "M8 회의일 기반 풀이(최대 엔트로피)", "M11 동적 앙상블(빈도·통안채·DNS·M8)", "M3c 교정(a)", "M8c 교정(a)", "M11c 교정(a)"] if m in models}

    # 식별 범위
    ir = pd.read_csv(RES / "ident_range.csv")
    if len(ir):
        ir["width"] = ir["hi"] - ir["lo"]
        ir["multi"] = ir["n_meet"] >= 2
        irs = ir.groupby("D").agg(cells=("width", "size"), width_mean=("width", "mean"), multi_share=("multi", "mean"),
                                  width_multi=("width", lambda s: float(s[ir.loc[s.index, "multi"]].mean()) if ir.loc[s.index, "multi"].any() else np.nan)).reset_index()
        res["ident_range"] = irs.to_dict("records")
        res["ident_range_all"] = {"cells": int(len(ir)), "mean_width": float(ir["width"].mean()), "multi_share": float(ir["multi"].mean())}

    # 구성원 가중(M11r, M16, M17)
    info = json.load(open(RES / "combo_info.json", encoding="utf-8"))
    w = {}
    for nm in ("M11r η=10(재현)", "M16 시계 연속 MoE", "M17 국면×시계 MoE"):
        rows = info.get(nm, [])
        if not rows:
            continue
        t = pd.DataFrame(rows)
        t["period"] = np.where(t["meeting"] >= wf.FINAL_START, PERS[1], np.where(t["meeting"] >= wf.EVAL_START, PERS[0], "학습"))
        wc = [c for c in t.columns if c.startswith("w:")]
        gb = t.groupby(["period", "D"])[wc].mean().reset_index()
        w[nm] = gb.to_dict("records")
        if "regime" in t:
            w[nm + "|국면"] = t.groupby(["regime"])[wc].mean().reset_index().to_dict("records")
    res["weights"] = w
    cal_a = info.get("M3c 교정(a)", [])
    res["calib_a"] = {k: pd.DataFrame(info[k])["a"].value_counts().sort_index().to_dict() for k in info if k.endswith("교정(a)") and info[k]}

    # AFNS·제로 보조 지표
    par = {}
    for f in ("afns_params.json", "afns_k_params.json"):
        p = RES / f
        if p.exists():
            par[f] = json.load(open(p, encoding="utf-8"))
    res["afns_params"] = par
    (RES / "results4.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: None if (isinstance(o, float) and np.isnan(o)) else (float(o) if isinstance(o, (np.floating, np.integer)) else str(o))), encoding="utf-8")
    df.to_csv(RES / "cells_all.csv", index=False, encoding="utf-8")
    print("done", len(models), "models;", "pareto", pareto)


if __name__ == "__main__":
    main()
