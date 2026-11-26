

def test_meeting_day_targets_that_meeting_until_decision_is_recorded():
    from datetime import date
    from bokwatch.awm_live import target_meeting
    ms = [date(2026, 10, 22), date(2026, 11, 26), date(2027, 1, 14)]
    assert target_meeting(ms, set(), date(2026, 11, 26)) == date(2026, 11, 26)          # 회의 당일, 결정 입력 전
    assert target_meeting(ms, {date(2026, 11, 26)}, date(2026, 11, 26)) == date(2027, 1, 14)   # 결정 입력 뒤
    assert target_meeting(ms, set(), date(2026, 11, 25)) == date(2026, 11, 26)
