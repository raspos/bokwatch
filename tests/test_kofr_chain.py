from datetime import date

from bokwatch import kofr_ois as K

CURVE = {"m1": {"tenor_days": 30, "cd_date": "2026-11-11", "ois": 3.1455}, "m3": {"tenor_days": 91, "cd_date": "2026-11-11", "ois": 3.2548}}
MEETINGS = [date(2026, 11, 26), date(2027, 1, 14), date(2027, 2, 25)]


def test_later_meeting_not_solved_when_error_would_blow_up():
    path = K.solve_path(CURVE, 3.0, 0.045, MEETINGS, K.MAX_AMP)
    # 11/26은 1개월 OIS로 풀리지만, 1/14는 3개월 만기의 3분의 1 미만이라 오차가 2배를 넘어 확률로 내지 않는다
    assert [x["meeting"] for x in path] == ["2026-11-26"]
    assert path[0]["source"] == "1개월 OIS"


def test_later_meeting_falls_back_to_reference_estimate():
    est = K.min_change_estimate(CURVE, 3.0, 0.045, MEETINGS, None, K.MAX_AMP)
    assert est and [x["date"] for x in est["later"]] == ["2027-01-14"]
    assert 0 < est["later"][0]["p_hike"][0] < 0.6   # 회의별 변화 최소 가정(정해진 값이 아님)


def test_rule_does_not_change_past_dates():
    # 적용일(2026-11-11) 전 기준일에는 규칙을 쓰지 않아 과거 값과 백테스트가 그대로다
    path = K.solve_path(CURVE, 3.0, 0.045, MEETINGS)
    assert [x["meeting"] for x in path] == ["2026-11-26", "2027-01-14"]
