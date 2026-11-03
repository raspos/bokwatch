"""기관 전망 평가: 시점 통일, 미제출은 동결이 아님, 수정 이력, 표본이 작으면 순위 없음."""
from bokwatch import forecast_eval as F

REPORTS = [
    {"institution": "A증권", "published": "2026-09-20", "calls": {"2026-10-22": {"call": "인상"}}},
    {"institution": "A증권", "published": "2026-10-16", "calls": {"2026-10-22": {"call": "동결"}}},     # 수정
    {"institution": "B증권", "published": "2026-10-21", "calls": {"2026-10-22": {"call": "동결"}}},
    {"institution": "C증권", "published": "2026-10-23", "calls": {"2026-10-22": {"call": "동결"}}},     # 회의 뒤 발표 → 쓰지 않음
]
SERIES = {"meetings": {"2026-10-22": {"2026-10-14": {"m5": {"hike": 0.3, "hold": 0.7, "cut": 0.0}, "kind": "retro"},
                                      "2026-10-21": {"m5": {"hike": 0.2, "hold": 0.8, "cut": 0.0}, "kind": "retro"}}}}


def test_only_forecasts_available_at_horizon_are_used_and_no_default_hold():
    r = F.evaluate(REPORTS, {"2026-10-22": "hold"}, SERIES)
    t = {x["horizon"]: x for x in r["table"]}
    assert t[30]["n_institutions"] == 1 and t[30]["hits"] == 0           # 30일 전(9/22)에는 A의 인상 전망만 있었다
    assert t[7]["n_institutions"] == 1 and t[7]["hits"] == 0             # 10/15: A는 아직 인상 전망(10/16 수정 전)
    assert t[1]["n_institutions"] == 2 and t[1]["hits"] == 2             # 10/21: A(동결, 수정 후)·B. C는 회의 뒤라 제외


def test_revisions_and_ranking_gate():
    r = F.evaluate(REPORTS, {"2026-10-22": "hold"}, SERIES)
    assert r["revisions"] == [{"institution": "A증권", "meeting": "2026-10-22", "from": "인상", "to": "동결", "date": "2026-10-16"}]
    assert r["ranking"] is None and r["meetings_evaluated"] == 1          # 표본 부족: 순위 없음


def test_bokwatch_uses_latest_record_on_or_before_cutoff_and_marks_kind():
    r = F.evaluate(REPORTS, {"2026-10-22": "hold"}, SERIES)
    t = {x["horizon"]: x for x in r["table"]}
    assert t[1]["bokwatch"]["asof"] == "2026-10-21" and t[1]["bokwatch"]["hit"] and t[1]["bokwatch"]["kind"] == "retro"
    assert t[7]["bokwatch"]["asof"] == "2026-10-14"                      # 10/15 이전 마지막 기록
    assert t[30]["bokwatch"] is None                                      # 그 시점 기록이 없으면 만들지 않는다
