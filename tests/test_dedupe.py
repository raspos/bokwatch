"""기사 중복 판정 규칙: 재수집·통신사 전재·제목 변경·수정은 하나만 남기고, 같은 사건·독립 보도는 지우지 않는다."""
from datetime import datetime, timedelta

from bokwatch import dedupe

T0 = datetime.fromisoformat("2026-11-03T08:00+09:00")


def art(i, press, title, summary="", dh=0.0):
    return {"id": f"a{i}", "press_id": press, "title": title, "summary": summary,
            "published": (T0 + timedelta(hours=dh)).isoformat(timespec="minutes")}


def types(arts):
    dedupe.mark(arts)
    return [a["dup_type"] for a in arts]


def test_same_press_same_title_is_recollection():
    a = [art(0, "hankyung", "한은 11월 금통위 인상 가능성 높다", "요약 가"), art(1, "hankyung", "한은 11월 금통위 인상 가능성 높다", "요약 가", 1)]
    assert types(a) == ["독립 보도", "재수집"] and a[1]["dup_of"] == "a0"


def test_wire_reprint_with_slightly_changed_title():
    a = [art(0, "yna", "미 연준 이어 ECB도 금리 동결…\"인플레·경기둔화 위험 여전\"", "ECB가 금리를 동결했다 예금금리 2.50%"),
         art(1, "heraldcorp", "연준 이어 ECB도 금리 동결…“인플레·경기둔화 위험 여전”", "유럽중앙은행이 기준금리를 묶었다", 2)]
    assert types(a)[1] == "통신사 전재" and a[1]["dup_of"] == "a0"


def test_retitled_copy_and_same_press_update():
    s = "5대 은행 가계대출이 한 달 만에 증가했고 정기예금에 24조원이 몰렸다"
    a = [art(0, "news1", "5대 은행 가계대출 한 달 만에 증가…정기예금엔 24조원 몰렸다", s),
         art(1, "chosunbiz", "5대銀 가계대출 한 달 만에 증가세… 정기예금은 24조원 늘어", s, 1)]
    assert types(a)[1] in ("제목 변경", "통신사 전재")
    b = [art(0, "mk", "한은 총재 국감 발언 금리 인상 기조 유지 필요", "요약"), art(1, "mk", "[업데이트] 한은 총재 국감 발언 금리 인상 기조 유지 필요 종합", "요약", 3)]
    assert types(b)[1] == "수정·업데이트"


def test_same_event_and_independent_are_kept():
    a = [art(0, "sedaily", "3분기 외환거래 일평균 1220억 달러 역대 최대", "서울경제 자체 취재 내용 A"),
         art(1, "ajunews", "3분기 일평균 외환거래 1220억달러 최대 증가폭 둔화", "전혀 다른 문장으로 쓴 분석 B", 1),
         art(2, "joongang", "신현송 총재 11월 인상 시사하나", "독립 취재 기사 C", 2)]
    t = types(a)
    assert t[1] in ("같은 사건", "독립 보도") and t[2] == "독립 보도"
    assert [x["id"] for x in dedupe.unique(a)] == ["a0", "a1", "a2"]      # 5·6은 지우지 않는다


def test_unique_drops_only_removed_types_and_respects_window():
    a = [art(0, "hankyung", "동일 제목 기사입니다 한은 금리", "s"), art(1, "hankyung", "동일 제목 기사입니다 한은 금리", "s", 1),
         art(2, "hankyung", "동일 제목 기사입니다 한은 금리", "s", 24 * 5)]       # 72시간 밖이면 별개
    dedupe.mark(a)
    assert [x["id"] for x in dedupe.unique(a)] == ["a0", "a2"]
