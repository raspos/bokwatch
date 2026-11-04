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


def annotate_press(reports: list[dict]) -> list[dict]:
    """보고서 출처(link)가 허용 38개 매체 기사인지 표시한다. 링크가 없거나 허용 목록 밖이면 'excluded'(원출처 확인 불가 포함)."""
    from .press import default_index
    idx = default_index()
    for x in reports:
        res = idx.identify({"link": x.get("link") or ""})
        o = idx.outlets.get(res["outlet"]) if res["outlet"] else None
        x["press_status"] = res["status"] if x.get("link") else "excluded"
        x["press_name"] = o["name"] if o else None
        x["press_reason"] = res["reason"] if x.get("link") else "링크 없음: 출처 확인 불가"
    return reports


def allowed_reports(reports: list[dict]) -> list[dict]:
    return [x for x in annotate_press(reports) if x["press_status"] == "allowed"]


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


def consensus(reports: list[dict], meetings: list[str], today: date | None = None, since: str | None = None) -> dict:
    """회의별 전망 기관 수, 최종금리 분포. 같은 기관은 그 회의에 대한 최신 보고서만 쓴다.
    since가 없으면 기준일 포함 최근 5영업일 안에 나온 보고서만(지난 회의 평가용). since가 있으면 그날 이후 발표된 보고서 전체에서
    기관별 최신(직전 결정 이후 나온 전망은 5영업일이 지나도 유효한 전망으로 본다 — 화면에 발표일을 함께 보인다)."""
    win = since or (window_start(today).isoformat() if today else None)
    ok = [r for r in sorted(reports, key=lambda x: x["published"]) if not (win and r["published"] < win)]
    latest_any: dict[str, dict] = {}
    for r in ok:
        latest_any[r["institution"]] = r
    per = {}
    for m in meetings:
        best: dict[str, dict] = {}
        for r in ok:
            if (r.get("calls") or {}).get(m):
                best[r["institution"]] = r
        c = Counter(x["calls"][m]["call"] for x in best.values())
        n = sum(c.values())
        per[m] = {"counts": dict(c), "n": n, "hike_share": round(c.get("인상", 0) / n, 4) if n else None,
                  "latest": max((x["published"] for x in best.values()), default=None)}
    term = Counter(f"{r['terminal']:.2f}" for r in latest_any.values() if r.get("terminal") is not None)
    return {"by_meeting": per, "terminal": dict(sorted(term.items())), "institutions": len(latest_any),
            "since": win, "window_bd": None if since else WINDOW_BD, "mode": "since" if since else "window"}


def new_reports(reports: list[dict], today: date, days: int = 2) -> list[dict]:
    return [r for r in reports if d(r["published"]) >= today - timedelta(days=days)]


def last_decision_date(today: date) -> str | None:
    """오늘 이전 마지막 금통위 결정일(이후 나온 전망을 현재 회의에 대한 유효한 전망으로 본다)."""
    from .common import load_config
    ds = sorted(x["date"] for x in load_config().get("past_decisions", []) if str(x["date"]) <= today.isoformat())
    return str(ds[-1]) if ds else None


def build_reports(meetings: list[str], today: date) -> dict:
    r = load_reports()
    all_reps = annotate_press(sorted(r["reports"], key=lambda x: x["published"], reverse=True))
    reps = [x for x in all_reps if x["press_status"] == "allowed"]       # 보고서 표·집계는 허용 38개 매체 출처만
    since = last_decision_date(today) or window_start(today).isoformat()      # 직전 결정 이후 발표된 전망이 유효
    newest = {}
    for x in sorted(reps, key=lambda z: z["published"]):
        newest[x["institution"]] = id(x)
    for x in reps:
        x["in_window"] = x["published"] >= since
        x["superseded"] = newest[x["institution"]] != id(x)
    return {
        "asof": r.get("asof"),
        "reports": reps,
        "press_excluded": len(all_reps) - len(reps),
        "consensus": consensus(reps, meetings, today, since=last_decision_date(today)),
        "new": [x["institution"] for x in new_reports(reps, today)],
        "kofia": r["kofia_survey"],
    }
