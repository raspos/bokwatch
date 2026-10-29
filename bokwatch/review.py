"""가장 최근에 끝난 금통위의 결과와 예측 적중도(모형·전문가·금투협 설문). 날짜별 기록은 고치지 않고 읽기만 한다."""
from __future__ import annotations

from datetime import date, timedelta

from .common import d
from .reports import consensus

KINDS = (("hike", "인상"), ("hold", "동결"), ("cut", "인하"))
KO = dict(KINDS)


def top_kind(p: dict) -> str | None:
    """가장 높은 확률의 결과. 최고값이 둘 이상 같으면 None(적중으로 치지 않는다)."""
    v = {k: float(p.get(k) or 0) for k, _ in KINDS}
    best = max(v.values())
    top = [k for k, x in v.items() if abs(x - best) < 1e-9]
    return top[0] if len(top) == 1 else None


def business_days_before(day: date, n: int) -> date:
    k = 0
    while k < n:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            k += 1
    return day


def _model_row(r: dict, actual: str) -> dict:
    p = {"hike": float(r["p_hike"]), "hold": float(r["p_hold"]), "cut": float(r["p_cut"] or 0)}
    top = top_kind(p)
    return {"date": r["date"], "asof": r["asof"], "p": p, "expected": float(r["expected"]) if r.get("expected") not in ("", None) else None,
            "instrument": r.get("instrument"), "top": top, "hit": top == actual}


def _model_m5(series, M, rows, actual, d3_day, g) -> dict | None:
    """M5(종합 예측) 기준 적중도. 기준일에 알 수 있던 자료로 다시 계산한 값이면 kind=retro(사후 재계산), 당시 저장 값이면 stored."""
    days = ((series or {}).get("meetings") or {}).get(M) or {}
    if not rows or not days:
        return None

    def row(day):
        e = days.get(day)
        if not e or not e.get("m5"):
            return None
        p = e["m5"]
        top = top_kind(p)
        exp = round(float(g["prev_rate"]) + 0.25 * (p["hike"] - p["cut"]), 3)
        return {"date": day, "asof": day, "p": p, "expected": exp, "top": top, "hit": top == actual, "kind": e.get("kind")}

    final = row(rows[-1]["asof"])
    if not final:
        return None
    out = {"final": final, "d3": row(d3_day), "d3_day": d3_day,
           "path": [[k, e["m5"]["hike"]] for k, e in sorted(days.items()) if e.get("m5")]}
    out["predicted_change_bp"] = round((final["expected"] - float(g["prev_rate"])) * 100, 1)
    return out


def build_review(guidance: dict, plog: list[dict], reports: list[dict], kofia: list[dict], today: date, series: dict | None = None) -> dict | None:
    done = [m for m in guidance.get("meetings", []) if m.get("decision") and d(m["date"]) <= today and m.get("prev_rate") is not None]
    if not done:
        return None
    g = max(done, key=lambda m: m["date"])
    M = g["date"]
    change_bp = round((float(g["rate"]) - float(g["prev_rate"])) * 100, 1)
    actual = "hike" if change_bp > 0 else "cut" if change_bp < 0 else "hold"
    out = {"meeting": M, "decision": g["decision"], "rate": g["rate"], "prev_rate": g["prev_rate"], "change_bp": change_bp,
           "actual": actual, "vote": g.get("vote")}

    rows = [r for r in plog if r.get("status") == "산출" and r.get("meeting") == M and len(r["date"]) == 10 and r["date"] <= M]
    rows.sort(key=lambda r: r["date"])
    model = None
    if rows:
        final = _model_row(rows[-1], actual)
        d3_day = business_days_before(d(M), 3).isoformat()
        d3r = [r for r in rows if r["asof"] == d3_day]
        model = {"final": final, "d3": _model_row(d3r[-1], actual) if d3r else None, "d3_day": d3_day,
                 "path": [[r["date"], round(float(r["p_hike"]), 4)] for r in rows]}
        if final["expected"] is not None:
            model["predicted_change_bp"] = round((final["expected"] - float(g["prev_rate"])) * 100, 1)
    out["model"] = model
    out["model_m5"] = _model_m5(series, M, rows, actual, d3_day if rows else None, g)

    c = consensus(reports, [M], d(M))
    cm = c["by_meeting"].get(M) or {}
    if cm.get("n"):
        order = {"인상": "hike", "동결": "hold", "인하": "cut"}
        p = {order[k]: v / cm["n"] for k, v in cm["counts"].items() if k in order}
        top = top_kind(p)
        out["experts"] = {"n": cm["n"], "counts": cm["counts"], "since": c["since"], "top": top, "hit": top == actual}
    else:
        out["experts"] = None

    my = d(M)
    ny, nm = (my.year + (my.month == 12), my.month % 12 + 1)  # 10월 회의 → '11월 채권시장지표'
    label = f"{ny}-{nm:02d}"
    k = next((x for x in kofia if x.get("month") == label and x.get("status") == "발표"), None)
    if k:
        p = {"hike": (k.get("hike") or 0) / 100, "hold": (k.get("hold") or 0) / 100, "cut": (k.get("cut") or 0) / 100}
        top = top_kind(p)
        out["kofia"] = {"month": label, "hold": k.get("hold"), "hike": k.get("hike"), "cut": k.get("cut"), "respondents": k.get("respondents"),
                        "top": top, "hit": top == actual}
    else:
        out["kofia"] = None
    return out
