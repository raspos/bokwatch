"""AWM 2.0 백테스트: 평가 지표, 금통위 단위 군집 부트스트랩, 표본 구분, 결과 JSON.

관측 칸은 금통위당 6개(30·20·10·5·3·1일 전)라 독립 사례가 아니다. 신뢰구간·유의성은 금통위를 한 묶음으로 재표본해 계산한다.
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict

import numpy as np

from . import awm, awm_data
from .awm import CL, brier, logloss

HORIZONS = awm_data.HORIZONS


def models_all() -> list[awm.Model]:
    return [
        awm.AlwaysHold(),
        awm.Frequency(),
        awm.Single("ois", "M2 합성 OIS 단독"),
        awm.Single("msb91", "M3 통안채 91일 단독"),
        awm.Single("cd91", "M4 CD91 단독"),
        awm.Fixed("ois", "msb91", 0.5, "M5 OIS+통안채 50:50"),
        awm.BucketWeight(name="M6 기간별 고정 가중치"),
        awm.SignalWeight(["lnD"], "M6c 기간 연속형 가중치"),
        awm.EWA(name="M7 최근 오차 반영(EWA)"),
        awm.SignalWeight(["abs_s91_chg10", "abs_ois_chg5"], "M8 기간+전환 신호 가중치"),
        awm.SignalWeight(["hike_reg", "cut_reg", "streak"], "M8b 기간+직전 결정 맥락 가중치(탐색적)"),
        awm.SignalWeight(["abs_s91_chg10", "abs_ois_chg5", "ois_1m", "ois_stale", "disagree"], "M9 기간+전환 신호+신뢰도 가중치"),
        awm.SignalWeight(["abs_s91_chg10", "abs_ois_chg5", "hike_reg", "cut_reg", "streak", "ois_1m", "ois_stale", "disagree"],
                         "M9b 신호+결정 맥락+신뢰도(탐색적)"),
        awm.TwoStage(),
    ]


# ---------------------------------------------------------------- 지표
def cell_metrics(rec: dict) -> dict:
    p = np.array(rec["p"])
    a = rec["actual"]
    top = np.flatnonzero(np.isclose(p, p.max()))
    hit = len(top) == 1 and CL[top[0]] == a
    return {"brier": brier(p, a), "logloss": logloss(p, a), "hit": hit, "pchg": float(1 - p[1]),
            "dir_ok": (p[0] > p[2]) == (a == "hike") if a != "hold" else None}


def summarize(recs: list[dict]) -> dict:
    if not recs:
        return {"n_cells": 0}
    ms = [cell_metrics(r) for r in recs]
    meetings = sorted({r["meeting"] for r in recs})
    chg = [(r, m) for r, m in zip(recs, ms) if r["actual"] != "hold"]
    out = {"n_cells": len(recs), "n_meetings": len(meetings), "n_change_meetings": len({r["meeting"] for r, _ in chg}),
           "hit_rate": round(float(np.mean([m["hit"] for m in ms])), 4),
           "brier": round(float(np.mean([m["brier"] for m in ms])), 4),
           "logloss": round(float(np.mean([m["logloss"] for m in ms])), 4),
           "hit_rate_change": round(float(np.mean([m["hit"] for _, m in chg])), 4) if chg else None,
           "hit_rate_hold": round(float(np.mean([m["hit"] for r, m in zip(recs, ms) if r["actual"] == "hold"])), 4)}
    for thr in (0.3, 0.5):                                         # 금리 변경 경보: P(변경) ≥ 임계값
        tp = sum(m["pchg"] >= thr for r, m in zip(recs, ms) if r["actual"] != "hold")
        fp = sum(m["pchg"] >= thr for r, m in zip(recs, ms) if r["actual"] == "hold")
        fn = sum(m["pchg"] < thr for r, m in zip(recs, ms) if r["actual"] != "hold")
        tn = sum(m["pchg"] < thr for r, m in zip(recs, ms) if r["actual"] == "hold")
        prec = tp / (tp + fp) if tp + fp else None
        rec_ = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec_ / (prec + rec_) if prec and rec_ else (0.0 if prec is not None and rec_ is not None else None)
        out[f"alert_{thr}"] = {"precision": None if prec is None else round(prec, 4), "recall": None if rec_ is None else round(rec_, 4),
                               "f1": None if f1 is None else round(f1, 4), "false_alarm_rate": round(fp / (fp + tn), 4) if fp + tn else None,
                               "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    dirs = [m["dir_ok"] for r, m in zip(recs, ms) if r["actual"] != "hold" and m["pchg"] >= 0.3]
    out["direction_acc_given_alert"] = round(float(np.mean(dirs)), 4) if dirs else None
    out["direction_n"] = len(dirs)
    # 보정(P(변경) 구간별 실제 변경 비율)
    bins = [(0, 0.1), (0.1, 0.3), (0.3, 0.6), (0.6, 1.01)]
    cal = []
    for lo, hi in bins:
        sel = [(m["pchg"], r["actual"] != "hold") for r, m in zip(recs, ms) if lo <= m["pchg"] < hi]
        cal.append({"bin": f"{lo:.1f}~{min(hi, 1.0):.1f}", "n": len(sel),
                    "mean_p": round(float(np.mean([s[0] for s in sel])), 3) if sel else None,
                    "observed": round(float(np.mean([s[1] for s in sel])), 3) if sel else None})
    out["calibration"] = cal
    by_h = defaultdict(list)
    for r, m in zip(recs, ms):
        by_h[r["D"]].append(m["brier"])
    out["brier_by_horizon"] = {str(h): round(float(np.mean(v)), 4) for h, v in sorted(by_h.items(), reverse=True)}
    return out


def regime(meta_last_dir, since) -> str:
    if meta_last_dir in ("hike", "cut") and since is not None and since <= 200:
        return "인상 국면" if meta_last_dir == "hike" else "인하 국면"
    return "동결 국면"


# ---------------------------------------------------------------- 군집 부트스트랩
def per_meeting(recs: list[dict], key: str = "brier") -> dict[str, float]:
    by = defaultdict(list)
    for r in recs:
        by[r["meeting"]].append(cell_metrics(r)[key])
    return {m: float(np.mean(v)) for m, v in by.items()}


def cluster_diff(a: list[dict], b: list[dict], key: str = "brier", B: int = 10000, seed: int = 20261029) -> dict:
    """모형 a − 모형 b의 금통위별 평균 차이를 금통위 단위로 재표본. 음수면 a가 낫다(Brier·로그손실)."""
    ka = {(r["meeting"], r["D"]): r for r in a}
    kb = {(r["meeting"], r["D"]): r for r in b}
    common = sorted(set(ka) & set(kb))
    by = defaultdict(list)
    for k in common:
        by[k[0]].append(cell_metrics(ka[k])[key] - cell_metrics(kb[k])[key])
    ms = sorted(by)
    if len(ms) < 3:
        return {"n_meetings": len(ms)}
    d = np.array([np.mean(by[m]) for m in ms])
    rng = random.Random(seed)
    boots = np.array([np.mean([d[rng.randrange(len(d))] for _ in range(len(d))]) for _ in range(B)])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    p = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return {"n_meetings": len(ms), "mean_diff": round(float(d.mean()), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "p_two_sided": round(float(min(p, 1.0)), 4), "wins": int((d < 0).sum()), "losses": int((d > 0).sum())}


# ---------------------------------------------------------------- 실행
def run(panel: list[dict] | None = None, burn_in: int = 6, B: int = 10000) -> dict:
    panel = panel if panel is not None else awm_data.build_panel()
    cells = awm.prepare(panel)
    models = models_all()
    params_log: list = []
    recs = awm.walk_forward(cells, models, params_log=params_log)
    meta = {(c.meeting, c.D): c.meta for c in cells}
    for r in recs:
        m = meta[(r["meeting"], r["D"])]
        r["regime"] = regime(m["last_dir"], m["since"])
    # 시장 급변 칸: 통안채 91일−기준금리의 10영업일 변화 절댓값이 '이전 금통위 칸들의 상위 25%' 문턱 이상(과거만 사용)
    vol, past_vals, last_idx = {}, [], None
    for c in sorted(cells, key=lambda x: (x.idx, x.D)):
        if last_idx != c.idx:
            if last_idx is not None:
                past_vals.extend(cur_vals)
            cur_vals, last_idx = [], c.idx
        v = c.feat.get("s91_chg10_bp")
        a = abs(v) if v is not None else None
        thr = float(np.percentile(past_vals, 75)) if len(past_vals) >= 30 else None
        vol[(c.meeting, c.D)] = None if a is None or thr is None else a >= thr
        if a is not None:
            cur_vals.append(a)
    for r in recs:
        r["volatile"] = vol.get((r["meeting"], r["D"]))
    meet_order = sorted({c.meeting for c in cells})
    ois_meet = sorted({c.meeting for c in cells if c.preds["ois"] is not None})
    eval_ois = set(ois_meet[burn_in:])                              # OIS 표본: 합성 OIS가 처음 풀린 뒤 6회는 학습에만 쓴다
    eval_all = set(meet_order[burn_in:])                            # 전체 표본: 첫 6회는 학습에만 쓴다
    by_model = defaultdict(list)
    for r in recs:
        by_model[r["model"]].append(r)
    names = [m.name for m in models]
    need_ois = {m.name for m in models if "ois" in m.needs}

    def common(group: set[str], meetings: set[str]) -> list[str]:
        """그룹의 모든 모형이 예측한 (금통위, D) 칸 집합(같은 표본에서만 비교)."""
        sets = [{(r["meeting"], r["D"]) for r in by_model[n] if r["meeting"] in meetings} for n in group]
        return sorted(set.intersection(*sets)) if sets else []

    out = {"meta": {"horizons": list(HORIZONS), "burn_in": burn_in, "bootstrap": {"B": B, "unit": "금통위(군집)"},
                    "brier": "세 범주 제곱오차 합(0~2)", "alert_thresholds": [0.3, 0.5]}}
    # (A) OIS를 쓰는 모형·기준모형 — 같은 표본
    gA = {n for n in names if n in need_ois} | {"M0 항상 동결", "M1 과거 결정 빈도", "M3 통안채 91일 단독", "M4 CD91 단독"}
    keyA = set(common(gA, eval_ois))
    # (B) OIS 없는 모형 — 더 긴 표본
    gB = {"M0 항상 동결", "M1 과거 결정 빈도", "M3 통안채 91일 단독", "M4 CD91 단독"}
    keyB = set(common(gB, eval_all))

    def pick(n, keys):
        return [r for r in by_model[n] if (r["meeting"], r["D"]) in keys]

    def sample_info(keys):
        ms = sorted({k[0] for k in keys})
        acts = {}
        for r in by_model["M0 항상 동결"]:
            acts[r["meeting"]] = r["actual"]
        return {"n_cells": len(keys), "n_meetings": len(ms), "first": ms[0] if ms else None, "last": ms[-1] if ms else None,
                "actuals": {a: sum(acts[m] == a for m in ms) for a in CL}}

    out["sample_ois"] = sample_info(keyA)
    out["sample_long"] = sample_info(keyB)
    out["table_ois"] = {n: summarize(pick(n, keyA)) for n in names if n in gA}
    out["table_long"] = {n: summarize(pick(n, keyB)) for n in sorted(gB)}
    # 국면별(OIS 표본)
    reg = defaultdict(lambda: defaultdict(list))
    for n in names:
        if n in gA:
            for r in pick(n, keyA):
                reg[n][r["regime"]].append(r)
    out["by_regime_ois"] = {n: {k: summarize(v) for k, v in sorted(d.items())} for n, d in reg.items()}
    # 시장 급변 칸 vs 평온 칸(과거 문턱 기준)
    out["by_volatility_ois"] = {}
    for n in names:
        if n in gA:
            for flag, label in ((True, "급변"), (False, "평온")):
                rs = [r for r in pick(n, keyA) if r.get("volatile") is flag]
                out["by_volatility_ois"].setdefault(n, {})[label] = summarize(rs)
    # 가중치 분포(OIS 가중치): 모형별 시점 D별 평균·최소·최대, 금통위 단위 변화
    wd = defaultdict(lambda: defaultdict(list))
    for r in recs:
        if "w_ois" in r and (r["meeting"], r["D"]) in keyA:
            wd[r["model"]][r["D"]].append(r["w_ois"])
    out["weight_by_horizon"] = {n: {str(D): {"mean": round(float(np.mean(v)), 3), "min": round(min(v), 3), "max": round(max(v), 3), "n": len(v)}
                                    for D, v in sorted(d.items(), reverse=True)} for n, d in wd.items()}
    # 쌍 비교(금통위 군집 부트스트랩)
    bench = ["M5 OIS+통안채 50:50", "M7 최근 오차 반영(EWA)", "M2 합성 OIS 단독", "M0 항상 동결"]
    out["paired_ois"] = {}
    for n in names:
        if n not in gA or n in bench and n == "M0 항상 동결":
            continue
        out["paired_ois"][n] = {}
        for bname in bench:
            if bname != n:
                out["paired_ois"][n][bname] = {"brier": cluster_diff(pick(n, keyA), pick(bname, keyA), "brier", B),
                                               "logloss": cluster_diff(pick(n, keyA), pick(bname, keyA), "logloss", B)}
    # 회의별 사전 확률(채택 후보용)
    out["rows"] = [r for r in recs if (r["meeting"], r["D"]) in keyA]
    out["params"] = params_log
    return out


def main(path: str | None = None) -> int:
    res = run()
    if path:
        json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    for k in ("sample_ois", "sample_long"):
        print(k, res[k])
    print("\n[OIS 표본] 모형별 Brier / 적중 / 변경회의 적중 / Recall@0.3 / 오탐률@0.3")
    for n, s in res["table_ois"].items():
        a3 = s["alert_0.3"]
        print(f"{n:34s} B={s['brier']:.4f} LL={s['logloss']:.3f} hit={s['hit_rate']:.3f} chg_hit={s['hit_rate_change']} "
              f"R={a3['recall']} FA={a3['false_alarm_rate']} P={a3['precision']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
