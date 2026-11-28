"""4차: 셀 표(모형별 확률)에서 결합 모형·민감도·교정 모형을 워크포워드로 만든다(프로토콜 v3 §E).

입력 engine3/results/cells.csv(2·3차 모형), cells4.csv(4차 기초 모형). 출력 cells4_combo.csv, combo_info.json.
모든 가중치는 해당 회의 이전에 끝난 회의의 결과만 쓴다(같은 회의의 다른 시계 결과도 쓰지 않는다).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "engine3" / "results"
CL = ("hike", "hold", "cut")
HZ = (60, 30, 14, 7, 1)

N_FREQ, N_MSB, N_DNS, N_M8 = "M0b 과거 빈도", "M2 통안채 91일 단독", "M7 DNS-VAR", "M8 회의일 기반 풀이(최대 엔트로피)"
N_M3, N_M11 = "M3 운영 50:50(OIS+통안채)", "M11 동적 앙상블(빈도·통안채·DNS·M8)"


def load_all():
    a = pd.read_csv(RES / "cells.csv")
    b = pd.read_csv(RES / "cells4.csv")
    return pd.concat([a, b], ignore_index=True)


def tab(df, name):
    g = df[df["model"] == name]
    return {(r.meeting, r.D): (np.array([r.p_hike, r.p_hold, r.p_cut]), r.exp_delta, r.prior12) for r in g.itertuples()}


def brier(p, a):
    y = np.array([1.0 if c == a else 0.0 for c in CL])
    return float(((p - y) ** 2).sum())


class Hist:
    """(키) → [(brier 벡터)] 누적."""
    def __init__(self):
        self.d = {}

    def add(self, key, member, b):
        self.d.setdefault((key, member), []).append(b)

    def mean(self, key, member, min_n):
        h = self.d.get((key, member), [])
        return float(np.mean(h)) if len(h) >= min_n else None


def walk(df, members, build, name, min_n=10):
    """회의 순서로 돌며 build(ctx)가 낸 확률을 기록한다. build(P_cell, hist_state) → (p, ed, info)."""
    P = {m: tab(df, m) for m in members}
    actual = df.drop_duplicates("meeting").set_index("meeting")["actual"].to_dict()
    cells = []
    info = []
    state = {"hist": Hist(), "raw": {}}
    for mt in sorted(actual):
        pend = []
        for D in HZ:
            if not all((mt, D) in P[m] for m in members):
                continue
            preds = {m: P[m][(mt, D)] for m in members}
            res = build(mt, D, preds, state)
            if res is None:
                continue
            p, ed, inf = res
            p = np.clip(p, 1e-6, None)
            p = p / p.sum()
            act = actual[mt]
            cells.append({"meeting": mt, "D": D, "actual": act, "delta": float("nan"), "model": name, "p_hike": p[0], "p_hold": p[1], "p_cut": p[2],
                          "exp_delta": ed, "prior12": preds[members[0]][2]})
            if inf:
                info.append({"meeting": mt, "D": D, **inf})
            pend.append((D, preds))
        for D, preds in pend:                                  # 회의가 끝난 뒤에만 이력에 반영
            for m, (p, _, pr) in preds.items():
                b = brier(p, actual[mt])
                state["hist"].add(("D", D), m, b)
                state["hist"].add(("R", regime(pr), D), m, b)
                state["raw"].setdefault(D, []).append((m, [preds[x][0] for x in members], actual[mt]))
    return cells, info, state


def regime(prior12):
    if prior12 is None or np.isnan(prior12):
        return "동결기"
    return "인상기" if prior12 > 0.1 else "인하기" if prior12 < -0.1 else "동결기"


def exp_w(scores, eta):
    w = {n: np.exp(-eta * v) for n, v in scores.items()}
    z = sum(w.values())
    return {n: x / z for n, x in w.items()}


def mixture(members, preds, w):
    p = sum(w[m] * preds[m][0] for m in members)
    ed = sum(w[m] * preds[m][1] for m in members)
    return p, ed


# ---- 개별 구성 ------------------------------------------------------------------------
def make_m11(members, eta=10.0, min_n=10):
    def build(mt, D, preds, st):
        sc = {m: st["hist"].mean(("D", D), m, min_n) for m in members}
        w = {m: 1.0 / len(members) for m in members} if any(v is None for v in sc.values()) else exp_w(sc, eta)
        p, ed = mixture(members, preds, w)
        return p, ed, {f"w:{m}": w[m] for m in members}
    return build


def make_kernel(members, eta=10.0, bw=0.7, min_eff=10, by_regime=False):
    """M16(시계 연속) / M17(국면×시계 연속). 이웃 시계의 과거 Brier를 ln D 가우시안 커널로 평활."""
    def build(mt, D, preds, st):
        reg = regime(preds[members[0]][2])
        sc, ok = {}, True
        for m in members:
            num = den = 0.0
            for D2 in HZ:
                k = np.exp(-((np.log(D) - np.log(D2)) ** 2) / (2 * bw ** 2))
                key = ("R", reg, D2) if by_regime else ("D", D2)
                h = st["hist"].d.get((key, m), [])
                num += k * sum(h)
                den += k * len(h)
            if den < min_eff:
                ok = False
                break
            sc[m] = num / den
        w = exp_w(sc, eta) if ok else {m: 1.0 / len(members) for m in members}
        p, ed = mixture(members, preds, w)
        inf = {f"w:{m}": w[m] for m in members}
        if by_regime:
            inf["regime"] = reg
        return p, ed, inf
    return build


def make_stack(members, lam=0.1, min_n=10):
    """정규화 스태킹: 시계별로 과거 칸의 Brier 평균 + λ·||w−균등||²를 최소화하는 단체(simplex) 가중."""
    K = len(members)

    def build(mt, D, preds, st):
        raw = st["raw"].get(D, [])
        n_meet = len({1 for _ in raw})
        recs = {}
        for m, plist, a in raw:
            pass
        # raw[D]는 (member, plist, actual) 가 구성원마다 쌓이므로 첫 구성원 기준으로 칸을 복원
        cells = [(plist, a) for m, plist, a in raw if m == members[0]]
        if len(cells) < min_n:
            w = np.ones(K) / K
        else:
            Pm = np.array([[x for x in pl] for pl, a in cells])           # (n,K,3)
            Y = np.array([[1.0 if c == a else 0.0 for c in CL] for pl, a in cells])  # (n,3)

            def f(w):
                q = np.einsum("k,nkc->nc", w, Pm)
                return float(((q - Y) ** 2).sum(1).mean() + lam * ((w - 1.0 / K) ** 2).sum())
            r = minimize(f, np.ones(K) / K, method="SLSQP", bounds=[(0, 1)] * K, constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}])
            w = np.clip(r.x, 0, 1)
            w = w / w.sum()
        wd = {m: w[i] for i, m in enumerate(members)}
        p, ed = mixture(members, preds, wd)
        return p, ed, {f"w:{m}": wd[m] for m in members}
    return build


def make_avg(members, weights):
    def build(mt, D, preds, st):
        w = dict(zip(members, weights))
        p, ed = mixture(members, preds, w)
        return p, ed, None
    return build


def make_calib(member, grid=None, min_meetings=40):
    """로그잇 스케일 한 모수 a: q_c ∝ p_c^a. 과거 칸의 Brier를 최소화하는 a(0.5~1.5, 0.1 격자)를 확장 창으로 정한다."""
    grid = grid or [round(0.5 + 0.1 * i, 1) for i in range(11)]

    def build(mt, D, preds, st):
        raw = [(plist[0], a) for lst in st["raw"].values() for m, plist, a in lst if m == member]
        n_meet = len(st.setdefault("calm", set()))
        # 과거 회의 수 근사: raw 칸 수 / 시계 수
        if len(raw) < min_meetings * 5:
            a_best = 1.0
        else:
            best, a_best = 9e9, 1.0
            for a in grid:
                e = 0.0
                for p, act in raw:
                    q = np.clip(p, 1e-6, None) ** a
                    q = q / q.sum()
                    e += brier(q, act)
                if e < best - 1e-12:
                    best, a_best = e, a
        p = np.clip(preds[member][0], 1e-6, None) ** a_best
        p = p / p.sum()
        return p, preds[member][1], {"a": a_best}
    return build


def main():
    df = load_all()
    out, infos = [], {}
    base4 = [N_FREQ, N_MSB, N_DNS, N_M8]

    def run(name, members, build, min_n=10):
        c, inf, _ = walk(df, members, build, name, min_n)
        out.extend(c)
        infos[name] = inf
        print(name, len(c), flush=True)

    # M11 재현(η=10) + 민감도
    run("M11r η=10(재현)", base4, make_m11(base4, 10))
    for eta in (2, 5, 20, 50):
        run(f"M11s η={eta}", base4, make_m11(base4, eta))
    for drop in base4:
        mem = [m for m in base4 if m != drop]
        run(f"M11 −{drop[:3]}", mem, make_m11(mem, 10))
    run("M11 스태킹(정규화)", base4, make_stack(base4))
    # M14 · M15 · M16 · M17
    run("M14 M8+운영 50:50", [N_M8, N_M3], make_avg([N_M8, N_M3], [0.5, 0.5]))
    run("M15 M8+M11 평균", [N_M8, N_M11], make_avg([N_M8, N_M11], [0.5, 0.5]))
    run("M16 시계 연속 MoE", base4, make_kernel(base4))
    run("M17 국면×시계 MoE", base4, make_kernel(base4, by_regime=True))
    # 교정(단일 모수) — M3·M2·M8·M11
    for nm, lab in ((N_M3, "M3"), (N_MSB, "M2"), (N_M8, "M8"), (N_M11, "M11")):
        run(f"{lab}c 교정(a)", [nm], make_calib(nm))
    pd.DataFrame(out).to_csv(RES / "cells4_combo.csv", index=False, encoding="utf-8")
    (RES / "combo_info.json").write_text(json.dumps(infos, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
