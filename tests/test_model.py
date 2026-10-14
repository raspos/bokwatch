from datetime import date

import pytest

from bokwatch.model import Instrument, solve, segment_days, sensitivity, move_distribution

ASOF = date(2026, 10, 13)
MEETINGS = [date(2026, 10, 22), date(2026, 11, 26)]


def run(spread_bp, method="min_hike"):
    cd = Instrument("CD91", 3.24, 91, spread_bp / 100)
    return solve(ASOF, 3.00, [cd], MEETINGS, method=method)


def pct(x):
    return round(x * 100, 1)


def test_checksum_base():
    r = run(10)
    oct_, nov = r.meetings
    assert pct(oct_.p_hike) == 8.5
    assert pct(nov.p_hike) == 91.5
    assert nov.level_probs == {3.25: 1.0}


def test_checksum_auto_equals_min_hike():
    # CD 하나에 회의 2개 → auto도 최소 인상 경로로 풀어야 한다
    a, b = run(10, "auto"), run(10, "min_hike")
    assert [m.p_hike for m in a.meetings] == pytest.approx([m.p_hike for m in b.meetings])


def test_checksum_spread_5():
    assert pct(run(5).meetings[0].p_hike) == 60.5


def test_checksum_spread_15():
    r = run(15)
    assert pct(r.meetings[0].p_hike) == 0.0
    assert pct(r.meetings[1].p_hike) == 68.3


def test_sensitivity_keys():
    s = sensitivity(ASOF, 3.0, [Instrument("CD91", 3.24, 91, 0.10)], MEETINGS, "min_hike")
    assert pct(s[-5].meetings[0].p_hike) == 60.5 and pct(s[5].meetings[1].p_hike) == 68.3


@pytest.mark.parametrize("sp", [0, 5, 10, 15, 20, 30, 40])
@pytest.mark.parametrize("method", ["auto", "min_hike", "lsq"])
def test_probs_sum_to_one_nonnegative(sp, method):
    for m in run(sp, method).meetings:
        assert sum(m.move_probs.values()) == pytest.approx(1)
        assert sum(m.level_probs.values()) == pytest.approx(1)
        assert m.p_hike + m.p_hold + m.p_cut == pytest.approx(1)
        assert all(v >= -1e-12 for v in list(m.move_probs.values()) + list(m.level_probs.values()))


def test_meeting_outside_maturity_has_zero_weight():
    seg = segment_days(date(2026, 10, 14), 30, MEETINGS)
    assert seg[2] == 0 and sum(seg) == 30
    r = solve(ASOF, 3.0, [Instrument("x", 3.10, 30, 0)], MEETINGS + [date(2027, 1, 14)], "auto")
    assert [m.in_range for m in r.meetings] == [True, False, False]


def test_big_move_and_cut():
    d = move_distribution(0.30)
    assert d[25] == pytest.approx(0.8) and d[50] == pytest.approx(0.2)
    d = move_distribution(-0.10)
    assert d[-25] == pytest.approx(0.4) and d[0] == pytest.approx(0.6)


def test_bootstrap_two_tenors():
    # 만기가 회의를 하나씩 더 덮는 두 상품 → 정확히 역산
    insts = [Instrument("a", 0, 40, 0), Instrument("b", 0, 91, 0)]
    start = date(2026, 10, 14)
    # 진짜 경로: 10월 +25bp, 11월 +0  → a: 8일 3.00, 32일 3.25
    insts[0].rate = (8 * 3.0 + 32 * 3.25) / 40
    insts[1].rate = (8 * 3.0 + 83 * 3.25) / 91
    r = solve(ASOF, 3.0, insts, MEETINGS, "auto")
    assert r.meetings[0].p_hike == pytest.approx(1)
    assert r.meetings[1].p_hike == pytest.approx(0, abs=1e-9)
    assert r.method == "bootstrap"
