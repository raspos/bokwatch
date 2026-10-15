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


# 4. 의사록 공개 예정일 (규칙: 회의+14일 이후 첫 화요일. 2025-10~2026-08 실측 8건)
def test_minutes_release_rule():
    assert minutes_release_date(date(2026, 8, 27)) == date(2026, 9, 15)  # 실제 게시 9/15
    assert minutes_release_date(date(2026, 4, 10)) == date(2026, 4, 28)  # 금요일 회의, 실제 게시 4/28
    assert minutes_release_date(date(2026, 10, 22)) == date(2026, 11, 10)
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
    ok = "BOK워치: x\n- a\n- b\n- c\n- d\n- 91.5%"
    assert lint(ok) == []
    assert any("이는" in p for p in lint(ok + "\n- 이는 문제"))
    assert any("문단 수" in p for p in lint("h\n- a"))


# ---------------------------------------------------------------- 한은 홈페이지(2026-10-14 실제 구조)
from pathlib import Path

from bokwatch.fetch_bok import decision_summary, parse_meeting_year

FIX = Path(__file__).parent / "fixtures"


def test_parse_meeting_year_real_table():
    html = (FIX / "bok_meetings_2026.html").read_text(encoding="utf-8")
    got = parse_meeting_year(html, 2026, "https://www.bok.or.kr")
    assert set(got) == {"2026-08-27", "2026-10-22"}
    aug = got["2026-08-27"]["docs"]
    assert set(aug) == {"statement", "press", "minutes"}
    # 첨부는 PDF 먼저 (화면은 attachments[0]을 PDF로 연다)
    assert aug["minutes"]["attachments"][0]["name"] == "2026년도 제16차 금통위 의사록.pdf"
    assert aug["minutes"]["attachments"][0]["url"].startswith("https://www.bok.or.kr/portal/cmmn/file/fileDown.do")
    assert aug["statement"]["posted"] == "2026-08-27" and aug["minutes"]["posted"] is None
    assert "/view.do?" in aug["press"]["url"]
    assert got["2026-10-22"]["docs"] == {}  # 미래 회의: 자료 없음


def test_minutes_list_non_policy_meeting_not_linked():
    # 정책회의가 아닌 금통위(2026-07-23) 의사록이 7/16 정책회의에 붙으면 안 된다
    ms = [date(2026, 7, 16), date(2026, 8, 27)]
    t = "금융통화위원회 의사록(2026년 제14차)(2026.7.23)"
    assert meeting_for_post("minutes", t, date(2026, 8, 11), ms) is None
    t = "금융통화위원회 의사록(2026년 제13차)(2026.7.16)"
    assert meeting_for_post("minutes", t, date(2026, 8, 4), ms) == date(2026, 7, 16)


# 2026-08-27 의사록 원문 형식(PDF 추출 텍스트의 줄바꿈 공백 포함)
MIN_TEXT = """6. 회의경과
가. 의결안건
(3) 위원 토의내용
일부 위원은 향후 전망과 관련하여 반도체 경기와 중동상황에 대한 비관 시
나리오를 점검할 필요가 있다는 견해를 밝혔음.
(4) 한국은행 기준금리 결정에 관한 위원별 의견 개진
다수의 위원들은 국내외 금융·경제 상황을 종합적으로 고려할 때 기준금리를 인상하는 것이 바람
직하다는 견해를 나타낸 반면 일부 위원은 동결할 것을 주장하였음.
일부 위원은 금번 회의에서 현재 2.75%인 기준금리를 3.00%로 인상하는 것이
적절하다는 의견을 나타내었음.
세계 경제는 완만한 성장세를 이어갈 것으로 전망됩니다.
한편, 일부 위원은 금번 회의에서 현재 2.75%인 기준금리를 3.00%로 인상하
는 것이 적절하다는 의견을 나타내었음.
물가 상승압력이 이어지고 있습니다.
또 다른 일부 위원은 금번 회의에서 기준금리를 동결하여 2.75% 수준을 유지
하는 것이 적절하다는 의견을 표명하였음.
성장 측면의 불확실성이 큽니다.
(5) 토의결론
위와 같은 위원별 의견 개진 내용을 종합, 위원들은 다수결로 한국은행 기준
금리를 2.75%에서 3.00%로 0.25%p 인상하기로 결정하였음.
(6) 심의결과
(다만, 황건일 위원은 한국은행 기준금리를 0.25%p 인상하는 것에 대해 명백히
반대의사를 표시하고 현 수준에서 동결할 것을 주장하였음.)
"""


def test_minutes_member_section_real_format():
    paras = member_paragraphs(MIN_TEXT)
    assert len(paras) == 3  # '(3) 위원 토의내용'의 경제동향 발언과 '다수의 위원들은' 요약은 제외
    v = classify_views(paras, load_config()["tone"]["minutes_views"])
    assert [p["lean"] for p in v["paragraphs"]] == ["인상", "인상", "동결"]
    assert v["totals"] == {"인상": 2, "동결": 1, "인하": 0}


def test_decision_summary_dissent_names():
    s = decision_summary(MIN_TEXT)
    assert s == {"result": "다수결", "dissent": [{"name": "황건일", "view": "동결"}]}
    two = "(5) 토의결론 위원들은 다수결로 결정하였음. (다만, 주상영 위원과 신성환 위원은 한국은행 기준금리를 0.25%포인트 인상하 는 것에 대해 명백히 반대의사를 표시하고 현 수준에서 유지할 것을 주장하였음.)"
    assert [x["name"] for x in decision_summary(two)["dissent"]] == ["주상영", "신성환"]


def test_load_dotenv_does_not_override(monkeypatch):
    import os
    from bokwatch.common import load_dotenv
    f = FIX / "_dotenv_test.env"  # 시스템 임시 폴더 권한 문제를 피해 테스트 폴더에 만든다
    f.write_text('# 주석\nBW_A=abc\nexport BW_B="x y"\nBW_C=\nBW_D=from_file\n', encoding="utf-8")
    try:
        for k in ("BW_A", "BW_B", "BW_C"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("BW_D", "from_env")
        load_dotenv(f)
        assert os.environ["BW_A"] == "abc" and os.environ["BW_B"] == "x y"
        assert "BW_C" not in os.environ and os.environ["BW_D"] == "from_env"
    finally:
        f.unlink()
        for k in ("BW_A", "BW_B"):
            os.environ.pop(k, None)


def test_ecos_error_hides_key(monkeypatch):
    import pytest
    import requests
    from bokwatch import fetch_rates

    def boom(url, timeout):
        raise requests.ConnectionError(f"failed: {url}")
    monkeypatch.setattr(fetch_rates.requests, "get", boom)
    monkeypatch.setattr(fetch_rates.time, "sleep", lambda s: None)
    cfg = {"ecos": {"base_url": "https://ecos.bok.or.kr/api", "key_env": "X"}}
    with pytest.raises(fetch_rates.EcosError) as ei:
        fetch_rates.ecos_get(cfg, "StatisticItemList", ["817Y002"], key="SECRETKEY123")
    assert "SECRETKEY123" not in str(ei.value) and "***" in str(ei.value)


def test_prob_log_fixed_daily_record(monkeypatch):
    import build
    f = FIX / "_prob_log_test.csv"
    monkeypatch.setattr(build, "PROB_LOG", f)
    cur = {"asof": "2026-10-13", "inputs": [{"used": True, "label": "CD 91일", "spread": 0.18}],
           "scenarios": {"0": {"meetings": [
               {"date": "2026-10-22", "in_range": True, "p_hike": 0.0, "p_hold": 1.0, "p_cut": 0.0, "expected": 3.0},
               {"date": "2026-11-26", "in_range": True, "p_hike": 0.455, "p_hold": 0.545, "p_cut": 0.0, "expected": 3.114}]}}}
    try:
        rows = build.update_prob_log(cur, date(2026, 10, 14), None, write=True)
        assert [(r["date"], r["meeting"], float(r["p_hike"])) for r in rows] == [
            ("2026-10-14", "2026-10-22", 0.0), ("2026-10-14", "2026-11-26", 0.455)]
        # 같은 날 다시 돌리면 그날 줄만 바뀐다. 중단이면 수치 없이 사유만 남긴다
        rows = build.update_prob_log(cur, date(2026, 10, 14), "만기가 확정 일정 밖", write=True)
        assert len(rows) == 1 and rows[0]["status"] == "중단" and rows[0]["p_hike"] == ""
        # 다음 날 기록이 앞날 기록을 지우지 않는다. write=False면 읽기만
        build.update_prob_log(cur, date(2026, 10, 15), None, write=True)
        rows = build.update_prob_log(None, date(2026, 10, 16), None, write=False)
        assert sorted({r["date"] for r in rows}) == ["2026-10-14", "2026-10-15"]
    finally:
        f.unlink(missing_ok=True)


def test_krx_futures_parse_real_rows():
    from bokwatch.fetch_futures import parse_items
    # 2026-10-13 KRX Open API fut_bydd_trd 응답 일부(필드 그대로)
    items = [
        {"BAS_DD": "20261013", "PROD_NM": "3개월무위험금리 선물", "ISU_CD": "A696B000", "ISU_NM": "3개월무위험금리 F 202611",
         "TDD_CLSPRC": "", "SETL_PRC": "96.88", "ACC_TRDVOL": "0", "ACC_OPNINT_QTY": "90"},
        {"BAS_DD": "20261013", "PROD_NM": "3개월무위험금리 선물", "ISU_CD": "A6971000", "ISU_NM": "3개월무위험금리 F 202701",
         "TDD_CLSPRC": "96.815", "SETL_PRC": "96.815", "ACC_TRDVOL": "10", "ACC_OPNINT_QTY": "70"},
        {"BAS_DD": "20261013", "PROD_NM": "3개월무위험금리 선물", "ISU_CD": "D696A6BS", "ISU_NM": "3개월무위험금리 SP 2610-2611",
         "TDD_CLSPRC": "", "SETL_PRC": "", "ACC_TRDVOL": "0", "ACC_OPNINT_QTY": ""},
        {"BAS_DD": "20261013", "PROD_NM": "3년국채 선물", "ISU_CD": "A1661000", "ISU_NM": "3년국채 F 202612",
         "TDD_CLSPRC": "105.1", "SETL_PRC": "105.1", "ACC_TRDVOL": "100", "ACC_OPNINT_QTY": "1"},
    ]
    rows = parse_items(items, "2026-10-13")
    assert [(r["month"], r["settle"], r["volume"], r["oi"]) for r in rows] == [("2026-11", 96.88, 0, 90), ("2027-01", 96.815, 10, 70)]


def test_qual_mix_weights():
    import build
    cur = {"scenarios": {"0": {"meetings": [{"date": "2026-11-26", "in_range": True, "p_hike": 0.4, "p_hold": 0.6, "p_cut": 0.0}]}}}
    qual = {"probs": {"meeting": "2026-11-26", "p_hike": 0.8, "p_hold": 0.2, "p_cut": 0.0, "reason": "r"}}
    q = build.qual_mix(cur, qual)
    assert q["w10"]["p_hike"] == 0.44 and q["w20"]["p_hike"] == 0.48
    # CD 값이 없는 회의면 정성 확률만 남기고 혼합은 내지 않는다
    assert "w10" not in build.qual_mix({"scenarios": {"0": {"meetings": []}}}, qual)


def test_status_messages_redact_keys(monkeypatch):
    from bokwatch import common
    monkeypatch.setenv("NAVER_CLIENT_ID", "abcd1234xy")
    msg = ("'신현송': ValueError: Invalid header value b'abcd1234xy\n'; "
           "Incorrect API key provided: sk-proj-****abcdEFGH1234; serviceKey=AbCdEf123456%3D%3D; id abcd1234xy")
    out = common.redact(msg)
    assert "abcd1234xy" not in out and "abcdEFGH1234" not in out and "AbCdEf123456" not in out


def test_ecos_retries_timeouts_then_succeeds(monkeypatch):
    import requests
    from bokwatch import fetch_rates
    calls = []

    class R:
        def raise_for_status(self): pass
        def json(self): return {"StatisticSearch": {"row": [{"TIME": "20261013", "DATA_VALUE": "3.24"}]}}

    def flaky(url, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectTimeout("timeout")
        return R()
    monkeypatch.setattr(fetch_rates.requests, "get", flaky)
    monkeypatch.setattr(fetch_rates.time, "sleep", lambda s: None)
    cfg = {"ecos": {"base_url": "https://ecos.bok.or.kr/api", "key_env": "X"}}
    rows = fetch_rates.ecos_get(cfg, "StatisticSearch", ["817Y002"], key="K")
    assert len(calls) == 3 and rows[0]["DATA_VALUE"] == "3.24"


def test_cd_short_solve_and_parse():
    from datetime import date
    from bokwatch import cd_short
    from bokwatch.fetch_cdcurve import parse_day
    # 10/14 공시: 1개월 3.13%, 스프레드 6bp, 기준 3.00%, 회의 10/22 → 결제 10/15부터 30일: 회의 전 7일·뒤 23일
    r = cd_short.solve(date(2026, 10, 14), 3.00, 3.13, 0.06, 30, [date(2026, 10, 22), date(2026, 11, 26)])
    assert (r["pre_days"], r["post_days"]) == (7, 23)
    assert abs(r["expected"] - (3.00 + 30 * 0.07 / 23)) < 1e-4
    assert abs(r["p_hike"] - (30 * 0.07 / 23) / 0.25) < 1e-3 and r["p_cut"] == 0
    # 만기 안 회의가 없거나 둘이면 풀지 않는다
    assert cd_short.solve(date(2026, 10, 23), 3.00, 3.05, 0.05, 15, [date(2026, 10, 22), date(2026, 11, 26)]) is None
    xml = ("<BISComDspDatDTO><val1>AAA</val1><val2>전일</val2><val3>5사 평균</val3><val4>1</val4><val5>1</val5><val6>1</val6>"
           "<val7>1</val7><val8>1</val8><val9>1</val9></BISComDspDatDTO><BISComDspDatDTO><val1>AAA</val1><val2>당일</val2>"
           "<val3>5사 평균</val3><val4>3.07</val4><val5>3.10</val5><val6>3.13</val6><val7>3.25</val7><val8>3.67</val8>"
           "<val9>3.70</val9></BISComDspDatDTO>")
    row = parse_day(xml, "2026-10-14")
    assert row["m1"] == 3.13 and row["d7"] == 3.07 and row["y1"] == 3.70
    assert parse_day(xml.replace("당일", "x"), "2026-10-14") is None


def test_kofr_ois_compounding_and_next_meeting():
    from datetime import date
    from bokwatch import kofr_ois
    k = kofr_ois.Kofr({"2026-01-01": 3.0, "2026-01-02": 3.0})
    # 휴일은 직전 금리(3.0%)가 이어진다: 10일 일복리 = ((1+0.03/365)^10 − 1) × 365/10
    assert abs(k.comp(date(2026, 1, 1), 2) - ((1 + 0.03 / 365) ** 2 - 1) * 365 / 2 * 100) < 1e-9
    assert k.comp(date(2025, 12, 31), 2) is None
    row = {"m1": {"cd_date": "2026-10-14", "tenor_days": 30, "ois": 3.0762}}
    n = kofr_ois.next_meeting(row, 3.00, 0.033, [date(2026, 10, 22), date(2026, 11, 26)])
    # 30×3.0762 = 7×3.033 + 23×(E+0.033) → E = 3.0563
    assert (n["pre_days"], n["post_days"]) == (7, 23)
    assert abs(n["expected"] - ((30 * 3.0762 - 7 * 3.033) / 23 - 0.033)) < 1e-4
    assert abs(n["p_hike"] - (n["expected"] - 3.0) / 0.25) < 1e-3


def test_kofr_ois_bootstrap_second_meeting():
    from datetime import date
    from bokwatch import kofr_ois
    c = {"m1": {"cd_date": "2026-10-14", "tenor_days": 30, "ois": 3.0762},
         "m3": {"cd_date": "2026-10-14", "tenor_days": 91, "ois": 3.1284}}
    ms = [date(2026, 10, 22), date(2026, 11, 26), date(2027, 1, 11)]
    path = kofr_ois.solve_path(c, 3.00, 0.033, ms)
    assert [x["meeting"] for x in path] == ["2026-10-22", "2026-11-26"]
    e1, e2 = path[0]["expected"], path[1]["expected"]
    # 91×OIS = 7×(r0+k) + 35×(E1+k) + (46+3)×(E2+k), 1/11 회의(뒤 3일)는 변화 없음
    assert abs(91 * 3.1284 - (7 * 3.033 + 35 * (e1 + 0.033) + 49 * (e2 + 0.033))) < 0.01
    assert path[1]["tail_assumed"] == ["2027-01-11"]
    assert abs(path[1]["delta_bp"] - (e2 - e1) * 100) < 0.01
