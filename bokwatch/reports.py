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


def consensus(reports: list[dict], meetings: list[str]) -> dict:
    """회의별 전망 기관 수, 최종금리 분포. 같은 기관은 최신 보고서만."""
    latest: dict[str, dict] = {}
    for r in sorted(reports, key=lambda x: x["published"]):
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
    return {"by_meeting": per, "terminal": dict(sorted(term.items())), "institutions": len(latest)}


def new_reports(reports: list[dict], today: date, days: int = 2) -> list[dict]:
    return [r for r in reports if d(r["published"]) >= today - timedelta(days=days)]


def build_reports(meetings: list[str], today: date) -> dict:
    r = load_reports()
    reps = sorted(r["reports"], key=lambda x: x["published"], reverse=True)
    return {
        "asof": r.get("asof"),
        "reports": reps,
        "consensus": consensus(reps, meetings),
        "new": [x["institution"] for x in new_reports(reps, today)],
        "kofia": r["kofia_survey"],
    }
