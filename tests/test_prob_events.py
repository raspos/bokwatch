"""확률 변화가 큰 날 탐지: 임계값, 정렬, 동시 이벤트 창(그 날·전날), 원인 단정 문구."""
from pathlib import Path

from bokwatch import prob_events as P


def series(vals):
    days = {f"2026-10-{20 + i}": {"m5": {"hike": v, "hold": 1 - v, "cut": 0.0}, "kind": "retro"} for i, v in enumerate(vals)}
    return {"meetings": {"2026-11-26": days}}


EV = [{"date": "2026-10-22", "time": "21:30", "label": "미국 PCE", "country": "US", "kind": "pce", "importance": 3},
      {"date": "2026-10-23", "label": "별 영향 없는 일정", "country": "KR", "importance": 1},
      {"date": "2026-10-30", "label": "먼 날 이벤트", "country": "KR", "importance": 3}]


def test_only_moves_at_or_above_threshold_sorted_by_size():
    r = P.build(series([0.50, 0.52, 0.60, 0.59, 0.40]), "2026-11-26", EV, [], [], Path("없음.csv"))
    assert [x["date"] for x in r["rows"]] == ["2026-10-24", "2026-10-22"]           # -19%p, +8%p. 2%p·1%p 변화는 제외
    assert r["rows"][0]["delta"] < 0 and abs(r["rows"][0]["delta"]) > abs(r["rows"][1]["delta"])


def test_related_events_window_is_same_day_and_previous_day_with_min_importance():
    r = P.build(series([0.50, 0.60]), "2026-11-26", EV, [], [], Path("없음.csv"))
    labels = [e["label"] for e in r["rows"][0]["events"]]                           # 10/21 기준일: 그 날·전날(10/20~21) 이벤트
    assert labels == []
    r2 = P.build(series([0.50, 0.50, 0.60]), "2026-11-26", EV, [], [], Path("없음.csv"))
    assert [e["label"] for e in r2["rows"][0]["events"]] == ["미국 PCE"]            # 10/22 변화: 10/21·10/22 중 10/22 PCE만(중요도 1 일정·먼 날짜 제외)
    assert r2["rows"][0]["date"] == "2026-10-22"


def test_note_does_not_claim_causation_and_missing_series_is_empty():
    r = P.build(series([0.5, 0.7]), "2026-11-26", EV, [], [], Path("없음.csv"))
    assert "원인" in r["note"] and "확인되지 않았다" in r["note"]
    assert P.build({"meetings": {}}, "2026-11-26", EV, [], [], Path("없음.csv"))["rows"] == []


def test_lines_are_short_summaries_and_empty_when_no_event():
    ev = [{"date": "2026-10-22", "kind": "bok", "label": "금통위 통화정책방향 결정", "importance": 3},
          {"date": "2026-10-22", "kind": "gdp", "label": "한국 3분기 GDP 속보치 전기비 +1.0%(8월 한은 전망 0.3%)", "importance": 3}]
    sp = [{"date": "2026-10-22", "venue": "금통위 간담회", "verdict": "매파"}]
    r = P.build(series([0.50, 0.50, 0.60, 0.60, 0.40]), "2026-11-26", ev, sp, [], Path("없음.csv"), meetings=[{"date": "2026-10-22", "rate": 3.0, "decision": "동결"}])
    by = {x["date"]: x["lines"] for x in r["rows"]}
    assert by["2026-10-22"] == ["금통위 결정: 기준금리 3.00% 동결", "한국 3분기 GDP 속보치 전기비 +1.0%", "총재 금통위 간담회 발언(매파)"]
    assert by["2026-10-24"] == []                       # 그 날·전날에 이벤트가 없으면 화면에서 '이벤트 없음'


def test_days_without_events_fall_back_to_forecasts_then_rates(tmp_path):
    rates = tmp_path / "rates.csv"
    rates.write_text("""date,id,value,source
2026-10-21,cd91,3.25,x
2026-10-22,cd91,3.26,x
2026-10-21,ktb3y,3.88,x
2026-10-22,ktb3y,3.84,x
2026-10-21,kofr,3.05,x
2026-10-22,kofr,3.05,x
""", encoding="utf-8")
    reps = [{"institution": "A", "published": "2026-10-22", "calls": {"2026-11-26": {"call": "인상"}}},
            {"institution": "B", "published": "2026-10-21", "calls": {"2026-11-26": {"call": "동결"}}}]
    r = P.build(series([0.50, 0.50, 0.60]), "2026-11-26", [], [], [], rates, reports=reps)
    assert r["rows"][0]["lines"] == ["기관 전망 2곳 발표(11/26 인상 1·동결 1)", "시장금리: 국고채 3년 -4.0bp · CD 91일 +1.0bp"]
    r2 = P.build(series([0.50, 0.50, 0.60]), "2026-11-26", [], [], [], Path("없음.csv"))
    assert r2["rows"][0]["lines"] == []                  # 전망·금리 자료도 없으면 비어 있다(화면에서 '이벤트 없음')
