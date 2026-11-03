"""뉴스 지표 4종(보도량·방향성·논조 변화·정책 신호 강도)과 주요 신호 목록.

보도량(관심도)과 논조를 따로 계산한다. 기사 수가 많다는 이유만으로 매파 점수가 오르지 않는다.
  관심도      통화정책 관련 기사 수(중복 제외 전 허용 언론사 기준)의 최근 72시간 대 직전 72시간 변화
  방향성      관련 사건의 인상 압력·중립·인하 압력 비중(같은 사건은 한 번)
  논조 변화   최근 72시간 압력지수 − 직전 72시간 압력지수, 그리고 최근 7일 평균 대비
  정책 신호 강도  강도 3인 사건 수와 근거 유형별(직접발언 우선) 분포
모든 계산은 규칙 기반이며 모델을 부르지 않는다. 언론사별 가중치는 쓰지 않는다(초기 원칙).
"""
from __future__ import annotations

from datetime import datetime, timedelta

DIRS = {"인상 압력": 1, "중립": 0, "인하 압력": -1}


def _index(arts: list[dict], tags: dict) -> dict:
    from .ai_judge import group_by_title, pressure_index
    if not arts:
        return {"index": None, "n": 0, "n_articles": 0}
    since = min(datetime.fromisoformat(a["published"]) for a in arts)
    return pressure_index(arts, tags, since, group_by_title(arts))


def _relevant(arts: list[dict], tags: dict) -> list[dict]:
    return [a for a in arts if tags.get(a["id"], {}).get("relevant")]


def _window(arts: list[dict], start: datetime, end: datetime) -> list[dict]:
    return [a for a in arts if start <= datetime.fromisoformat(a["published"]) < end]


def _share(arts: list[dict], tags: dict) -> dict:
    """사건 단위 방향 비중(같은 제목 묶음은 한 사건)."""
    from .ai_judge import group_by_title
    out = {"인상 압력": 0, "중립": 0, "인하 압력": 0}
    if not arts:
        return {"n_events": 0, **{k: None for k in out}}
    by = {a["id"]: a for a in arts}
    for g in group_by_title(arts):
        ts = [tags[i] for i in g["ids"] if i in by]
        w = sum(t["strength"] for t in ts)
        d = sum(DIRS[t["direction"]] * t["strength"] for t in ts) / w
        out["인상 압력" if d > 0.2 else "인하 압력" if d < -0.2 else "중립"] += 1
    n = sum(out.values())
    return {"n_events": n, **{k: round(v / n, 3) for k, v in out.items()}}


def top_signals(arts: list[dict], tags: dict, direction: str, k: int = 5) -> list[dict]:
    """주요 매파(인상 압력)·비둘기파(인하 압력) 신호: 강도 높은 순, 근거 유형이 직접발언인 것을 먼저."""
    rows = []
    for a in arts:
        t = tags.get(a["id"], {})
        if t.get("relevant") and t.get("direction") == direction and t.get("strength", 0) >= 2 and t.get("target_bank", "한은") == "한은":   # 연준·해외 기사는 한은 신호로 올리지 않는다
            rows.append((t.get("source_type") == "직접발언", t["strength"], a["published"], a, t))
    rows.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    return [{"press": a.get("press_name"), "published": a["published"][:16], "title": a["title"], "link": a["link"], "reason": t.get("reason"),
             "strength": t["strength"], "source_type": t.get("source_type") or "미분류"} for _, _, _, a, t in rows[:k]]


def compute(all_articles: list[dict], tags: dict, now: datetime, window_h: int = 72) -> dict:
    allowed = [a for a in all_articles if a.get("press_status") == "allowed"]
    uniq = [a for a in allowed if a.get("dup_type") not in ("재수집", "통신사 전재", "제목 변경", "수정·업데이트")]
    w = timedelta(hours=window_h)
    cur_s, prev_s = now - w, now - 2 * w
    rel_all_cur = _relevant(_window(allowed, cur_s, now + timedelta(minutes=1)), tags)       # 보도량은 중복 포함(얼마나 많이 다뤘나)
    rel_all_prev = _relevant(_window(allowed, prev_s, cur_s), tags)
    cur = _relevant(_window(uniq, cur_s, now + timedelta(minutes=1)), tags)                  # 논조는 중복 제외(같은 신호 반복 방지)
    prev = _relevant(_window(uniq, prev_s, cur_s), tags)
    week = _relevant(_window(uniq, now - timedelta(days=7), now + timedelta(minutes=1)), tags)
    i_cur, i_prev, i_week = _index(cur, tags), _index(prev, tags), _index(week, tags)
    d = lambda a, b: None if a is None or b is None else round(a - b, 3)       # noqa: E731
    pct = lambda a, b: None if not b else round((a - b) / b, 3)               # noqa: E731
    daily = []
    for k in range(13, -1, -1):
        day = (now - timedelta(days=k)).date()
        s = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo)
        da = _window(allowed, s, s + timedelta(days=1))
        du = _window(uniq, s, s + timedelta(days=1))
        ix = _index(_relevant(du, tags), tags)
        daily.append({"date": day.isoformat(), "reports": len(_relevant(da, tags)), "events": ix["n"], "index": ix["index"]})
    strong = [a for a in cur if tags[a["id"]].get("strength") == 3]
    src = {}
    for a in strong:
        k = tags[a["id"]].get("source_type") or "미분류"
        src[k] = src.get(k, 0) + 1
    return {
        "window_hours": window_h,
        "interest": {"reports_now": len(rel_all_cur), "reports_prev": len(rel_all_prev), "change_pct": pct(len(rel_all_cur), len(rel_all_prev)),
                     "note": "통화정책 관련 기사 수(중복 포함). 많다고 매파라는 뜻이 아니다."},
        "direction": _share(cur, tags),
        "tone_change": {"index_now": i_cur["index"], "index_prev": i_prev["index"], "vs_prev_window": d(i_cur["index"], i_prev["index"]),
                        "index_7d": i_week["index"], "vs_7d": d(i_cur["index"], i_week["index"])},
        "signal_strength": {"strong_articles": len(strong), "by_source_type": src},
        "hawk_signals": top_signals(cur, tags, "인상 압력"),
        "dove_signals": top_signals(cur, tags, "인하 압력"),
        "daily": daily,
    }
