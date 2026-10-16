"""보고서 전망 집계(컨센서스)."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from .common import d, load_yaml


def load_reports() -> dict:
    r = load_yaml("reports.yaml")
    r.setdefault("reports", [])
    r.setdefault("kofia_survey", [])
    return r


WINDOW_BD = 5  # 집계에 넣는 보고서: 기준일 포함 최근 5영업일 안에 나온 것


def window_start(today: date, n: int = WINDOW_BD) -> date:
    """기준일 포함 n영업일(주말 제외) 전의 첫날."""
    d, k = today, 0
    while True:
        if d.weekday() < 5:
            k += 1
            if k == n:
                return d
        d -= timedelta(days=1)


def consensus(reports: list[dict], meetings: list[str], today: date | None = None) -> dict:
    """회의별 전망 기관 수, 최종금리 분포. 같은 기관은 최신 보고서만, 최근 5영업일 안에 나온 것만."""
    since = window_start(today).isoformat() if today else None
    latest: dict[str, dict] = {}
    for r in sorted(reports, key=lambda x: x["published"]):
        if since and r["published"] < since:
            continue
        latest[r["institution"]] = r
    per = {}
    for m in meetings:
        c = Counter()
        for r in latest.values():
            call = (r.get("calls") or {}).get(m)
            if call:
                c[call["call"]] += 1
        n = sum(c.values())
        per[m] = {"counts": dict(c), "n": n,
                  "hike_share": round(c.get("인상", 0) / n, 4) if n else None}
    term = Counter(f"{r['terminal']:.2f}" for r in latest.values() if r.get("terminal") is not None)
    return {"by_meeting": per, "terminal": dict(sorted(term.items())), "institutions": len(latest),
            "since": since, "window_bd": WINDOW_BD}


def new_reports(reports: list[dict], today: date, days: int = 2) -> list[dict]:
    return [r for r in reports if d(r["published"]) >= today - timedelta(days=days)]


def build_reports(meetings: list[str], today: date) -> dict:
    r = load_reports()
    reps = sorted(r["reports"], key=lambda x: x["published"], reverse=True)
    since = window_start(today).isoformat()
    for x in reps:
        x["in_window"] = x["published"] >= since
    return {
        "asof": r.get("asof"),
        "reports": reps,
        "consensus": consensus(reps, meetings, today),
        "new": [x["institution"] for x in new_reports(reps, today)],
        "kofia": r["kofia_survey"],
    }
