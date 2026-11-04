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


def speaker_label(speakers: list[str] | None) -> str:
    sp = speakers or []
    if any(x.endswith("총재") and "부총재" not in x for x in sp) or not sp:
        return "총재"
    return sp[0]


def speech_text(s: dict) -> str:
    """'총재 국회 발언(매파): 연속 인상이 환율 안정에 기여' — 왜 그런 논조인지 한 줄 이유를 붙인다."""
    v = s.get("verdict") or ""
    head = f"{speaker_label(s.get('speakers'))} {s['venue']} 발언" + (f"({v})" if v in ("매파", "중립", "비둘기파") else "")
    return head + (f": {s['reason']}" if s.get("reason") else "")


def headline_of(items: list[dict], r: dict, decisions: dict[str, dict]) -> str:
    """그래프 위 말풍선에 쓰는 아주 짧은 제목: 금통위 결정 > 발언 > 지표 > 기관 전망 > 시장금리 순."""
    for e in r["events"]:
        if e.get("kind") == "bok" and e.get("date") in decisions:
            m = decisions[e["date"]]
            return f"금통위 {float(m['rate']):.2f}% {m.get('decision') or ''}".strip()
    if r["speeches"]:
        x = r["speeches"][0]
        return f"{speaker_label(x.get('speakers'))} {x['venue']} 발언"[:16]
    ind = [e for e in r["events"] if e.get("kind") != "bok"]
    if ind:
        return short_label(ind[0].get("label") or "", 14)
    if any(i["type"] == "forecast" for i in items):
        return "기관 전망 발표"
    return "시장금리 변동" if items else ""


RATE_NAMES = {"cd91": "CD 91일", "msb91": "통안채 91일", "ktb3y": "국고채 3년", "kofr": "KOFR"}


def rates_text(bp: dict) -> str:
    """시장금리 일간 변화 한 줄(1bp 이상만, 변화가 큰 순 3개). 모두 1bp 미만이면 '시장금리 변동 미미'."""
    big = sorted(((k, v) for k, v in bp.items() if abs(v) >= 1), key=lambda kv: -abs(kv[1]))[:3]
    if not big:
        return "시장금리 변동 미미" if bp else ""
    return "시장금리: " + " · ".join(f"{RATE_NAMES.get(k, k)} {v:+.1f}bp" for k, v in big)


def forecast_text(reports: list[dict], meeting: str, d_cur: str, d_prev: str) -> str:
    """그 날·전날 발표된 기관 전망 한 줄: '기관 전망 6곳 발표(11/26 인상 5·동결 1)'."""
    hit = [r for r in reports if str(r.get("published")) in (d_cur, d_prev) and (r.get("calls") or {}).get(meeting)]
    if not hit:
        return ""
    cnt: dict[str, int] = {}
    for r in hit:
        c = r["calls"][meeting]["call"]
        cnt[c] = cnt.get(c, 0) + 1
    md = f"{int(meeting[5:7])}/{int(meeting[8:10])}"
    return f"기관 전망 {len(hit)}곳 발표({md} " + "·".join(f"{k} {v}" for k, v in cnt.items()) + ")"


def related_events(events: list[dict], day: str) -> list[dict]:
    """그 날 이벤트 + 전날 한국 시간 15:30 이후 발표(미국 저녁 지표 등, 다음 기준일에 반영). 시각이 없는 전날 일정은 그 날 것이므로 넣지 않는다."""
    d0 = date.fromisoformat(day)
    prev = (d0 - timedelta(days=1)).isoformat()
    out = []
    for e in events:
        if e.get("date") == day or (e.get("date") == prev and (e.get("time") or "") >= "15:30"):
            out.append({k: e.get(k) for k in ("date", "time", "label", "country", "kind", "link", "source", "verify")})
    return out


def build(series: dict, meeting: str, events: list[dict], speech_events: list[dict], articles: list[dict], rates_csv: Path, thresh: float = THRESH,
          meetings: list[dict] | None = None, reports: list[dict] | None = None) -> dict:
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
            "speeches": [{"date": e["date"], "venue": e["venue"], "verdict": e["verdict"], "reason": e.get("reason"), "speakers": e.get("speakers")} for e in speech_events if e["date"] == d_cur],
            "lines": [],
            "rates_bp": rate_changes(rates_csv, d_cur, d_prev),
            "articles": [{k: a.get(k) for k in ("press_name", "published", "title", "link", "direction", "strength")} for a in arts],
        })
    for r in rows:        # 화면용 항목: 일정·발언에 더해 기관 전망 발표와 시장금리 변화를 함께 보인다(각 항목은 종류 태그와 한 줄 요약)
        items = [{"type": "bok" if e.get("kind") == "bok" else "indicator", "text": event_text(e, decisions)} for e in r["events"]]
        items += [{"type": "speech", "text": speech_text(x)} for x in r["speeches"]]
        ft = forecast_text(reports or [], meeting, r["date"], r["prev_date"])
        if ft:
            items.append({"type": "forecast", "text": ft})
        rt = rates_text(r["rates_bp"])
        if rt:
            items.append({"type": "market", "text": rt})
        r["items"] = items
        r["headline"] = headline_of(items, r, decisions)
        r["lines"] = [i["text"] for i in items]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    lanes = {"bok": [], "speech": [], "indicator": [], "forecast": []}
    if s:
        lo, hi = s[0][0], s[-1][0]
        for e in events:
            if lo <= str(e.get("date")) <= hi:
                if e.get("kind") in ("bok", "minutes"):
                    lanes["bok"].append({"date": e["date"], "text": event_text(e, decisions)})
                elif (e.get("importance") or 1) >= 2:
                    lanes["indicator"].append({"date": e["date"], "text": event_text(e, decisions)})
        for sp in speech_events:
            if lo <= sp["date"] <= hi:
                lanes["speech"].append({"date": sp["date"], "text": speech_text(sp)})   # sp에는 speakers가 들어 있다
        for dd in sorted({str(r.get("published")) for r in (reports or [])}):
            if lo <= dd <= hi:
                ft = forecast_text(reports or [], meeting, dd, dd)
                if ft:
                    lanes["forecast"].append({"date": dd, "text": ft})
    return {"meeting": meeting, "threshold": thresh, "rows": rows, "lanes": lanes,
            "note": "확률이 전일보다 {}%p 이상 움직인 날. 같이 표시한 이벤트는 시간적으로 겹친 것이며 원인이라고 확인되지 않았다. 발표 시각·이벤트 전후 가격이 없어 일간 변화만 본다.".format(int(thresh * 100))}
