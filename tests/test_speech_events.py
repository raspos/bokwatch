"""한국은행 발언 통합: 같은 행사 묶기, 같은 날 다른 행사 분리, 인용 1개는 판단 유보, 이전 대비 변화."""
from bokwatch import speech_events as S


def sp(date, venue, tone, quote, speaker="신현송 총재"):
    return {"date": date, "venue": venue, "speaker": speaker, "tone": tone, "quote": quote, "link": "L", "verify": False}


def test_same_event_merged_and_different_venue_separated():
    sps = [sp("2026-10-22", "금통위 간담회", "hawk", "물가 상방 위험이 커서 긴축 기조를 이어간다"),
           sp("2026-10-22", "금통위 간담회", "neutral", "추가 데이터를 확인해도 늦지 않다"),
           sp("2026-10-22", "라디오 인터뷰", "hawk", "환율 안정이 중요하다")]
    ev = S.build(sps)["events"]
    assert len(ev) == 2
    by = {e["venue"]: e for e in ev}
    assert by["금통위 간담회"]["n_quotes"] == 2 and by["라디오 인터뷰"]["n_quotes"] == 1


def test_single_quote_is_withheld():
    e = S.build([sp("2026-10-12", "국회", "hawk", "금리 인상 기조를 유지한다")])["events"][0]
    assert e["verdict"].startswith("판단 유보") and e["confidence"] == "낮음"


def test_change_vs_previous_event_and_topics():
    sps = [sp("2026-10-12", "국회", "dove", "경기 부담을 보며 금리 인하 가능성을 열어 둔다"), sp("2026-10-12", "국회", "dove", "성장 둔화를 우려한다"),
           sp("2026-10-23", "국회", "hawk", "물가가 높아 긴축 기조를 이어간다"), sp("2026-10-23", "국회", "hawk", "환율 불확실성에 경계한다")]
    ev = {e["date"]: e for e in S.build(sps)["events"]}
    assert ev["2026-10-23"]["verdict"] == "매파" and ev["2026-10-23"]["change"]["label"] == "매파 강화"
    assert ev["2026-10-12"]["verdict"] == "비둘기파" and ev["2026-10-12"]["change"] is None       # 이전 행사 없음
    assert "물가" in ev["2026-10-23"]["topics"] and "환율" in ev["2026-10-23"]["topics"]
    assert "불확실성" in ev["2026-10-23"]["risk_terms"] and "긴축" in ev["2026-10-23"]["new_terms"]


def test_different_speakers_do_not_compare():
    sps = [sp("2026-10-10", "세미나", "dove", "성장을 우려한다 경기", "박종우 부총재보"), sp("2026-10-10", "세미나", "dove", "금리 인하", "박종우 부총재보"),
           sp("2026-10-20", "국회", "hawk", "긴축 기조 물가", "신현송 총재"), sp("2026-10-20", "국회", "hawk", "인상", "신현송 총재")]
    ev = {e["date"]: e for e in S.build(sps)["events"]}
    assert ev["2026-10-20"]["change"] is None          # 발언자가 달라 비교하지 않는다
