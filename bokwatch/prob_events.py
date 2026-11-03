"""확률이 크게 움직인 날과 동시에 있었던 이벤트(규칙 기반).

- 대상: 다음 회의의 종합 예측(M5) 인상 확률, 기준일(금리 관측일)별. 전일 대비 변화 절댓값이 THRESH 이상인 날.
- 같이 보이는 것: 그 날·전날의 경제지표·행사 이벤트, 시장금리 변화(bp), 한은 발언 행사, 허용 38개 언론사의 강도 높은 기사.
- 이것은 '시간적으로 같이 있었던 이벤트'이며 원인이 아니다. 발표 시각·이벤트 전후 가격을 알 수 없어 일간 변화만 쓴다.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

THRESH = 0.05
RATE_IDS = ("cd91", "msb91", "kofr", "ktb3y")


def series_of(series: dict, meeting: str) -> list[tuple[str, float, str]]:
    days = (series.get("meetings") or {}).get(meeting) or {}
    return sorted((k, v["m5"]["hike"], v.get("kind")) for k, v in days.items() if v.get("m5"))


def rate_changes(rates_csv: Path, day: str, prev_day: str) -> dict:
    vals: dict[str, dict[str, float]] = {}
    if not rates_csv.exists():
        return {}
    for r in csv.DictReader(open(rates_csv, encoding="utf-8")):
        if r["id"] in RATE_IDS and r["date"] in (day, prev_day):
            vals.setdefault(r["id"], {})[r["date"]] = float(r["value"])
    out = {}
    for k, v in vals.items():
        if day in v and prev_day in v:
            out[k] = round((v[day] - v[prev_day]) * 100, 1)       # bp
    return out


def short_label(label: str, n: int = 38) -> str:
    """이벤트 이름을 한 줄 요약으로: 괄호 안 부연을 떼고 길면 자른다."""
    t = label.split("(")[0].strip().rstrip(",")
    return t if len(t) <= n else t[:n].rstrip() + "…"


def event_text(e: dict, decisions: dict[str, dict]) -> str:
    """이벤트 한 줄 요약. 금통위 결정은 결정 내용, 그 밖에는 이벤트 이름을 줄인 것."""
    if e.get("kind") == "bok" and e.get("date") in decisions:
        m = decisions[e["date"]]
        return f"금통위 결정: 기준금리 {float(m['rate']):.2f}% {m.get('decision') or ''}".strip()
    return short_label(e.get("label") or "")


def speech_text(s: dict) -> str:
    """'총재 국회 발언(매파): 연속 인상이 환율 안정에 기여' — 왜 그런 논조인지 한 줄 이유를 붙인다."""
    v = s.get("verdict") or ""
    head = f"총재 {s['venue']} 발언" + (f"({v})" if v in ("매파", "중립", "비둘기파") else "")
    return head + (f": {s['reason']}" if s.get("reason") else "")


def related_events(events: list[dict], day: str) -> list[dict]:
    """그 날과 전날(미국 저녁 발표 등이 다음 기준일에 반영되는 경우) 이벤트. 중요도 2 이상."""
    d0 = date.fromisoformat(day)
    keys = {day, (d0 - timedelta(days=1)).isoformat()}
    return [{k: e.get(k) for k in ("date", "time", "label", "country", "kind", "link", "source", "verify")}
            for e in events if e.get("date") in keys and (e.get("importance") or 1) >= 2]


def build(series: dict, meeting: str, events: list[dict], speech_events: list[dict], articles: list[dict], rates_csv: Path, thresh: float = THRESH,
          meetings: list[dict] | None = None) -> dict:
    s = series_of(series, meeting)
    decisions = {m["date"]: m for m in (meetings or []) if m.get("decision")}
    rows = []
    for (d_prev, p_prev, _), (d_cur, p_cur, kind) in zip(s, s[1:]):
        delta = p_cur - p_prev
        if abs(delta) < thresh:
            continue
        arts = [a for a in articles if (a.get("published") or "")[:10] == d_cur and a.get("press_name") and a.get("strength", 0) >= 2][:3]
        rows.append({
            "date": d_cur, "prev_date": d_prev, "p_before": round(p_prev, 4), "p_after": round(p_cur, 4), "delta": round(delta, 4), "kind": kind,
            "events": related_events(events, d_cur),
            "speeches": [{"date": e["date"], "venue": e["venue"], "verdict": e["verdict"], "reason": e.get("reason")} for e in speech_events if e["date"] in (d_cur, d_prev)],
            "lines": [],
            "rates_bp": rate_changes(rates_csv, d_cur, d_prev),
            "articles": [{k: a.get(k) for k in ("press_name", "published", "title", "link", "direction", "strength")} for a in arts],
        })
    for r in rows:        # 화면용 한 줄 요약들(없으면 빈 목록 → 화면에서 '이벤트 없음')
        r["lines"] = [event_text(e, decisions) for e in r["events"]] + [speech_text(x) for x in r["speeches"]]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {"meeting": meeting, "threshold": thresh, "rows": rows,
            "note": "확률이 전일보다 {}%p 이상 움직인 날. 같이 표시한 이벤트는 시간적으로 겹친 것이며 원인이라고 확인되지 않았다. 발표 시각·이벤트 전후 가격이 없어 일간 변화만 본다.".format(int(thresh * 100))}
