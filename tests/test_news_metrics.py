"""뉴스 지표: 보도량과 논조를 분리한다(기사가 많아도 논조가 오르지 않는다), 중복은 논조에서 한 번만."""
from datetime import datetime, timedelta

from bokwatch import news_metrics as N

NOW = datetime.fromisoformat("2026-11-03T12:00+09:00")


def uniq(i):
    """서로 겹치지 않는 제목(제목 유사도 묶음에 걸리지 않게)."""
    return "".join(chr(0xAC00 + (i * 97 + j * 311) % 11000) for j in range(14))


def art(i, title, hours_ago, dup=None, press="hankyung"):
    return {"id": f"a{i}", "title": title, "summary": "", "link": f"L{i}", "press_status": "allowed", "press_id": press, "press_name": press,
            "dup_type": dup or "독립 보도", "published": (NOW - timedelta(hours=hours_ago)).isoformat(timespec="minutes")}


def tag(d="인상 압력", s=2, src=None, bank="한은"):
    return {"relevant": True, "direction": d, "strength": s, "factor": "물가", "reason": "r", "target_bank": bank, **({"source_type": src} if src else {})}


def test_volume_does_not_move_tone():
    base = [art(i, uniq(i), 5 + i) for i in range(4)]
    tags = {a["id"]: tag("인상 압력") for a in base}
    # 중립 기사 40건을 더해도 인상 압력 사건의 방향은 그대로, 보도량만 늘어난다
    more = base + [art(100 + i, uniq(100 + i), 5 + i % 40) for i in range(40)]
    tags.update({a["id"]: tag("중립") for a in more if a["id"] not in tags})
    m1, m2 = N.compute(base, {k: tags[k] for k in (a["id"] for a in base)}, NOW), N.compute(more, tags, NOW)
    assert m2["interest"]["reports_now"] == m1["interest"]["reports_now"] + 40
    assert m1["direction"]["인상 압력"] == 1.0 and m2["direction"]["인상 압력"] < 0.2        # 비중은 바뀌어도 기사 수 자체가 점수를 올리지 않는다
    assert m1["tone_change"]["index_now"] == 1.0


def test_duplicates_count_in_volume_but_not_in_tone():
    a = [art(0, "한은 총재 인상 시사 발언 기사", 3), art(1, "한은 총재 인상 시사 발언 기사", 2, dup="통신사 전재", press="heraldcorp")]
    t = {"a0": tag("인상 압력"), "a1": tag("인상 압력")}
    m = N.compute(a, t, NOW)
    assert m["interest"]["reports_now"] == 2 and m["direction"]["n_events"] == 1


def test_signals_only_for_boks_own_direction_and_sorted_by_source():
    a = [art(0, "RBA 인상", 2), art(1, "한은 총재 인상 직접 발언", 3), art(2, "전문가 해석 인상", 4)]
    t = {"a0": tag("인상 압력", 3, bank="기타 해외"), "a1": tag("인상 압력", 3, "직접발언"), "a2": tag("인상 압력", 2, "전문가해석")}
    sig = N.top_signals(a, t, "인상 압력")
    assert [s["title"] for s in sig] == ["한은 총재 인상 직접 발언", "전문가 해석 인상"]      # 해외 기사 제외, 직접발언 우선
