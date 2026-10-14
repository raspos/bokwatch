import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from bokwatch import ai_judge
from bokwatch.common import KST
from bokwatch.fetch_events import parse_bls_ics, parse_bls_schedule, parse_fomc, parse_fred_csv, yoy_from_series
from bokwatch.fetch_naver import merge as nmerge, parse_items

BLS = """<table class="release-list"><tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
<tr><td>September 2026</td><td>Oct. 15, 2026</td><td>08:30 AM</td></tr>
<tr><td>October 2026</td><td>Nov. 12, 2026</td><td>08:30 AM</td></tr></table>"""


def test_bls_schedule_dst_to_kst():
    rows = parse_bls_schedule(BLS)
    assert rows[0]["ref_month"] == "2026-09"
    # 10월 15일 08:30 EDT = 21:30 KST, 11월 12일 08:30 EST = 22:30 KST
    assert rows[0]["release"].strftime("%Y-%m-%d %H:%M") == "2026-10-15 21:30"
    assert rows[1]["release"].strftime("%Y-%m-%d %H:%M") == "2026-11-12 22:30"


FOMC = """<div class="panel"><div class="panel-heading"><h4>2026 FOMC Meetings</h4></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>Oct/Nov</strong></div><div class="fomc-meeting__date">31-1</div></div>
<div class="row fomc-meeting"><div class="fomc-meeting__month"><strong>December</strong></div><div class="fomc-meeting__date">15-16*</div></div>
</div>"""


def test_fomc_parse():
    rows = parse_fomc(FOMC)
    assert rows[0]["end"] == date(2026, 11, 1) and rows[0]["start"] == date(2026, 10, 31)
    assert rows[1]["sep"] is True
    assert rows[1]["decision"].strftime("%Y-%m-%d %H:%M") == "2026-12-17 04:00"  # 14:00 EST → 다음날 04:00 KST


def test_yoy():
    pts = parse_fred_csv("observation_date,CPIAUCNS\n2025-08-01,100.0\n2025-09-01,100.5\n2026-08-01,103.0\n2026-09-01,103.0\n")
    y = yoy_from_series(pts)
    assert y["month"] == "2026-09" and y["yoy"] == 2.5 and y["prev_yoy"] == 3.0  # 2.4875… → 2.5


NAVER = {"items": [
    {"title": "<b>신현송</b> &quot;물가 2% 상회&quot;", "originallink": "https://www.hankyung.com/a/1",
     "link": "https://n.news.naver.com/mnews/article/015/1", "description": "한은 <b>총재</b>는…", "pubDate": "Tue, 13 Oct 2026 10:00:00 +0900"},
    {"title": "[속보] 신현송 \"물가 2% 상회\"", "originallink": "https://www.mk.co.kr/b/2",
     "link": "https://www.mk.co.kr/b/2", "description": "", "pubDate": "Tue, 13 Oct 2026 10:05:00 +0900"},
]}


def test_naver_parse_and_dedupe():
    items = parse_items(NAVER, "신현송")
    assert items[0]["title"] == '신현송 "물가 2% 상회"' and items[0]["press"] == "hankyung.com"
    assert items[0]["published"] == "2026-10-13T10:00+09:00"
    m = nmerge([], items, 30, datetime(2026, 10, 14, tzinfo=KST))
    assert len(m) == 1 and m[0]["dup_press"] == ["mk.co.kr"]   # 같은 제목 → 하나로


# ---------------------------------------------------------------- AI: 가짜 클라이언트
class FakeClient:
    """openai.OpenAI().chat.completions.create 흉내."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        msg = SimpleNamespace(content=None if r.get("refusal") else json.dumps(r["json"], ensure_ascii=False),
                              refusal=r.get("refusal"))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=r.get("finish", "stop"))])


CFG = {"model": "test-model", "classify_effort": "low", "synth_effort": "medium", "batch_size": 2,
       "max_new_per_run": 10, "window_hours": 72, "factors": ["물가", "환율", "성장·경기", "기타"]}
NOW = datetime(2026, 10, 14, 18, tzinfo=KST)
ARTS = [{"id": f"a{i}", "title": f"t{i}", "summary": "", "press": "p", "link": f"L{i}",
         "published": (NOW - timedelta(hours=i)).isoformat(timespec="minutes")} for i in range(3)]


def test_classify_batches_cache_and_request_shape():
    fc = FakeClient([
        {"json": {"items": [{"id": "a0", "relevant": True, "factor": "물가", "direction": "인상 압력", "strength": 3, "reason": "r"},
                            {"id": "a1", "relevant": True, "factor": "성장·경기", "direction": "인하 압력", "strength": 1, "reason": "r"},
                            {"id": "zzz", "relevant": True, "factor": "기타", "direction": "중립", "strength": 1, "reason": "가짜"}]}},
        {"json": {"items": [{"id": "a2", "relevant": False, "factor": "기타", "direction": "중립", "strength": 1, "reason": "r"}]}},
    ])
    tags = {}
    n, errs = ai_judge.classify(fc, CFG, ARTS, tags)
    assert n == 3 and errs == [] and "zzz" not in tags          # 입력에 없는 id는 버림
    kw = fc.calls[0]
    assert kw["model"] == "test-model" and kw["reasoning_effort"] == "low"
    rf = kw["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert kw["messages"][0]["role"] == "system" and "<articles>" in kw["messages"][1]["content"]
    # 캐시된 기사는 다시 부르지 않는다
    n2, _ = ai_judge.classify(FakeClient([]), CFG, ARTS, tags)
    assert n2 == 0
    idx = ai_judge.pressure_index(ARTS, tags, NOW - timedelta(hours=72))
    assert idx["n"] == 2 and idx["index"] == pytest.approx((3 - 1) / 4)


def test_synth_drops_unknown_ids_and_refusal(monkeypatch):
    monkeypatch.setattr(ai_judge, "context_block", lambda: {})
    tags = {"a0": {"relevant": True, "factor": "물가", "direction": "인상 압력", "strength": 3, "reason": "r"}}
    out = {"lean": 1, "headline": "h", "summary": "s", "counterpoints": [], "market_gap": "", "watch": [], "confidence": "보통",
           "drivers": [{"factor": "물가", "direction": "인상 압력", "point": "p", "article_ids": ["a0", "없는id"]}]}
    res = ai_judge.synthesize(FakeClient([{"json": out}]), CFG, ARTS, tags, NOW - timedelta(hours=72))
    assert res["drivers"][0]["article_ids"] == ["a0"]
    with pytest.raises(ai_judge.AIError):
        ai_judge.synthesize(FakeClient([{"refusal": "거절"}]), CFG, ARTS, tags, NOW - timedelta(hours=72))
    with pytest.raises(ai_judge.AIError):
        ai_judge.synthesize(FakeClient([{"json": {}, "finish": "length"}]), CFG, ARTS, tags, NOW - timedelta(hours=72))
    # effort 미지정(비추론 모델)이면 reasoning_effort를 보내지 않는다
    fc = FakeClient([{"json": out}])
    ai_judge.synthesize(fc, {**CFG, "synth_effort": None}, ARTS, tags, NOW - timedelta(hours=72))
    assert "reasoning_effort" not in fc.calls[0]


def test_memo_with_events_and_ai():
    from bokwatch.common import SITE_DATA, read_json
    from bokwatch.memo import build_memo
    meta = read_json(SITE_DATA / "meta.json")
    cur = read_json(SITE_DATA / "snapshots" / f"{meta['latest']}.json")
    events = {"upcoming": [{"date": "2026-10-15", "time": "21:30", "label": "미국 CPI(9월분)", "kind": "cpi", "importance": 3}],
              "indicators": {"us_cpi": {"label": "미국 CPI", "month": "2026-08", "yoy": 2.9, "prev_yoy": 2.7}}}
    qual = {"window_hours": 72, "pressure": {"index": 0.31, "n": 24}, "synthesis_updated": "2026-10-14T17:00+09:00",
            "synthesis": {"headline": "환율·물가 쪽 인상 압력 우세", "summary": "총재 국회 발언이 매파로 읽힌 것으로 풀이된다.",
                          "market_gap": "", "drivers": []}}
    m = build_memo(datetime(2026, 10, 14, 18, tzinfo=KST), cur, None, None, read_json(SITE_DATA / "guidance.json"),
                   read_json(SITE_DATA / "minutes.json"), read_json(SITE_DATA / "reports.json"), events, qual)
    assert m["lint"] == [], m["text"]
    assert "정성 판단(AI 자동 산출, 참고용)" in m["text"] and "10/15 21:30 미국 CPI" not in m["text"]
    assert "10월 15일 21:30 미국 CPI(9월분)" in m["text"] and "미국 CPI 8월 2.9%(전월 2.7%)" in m["text"]


def test_yoy_single_rounding_real_values():
    # FRED CPILFENS 2025-08 329.970 → 2026-08 338.041 = 2.44598% → BLS 공표 방식 2.4% (2.45 경유 2.5 아님)
    pts = [("2025-08", 329.970), ("2026-08", 338.041)]
    assert yoy_from_series(pts)["yoy"] == 2.4


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:a
DTSTART;TZID=US-Eastern:20261014T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART;TZID=US-Eastern:20261110T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
UID:c
DTSTART;TZID=US-Eastern:20261014T083000
SUMMARY:Real Earnings
END:VEVENT
END:VCALENDAR
"""


def test_bls_ics_today_release_kst():
    rows = parse_bls_ics(ICS, "Consumer Price Index")
    assert [x["release"].strftime("%Y-%m-%d %H:%M") for x in rows] == ["2026-10-14 21:30", "2026-11-10 22:30"]


def test_same_event_counted_once():
    # 같은 발언을 다섯 매체가 보도(인상 압력)한 사건 1개 vs 인하 압력 단독 기사 1개
    arts = [{"id": f"s{i}", "title": f"신현송 K자형 뚜렷 물가 낮춰야 {i}", "published": "2026-10-14T15:00+09:00"} for i in range(5)]
    arts.append({"id": "d0", "title": "수출 둔화 우려 확대", "published": "2026-10-14T15:00+09:00"})
    tags = {a["id"]: {"relevant": True, "factor": "한은 커뮤니케이션", "direction": "인상 압력", "strength": 2, "reason": "r"} for a in arts[:5]}
    tags["d0"] = {"relevant": True, "factor": "성장·경기", "direction": "인하 압력", "strength": 2, "reason": "r"}
    since = NOW - timedelta(hours=72)
    per_article = ai_judge.pressure_index(arts, tags, since)          # 기사 단위: 5 대 1
    groups = ai_judge.group_by_title(arts)
    assert sorted(len(g["ids"]) for g in groups) == [1, 5]
    per_event = ai_judge.pressure_index(arts, tags, since, groups)    # 사건 단위: 가중 2 대 1
    assert per_article["index"] == pytest.approx(4 / 6, abs=1e-3)
    assert per_event["n"] == 2 and per_event["n_articles"] == 6
    assert per_event["index"] == pytest.approx((2 * 2 - 2 * 1) / (2 * 2 + 2 * 1), abs=1e-3)  # 보도 5건 → 가중 최대 2배


def test_ai_catchall_and_topic_groups_are_split():
    arts = [{"id": f"a{i}", "title": f"t{i}", "published": "2026-10-14T10:00+09:00"} for i in range(4)]

    class C:
        chat = None
    fake = FakeClient([{"json": {"groups": [{"label": "개별 기타 기사", "ids": ["a0", "a1"]},
                                            {"label": "총재 CNN 패널 10/14", "ids": ["a2", "a3"]}]}}])
    groups, err = ai_judge.group_events(fake, CFG, arts)
    assert err is None
    assert sorted(len(g["ids"]) for g in groups) == [1, 1, 2]


def test_bls_api_parse_skips_missing():
    from bokwatch.fetch_events import parse_bls_api
    j = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "CUUR0000SA0", "data": [
        {"year": "2026", "period": "M09", "value": "336.940"}, {"year": "2025", "period": "M10", "value": "-"},
        {"year": "2025", "period": "M09", "value": "324.800"}, {"year": "2025", "period": "M13", "value": "1"}]}]}}
    pts = parse_bls_api(j)["CUUR0000SA0"]
    assert pts == [("2025-09", 324.8), ("2026-09", 336.94)]
    assert yoy_from_series(pts)["yoy"] == 3.7
