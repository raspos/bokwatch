from datetime import date, datetime

from bokwatch.common import KST, load_config
from bokwatch.fetch_bok import (classify_views, meeting_for_post, member_paragraphs,
                                minutes_release_date, parse_board)
from bokwatch.fetch_news import match_keywords, merge, parse_feed
from bokwatch.fetch_rates import match_items, value_on
from bokwatch.guidance import dotplot_summary, statement_diff, tone_score
from bokwatch.memo import lint

AUG = {3.00: 5, 3.25: 10, 3.50: 6}


# 3. 점도표
def test_dotplot_august():
    s = dotplot_summary(AUG, 3.00)
    assert s["median"] == 3.25 and s["above"] == 16 and s["below"] == 0 and s["n"] == 21


def test_dotplot_may():
    s = dotplot_summary({2.50: 2, 2.75: 7, 3.00: 10, 3.25: 2}, 2.50)
    assert s["median"] == 3.00 and s["at"] == 2 and s["above"] == 19


# 4. 의사록 공개 예정일 (규칙: 회의+12일 이후 첫 화요일)
def test_minutes_release_rule():
    assert minutes_release_date(date(2026, 8, 27)) == date(2026, 9, 8)
    assert minutes_release_date(date(2026, 10, 22)) == date(2026, 11, 3)
    # 한은 공지가 있으면 공지 우선
    assert minutes_release_date(date(2026, 8, 27), 12, {"2026-08-27": "2026-09-09"}) == date(2026, 9, 9)


def test_value_on_uses_previous_business_day():
    ser = {"2026-10-09": 3.20}
    assert value_on(ser, date(2026, 10, 12)) == (3.20, "2026-10-09")


def test_ecos_item_match():
    rows = [{"ITEM_CODE": "A1", "ITEM_NAME": "CD(91일)"}, {"ITEM_CODE": "B2", "ITEM_NAME": "국고채(3년)"},
            {"ITEM_CODE": "B3", "ITEM_NAME": "국고채(30년)"}]
    out = match_items(rows, [{"id": "cd91", "match": "CD(91일)"}, {"id": "ktb3y", "match": "국고채(3년)"}])
    assert out == {"cd91": ("A1", "CD(91일)"), "ktb3y": ("B2", "국고채(3년)")}


BOARD = """<ul class="bdLine"><li><a class="title" href="/portal/bbs/B0000245/view.do?nttId=1&menuNo=200761">
2026년 제17차 금융통화위원회(정기) 의사록</a><span class="date">2026.09.08</span></li>
<li><a href="/portal/bbs/B0000245/view.do?nttId=2&menuNo=200761">통화정책방향(2026.8.27)</a><span>2026.08.27</span></li></ul>"""


def test_parse_board_and_link_meeting():
    posts = parse_board(BOARD, "https://www.bok.or.kr")
    assert posts[0]["posted"] == "2026-09-08" and posts[0]["url"].startswith("https://www.bok.or.kr/portal/bbs/")
    ms = [date(2026, 7, 16), date(2026, 8, 27)]
    assert meeting_for_post("minutes", posts[0]["title"], date(2026, 9, 8), ms) == date(2026, 8, 27)
    assert meeting_for_post("statement", posts[1]["title"], date(2026, 8, 27), ms) == date(2026, 8, 27)


def test_minutes_member_views():
    text = ("1. 경제상황\n...\n정책결정\n일부 위원은 물가 상승압력이 커 기준금리를 0.25%p 인상할 필요가 있다는 견해를 밝혔다 이어서 설명\n"
            "다른 일부 위원은 성장 하방 위험을 고려해 현 수준에서 유지하는 것이 바람직하다는 의견을 나타내었다 추가 설명\n")
    paras = member_paragraphs(text)
    assert len(paras) == 2
    v = classify_views(paras, load_config()["tone"]["minutes_views"])
    assert [p["lean"] for p in v["paragraphs"]] == ["인상", "동결"]


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>
<item><title>신현송 "물가 상당 기간 2% 상회"</title><link>https://www.yna.co.kr/view/AKR1</link>
<pubDate>Mon, 12 Oct 2026 06:30:00 +0000</pubDate><description>&lt;b&gt;한은 총재&lt;/b&gt; 국회 발언</description></item>
<item><title>코스피 마감</title><link>https://www.yna.co.kr/view/AKR2</link><pubDate>Mon, 12 Oct 2026 07:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_rss_parse_filter_merge():
    items = parse_feed(RSS, "연합뉴스 경제")
    assert items[0]["published"] == "2026-10-12T15:30+09:00"
    assert "<b>" not in items[0]["summary"]
    kws = match_keywords(items[0], "신현송", ["한은 총재", "금통위"])
    assert kws == ["신현송", "한은 총재"]
    assert match_keywords(items[1], "신현송", ["금통위"]) == []
    a = dict(items[0], keywords=kws)
    now = datetime(2026, 10, 14, 12, tzinfo=KST)
    merged = merge([a], [dict(a, feed="연합뉴스 전체")], 90, now)
    assert len(merged) == 1                       # 링크 기준 중복 제거
    assert merge(merged, [], 1, now) == []         # 보관 기간 밖 삭제
    assert set(a) >= {"id", "title", "published", "link", "keywords", "feed", "summary"}


def test_statement_diff_aug():
    d = statement_diff("금리인상 기조를 이어나갈 필요.", "추가 기준금리 인상의 시기와 속도를 결정해 나갈 것.")
    assert {"op": "del", "text": "금리인상 기조를 이어나갈 필요."} in d
    assert {"op": "add", "text": "추가 기준금리 인상의 시기와 속도를 결정해 나갈 것."} in d


def test_tone_no_double_count():
    lex = {"hawkish": {"인상": 2, "추가 인상": 2}, "dovish": {"인하": 2}}
    assert tone_score(["추가 인상을 검토."], lex)["hawk"] == 2


def test_memo_lint():
    ok = "18시/E▶x\n- a\n- b\n- c\n- d\n- 91.5%"
    assert lint(ok) == []
    assert any("이는" in p for p in lint(ok + "\n- 이는 문제"))
    assert any("문단 수" in p for p in lint("h\n- a"))
