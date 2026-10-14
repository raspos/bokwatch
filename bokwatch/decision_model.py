"""금통위 결정 예측(통계모형, 실험): 회의 1건 = 표본 1개, 순서형 로지스틱(인하 < 동결 < 인상).

  python -m bokwatch.decision_model --fetch   # ECOS 장기 시계열·한은 회의 일정 받아 data/에 저장
  python -m bokwatch.decision_model           # 학습표·순차 검증·다음 회의 예측 → site/data/decision.json

입력(회의 3영업일 전, 그때 알 수 있던 값만)
  x1 CD 91일 − 기준금리 (bp)
  x2 CD 91일 20영업일 변화 (bp)
  x3 근원물가(식료품·에너지 제외) 전년동월비 − 물가목표 (%p). 발표 시점 기준: m월 지수는 m+1월 6일부터 사용
물가목표: 2016년부터 2.0%, 그 전 3.0%(2010~12 3±1%, 2013~15 2.5~3.5%의 가운데)
규제 강도(L2) λ=1.0, 순차 검증 시작 표본 40회는 결과를 보기 전에 고정했다.
결과(인상·동결·인하)는 회의 당일 기준금리와 전날 기준금리 비교. 임시회의(예: 2020-03-17) 변경은 정례회의 결과로 세지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from datetime import date, timedelta

import requests

from .common import DATA, SITE_DATA, d, load_config, now_kst, record_status, write_json
from .fetch_rates import ecos_get, value_on

HIST = DATA / "decision_inputs.csv"      # date,id,value (base·cd91 일별, core 월별)
MEETS = DATA / "meetings_history.csv"    # date (정례 통화정책방향 회의)
DATASET = DATA / "decision_dataset.csv"
OUT = SITE_DATA / "decision.json"
LAMBDA, START_N, N_BEFORE = 1.0, 40, 3
CLASSES = ("cut", "hold", "hike")
FEATURES = ("spread_bp", "cd_chg_bp", "core_gap")
# 사전에 정한 두 모형: M1 변수 3개, M2 = M1 + 직전 기준금리 변경 방향(최근 270일 안, 없으면 0). 이 둘만 시험한다.
MODELS = {"m1": ("spread_bp", "cd_chg_bp", "core_gap"), "m2": ("spread_bp", "cd_chg_bp", "core_gap", "last_move")}
LABELS = {"spread_bp": "CD − 기준금리(bp)", "cd_chg_bp": "CD 20영업일 변화(bp)", "core_gap": "근원물가 − 물가목표(%p)",
          "last_move": "직전 기준금리 변경 방향(+1 인상, −1 인하, 0 없음·270일 경과)"}


# ---------------------------------------------------------------- 수집
def fetch(cfg, start_year: int = 2007) -> None:
    from .fetch_bok import UA, parse_meeting_year
    rows = []
    s, e = f"{start_year}0101", now_kst().strftime("%Y%m%d")
    for r in ecos_get(cfg, "StatisticSearch", ["722Y001", "D", s, e, "0101000"]):
        rows.append((f"{r['TIME'][:4]}-{r['TIME'][4:6]}-{r['TIME'][6:]}", "base", r["DATA_VALUE"]))
    for r in ecos_get(cfg, "StatisticSearch", ["817Y002", "D", s, e, "010502000"]):
        rows.append((f"{r['TIME'][:4]}-{r['TIME'][4:6]}-{r['TIME'][6:]}", "cd91", r["DATA_VALUE"]))
    for r in ecos_get(cfg, "StatisticSearch", ["901Y010", "M", f"{start_year - 1}01", e[:6], "DB"]):
        rows.append((f"{r['TIME'][:4]}-{r['TIME'][4:6]}", "core", r["DATA_VALUE"]))
    with open(HIST, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "id", "value"])
        w.writerows(x for x in rows if x[2] not in (None, ""))
    meets = set()
    bok = cfg["bok"]
    for y in range(2008, now_kst().year + 1):
        r = requests.get(bok["meetings_page"]["url"].format(year=y), headers=UA, timeout=60)
        r.raise_for_status()
        meets |= set(parse_meeting_year(r.text, y, bok["base"]))
    with open(MEETS, "w", encoding="utf-8", newline="") as f:
        f.write("date\n" + "".join(m + "\n" for m in sorted(meets)))
    print(f"시계열 {len(rows)}행, 회의 {len(meets)}회 저장")


def load_inputs():
    ser = {"base": {}, "cd91": {}, "core": {}}
    with open(HIST, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ser[r["id"]][r["date"]] = float(r["value"])
    with open(MEETS, encoding="utf-8") as f:
        meets = [d(r["date"]) for r in csv.DictReader(f)]
    return ser, sorted(meets)


# ---------------------------------------------------------------- 특징
def target(day: date) -> float:
    return 2.0 if day.year >= 2016 else 3.0


def core_gap_on(core: dict, day: date):
    """day에 이미 발표된 최신 근원물가 전년동월비 − 목표. m월 지수는 m+1월 6일부터 쓴다."""
    y, m = day.year, day.month
    ym = (y, m - 1) if day.day >= 6 else (y, m - 2)
    while True:
        yy, mm = ym
        if mm <= 0:
            yy, mm = yy - 1, mm + 12
        cur, prev = core.get(f"{yy}-{mm:02d}"), core.get(f"{yy - 1}-{mm:02d}")
        if cur is not None and prev:
            return round((cur / prev - 1) * 100 - target(day), 3), f"{yy}-{mm:02d}"
        ym = (yy, mm - 1)
        if yy < 1990:
            return None, None


def features_on(ser, day: date) -> dict | None:
    cd_days = sorted(k for k in ser["cd91"] if k <= day.isoformat())
    if len(cd_days) < 21:
        return None
    cd_now, cd_20 = ser["cd91"][cd_days[-1]], ser["cd91"][cd_days[-21]]
    base, _ = value_on(ser["base"], day, 40)
    gap, cpi_m = core_gap_on(ser["core"], day)
    if base is None or gap is None:
        return None
    b = sorted((k, v) for k, v in ser["base"].items() if k <= day.isoformat())
    moves = [(k, v - p) for (k, v), (_, p) in zip(b[1:], b[:-1]) if abs(v - p) > 1e-9]
    last = moves[-1] if moves and (day - d(moves[-1][0])).days <= 270 else None
    return {"spread_bp": round((cd_now - base) * 100, 1), "cd_chg_bp": round((cd_now - cd_20) * 100, 1),
            "core_gap": gap, "last_move": (1 if last[1] > 0 else -1) if last else 0,
            "cpi_month": cpi_m, "rate_date": cd_days[-1], "base": base}


def build_dataset(ser, meets: list[date]) -> list[dict]:
    cd_dates = sorted(d(k) for k in ser["cd91"])
    rows = []
    for md in meets:
        if md < date(2008, 3, 1) or md > now_kst().date():
            continue
        prior = [x for x in cd_dates if x < md]
        if len(prior) < N_BEFORE + 21:
            continue
        obs = prior[-N_BEFORE]
        f = features_on(ser, obs)
        b_after, _ = value_on(ser["base"], md, 5)
        b_before, _ = value_on(ser["base"], md - timedelta(days=1), 40)
        if not f or b_after is None or b_before is None or md.isoformat() not in ser["base"]:
            continue
        mv = round((b_after - b_before) * 100)
        rows.append({"meeting": md.isoformat(), "obs_date": obs.isoformat(), **f,
                     "move_bp": mv, "actual": "hike" if mv > 0 else "cut" if mv < 0 else "hold"})
    return rows


# ---------------------------------------------------------------- 순서형 로지스틱
def _sig(z):
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit(rows: list[dict], lam: float = LAMBDA, feats=FEATURES) -> dict:
    import numpy as np
    from scipy.optimize import minimize
    X = np.array([[r[k] for k in feats] for r in rows], float)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1
    Z = (X - mu) / sd
    y = np.array([CLASSES.index(r["actual"]) for r in rows])

    def nll(w):
        beta, t1, dlt = w[:-2], w[-2], w[-1]
        t2 = t1 + math.exp(dlt)
        eta = Z @ beta
        c1 = 1 / (1 + np.exp(-(t1 - eta)))
        c2 = 1 / (1 + np.exp(-(t2 - eta)))
        p = np.where(y == 0, c1, np.where(y == 1, c2 - c1, 1 - c2))
        return -np.log(np.clip(p, 1e-12, None)).sum() + lam * (beta ** 2).sum()
    w0 = np.zeros(len(feats) + 2)
    w0[-2], w0[-1] = -2.0, math.log(4.0)
    res = minimize(nll, w0, method="L-BFGS-B")
    return {"beta": res.x[:-2].tolist(), "t1": float(res.x[-2]), "t2": float(res.x[-2] + math.exp(res.x[-1])),
            "mu": mu.tolist(), "sd": sd.tolist(), "n": len(rows), "feats": list(feats)}


def predict(m: dict, x: dict) -> dict:
    z = sum(b * (x[k] - mu) / sd for b, k, mu, sd in zip(m["beta"], m["feats"], m["mu"], m["sd"]))
    c1, c2 = _sig(m["t1"] - z), _sig(m["t2"] - z)
    return {"cut": round(c1, 4), "hold": round(c2 - c1, 4), "hike": round(1 - c2, 4)}


def _score(p: dict, actual: str):
    top = max(p.values())
    best = [k for k in p if abs(p[k] - top) < 1e-9]
    pred = best[0] if len(best) == 1 else "tie"
    return pred == actual, sum((p[k] - (1.0 if k == actual else 0.0)) ** 2 for k in CLASSES)


def walk_forward(rows: list[dict], start: int = START_N, feats=FEATURES) -> dict:
    preds = []
    for i in range(start, len(rows)):
        past, r = rows[:i], rows[i]
        m = fit(past, feats=feats)
        p = predict(m, r)
        freq = {k: (sum(x["actual"] == k for x in past) + 1) / (len(past) + 3) for k in CLASSES}
        hit, br = _score(p, r["actual"])
        bhit, bbr = _score(freq, r["actual"])
        preds.append({"meeting": r["meeting"], "actual": r["actual"], "move_bp": r["move_bp"],
                      **{f"p_{k}": p[k] for k in CLASSES}, "hit": hit, "brier": round(br, 4),
                      "base_rate": {f"p_{k}": round(freq[k], 4) for k in CLASSES}, "base_hit": bhit, "base_brier": round(bbr, 4),
                      "hold_hit": r["actual"] == "hold", "hold_brier": round(_score({"cut": 0, "hold": 1, "hike": 0}, r["actual"])[1], 4)})
    n = len(preds)

    def by(act, key):
        rs = [p for p in preds if p["actual"] == act]
        return {"n": len(rs), "hits": sum(p[key] for p in rs)}
    summ = {}
    for name, hk, bk in (("model", "hit", "brier"), ("base_rate", "base_hit", "base_brier"), ("always_hold", "hold_hit", "hold_brier")):
        summ[name] = {"hits": sum(p[hk] for p in preds), "brier": round(statistics.mean(p[bk] for p in preds), 4),
                      "by_actual": {a: by(a, hk) for a in CLASSES}}
    return {"n": n, "start_after": start, "first": preds[0]["meeting"] if preds else None, "summary": summ, "rows": preds}


# ---------------------------------------------------------------- 실행
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config()
    try:
        if a.fetch or not HIST.exists() or not MEETS.exists():
            fetch(cfg)
        ser, meets = load_inputs()
        rows = build_dataset(ser, meets)
        with open(DATASET, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, ["meeting", "obs_date", "rate_date", *MODELS["m2"], "cpi_month", "base", "move_bp", "actual"])
            w.writeheader()
            w.writerows({k: r[k] for k in w.fieldnames} for r in rows)
        today = now_kst().date()
        upcoming = sorted(m for m in meets if m > today) or sorted(
            d(x) for ys in cfg["meetings"].values() for x in (ys or []) if d(x) > today)
        x = features_on(ser, today)
        models = {}
        for name, feats in MODELS.items():
            wf = walk_forward(rows, feats=feats)
            full = fit(rows, feats=feats)
            s = wf["summary"]
            # 의미 있는 개선: 과거 결정 빈도보다 Brier 5% 이상 낮고 항상 동결보다도 낮아야 한다.
            # 5%는 첫 결과(2026-10-15)를 본 뒤 정한 값이다. 이후 평가에서는 바꾸지 않는다.
            beats = s["model"]["brier"] < 0.95 * s["base_rate"]["brier"] and s["model"]["brier"] < s["always_hold"]["brier"]
            models[name] = {"features": [{"key": k, "label": LABELS[k]} for k in feats],
                            "coef_standardized": dict(zip(feats, [round(b, 3) for b in full["beta"]])),
                            "walk_forward": wf, "beats_baselines": beats,
                            "next": ({"meeting": upcoming[0].isoformat(), "probs": predict(full, x)} if upcoming and x else None)}
        out = {"updated": now_kst().isoformat(timespec="minutes"), "n_meetings": len(rows),
               "span": [rows[0]["meeting"], rows[-1]["meeting"]] if rows else None,
               "class_counts": {k: sum(r["actual"] == k for r in rows) for k in CLASSES},
               "lambda": LAMBDA, "start_n": START_N, "inputs_today": x, "models": models,
               "adopt": any(m["beats_baselines"] for m in models.values()),
               "verdict": ("순차 검증에서 단순 비교 기준을 의미 있게 넘은 모형이 있다." if any(m["beats_baselines"] for m in models.values())
                           else "두 모형 모두 순차 검증에서 '과거 결정 빈도'를 의미 있게(Brier 5% 이상) 넘지 못했다. 화면 기본값으로 쓰지 않고 기록만 한다.")}
        write_json(OUT, out)
        sm = {k: v["walk_forward"]["summary"] for k, v in models.items()}
        record_status("decision", True, f"회의 {len(rows)}회 · Brier M1 {sm['m1']['model']['brier']} · M2 {sm['m2']['model']['brier']}"
                                        f" · 빈도 {sm['m1']['base_rate']['brier']} · 동결 {sm['m1']['always_hold']['brier']}")
        print(out["verdict"], {k: v["model"]["brier"] for k, v in sm.items()}, "빈도", sm["m1"]["base_rate"]["brier"])
    except Exception as e:
        record_status("decision", False, f"{type(e).__name__}: {e}")
        print(f"결정 예측 실패: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
