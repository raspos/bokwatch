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


# ---------------------------------------------------------------- KOFR 3개월 선물 (FedWatch 방식)
def test_kofr_futures_recovers_known_path():
    from datetime import timedelta
    from bokwatch import futures_model as fm
    assert fm.third_wednesday(2026, 11) == date(2026, 11, 18)
    assert fm.ref_window("2026-11") == (date(2026, 8, 19), date(2026, 11, 18))
    asof, r0, s = date(2026, 10, 13), 3.00, 0.04
    oct_, nov = date(2026, 10, 22), date(2026, 11, 26)
    E1, E2 = 3.10, 3.25          # 10월 뒤 기대 3.10%(인상확률 40%), 11월 뒤 3.25%(Δ 15bp → 60%)

    def path(d):
        return E2 if d >= nov else E1 if d >= oct_ else r0
    # 지난 KOFR 공시: 8/27 전 2.75%, 이후 3.00% (+정상 차이), 주말은 공시 없음
    fix, d = {}, date(2026, 6, 1)
    while d <= asof:
        if d.weekday() < 5:
            fix[d.isoformat()] = (3.00 if d >= date(2026, 8, 27) else 2.75) + s
        d += timedelta(days=1)
    cs = [fm.Contract(m, fm.price_for_path(m, path, fix, asof, s)) for m in ("2026-10", "2026-11", "2026-12", "2027-01")]
    out = fm.solve(asof, r0, cs, fix, [oct_, nov], s, known_through=date(2027, 1, 13))
    got = {m["date"]: m for m in out["meetings"]}
    assert abs(got["2026-10-22"]["p_hike"] - 0.40) < 0.01
    assert abs(got["2026-11-26"]["p_hike"] - 0.60) < 0.01
    assert abs(got["2026-11-26"]["expected"] - 3.25) < 0.003
    # 1월물(기준기간 10/21~2027-01-19)은 확정 일정 밖이라 쓰지 않는다
    assert [x["month"] for x in out["skipped"] if "확정 일정" in x["why"]] == ["2027-01"]


def test_blend_meetings_weights_and_fallback():
    from bokwatch.market import blend_meetings

    def mt(dt, h, hold, exp):
        return {"date": dt, "expected": exp, "delta_bp": 0.0, "p_hike": h, "p_hold": hold, "p_cut": 0.0,
                "moves": {"0": hold, "25": h}, "levels": {"3.00": hold, "3.25": h}, "method": "x", "in_range": True}
    cd = [mt("2026-10-22", 0.0, 1.0, 3.00), mt("2026-11-26", 0.455, 0.545, 3.114)]
    kf = [mt("2026-10-22", 1.0, 0.0, 3.25)]
    out = {m["date"]: m for m in blend_meetings(cd, kf, 0.5)}
    assert out["2026-10-22"]["p_hike"] == 0.5 and out["2026-10-22"]["expected"] == 3.125
    assert out["2026-10-22"]["source"] == "CD·KOFR 선물 혼합"
    # 한쪽만 있는 회의는 그쪽 값을 그대로 쓰고 출처를 밝힌다
    assert out["2026-11-26"]["p_hike"] == 0.455 and out["2026-11-26"]["source"] == "CD 91일만"
    assert blend_meetings(None, kf, 0.5)[0]["source"] == "KOFR 선물만"


def test_backtest_tie_is_not_a_hit():
    from bokwatch.market import _score
    pred, br = _score({"hike": 0.5, "hold": 0.5, "cut": 0.0}, "hike")
    assert pred == "tie" and br == 0.5
    assert _score({"hike": 0.6, "hold": 0.4, "cut": 0.0}, "hike")[0] == "hike"


def test_cd_path_ranges_match_review_example():
    from bokwatch import model
    # 리뷰 검산: CD 3.24, r0 3.00, 스프레드 18bp → 83·p10 + 48·p11 = 21.84
    r = model.path_ranges(date(2026, 10, 13), 3.00, model.Instrument("cd91", 3.24, 91, 0.18),
                          [date(2026, 10, 22), date(2026, 11, 26)])
    o, n = r["meetings"]["2026-10-22"], r["meetings"]["2026-11-26"]
    assert r["direction"] == "hike" and abs(r["L"] - 21.84) < 1e-6 and r["feasible"]
    assert (o["exposure_days"], n["exposure_days"]) == (83, 48)
    assert (o["min"], round(o["max"], 3)) == (0.0, 0.263) and (n["min"], round(n["max"], 3)) == (0.0, 0.455)
    assert (o["late"], round(n["late"], 3)) == (0.0, 0.455)          # 늦은 회의 배정(화면 기본값과 같음)
    assert (round(o["early"], 3), n["early"]) == (0.263, 0.0)        # 가까운 회의 배정


def test_decision_model_point_in_time_and_ordering():
    from bokwatch import decision_model as dm
    core = {f"2025-{m:02d}": 100.0 for m in range(1, 13)} | {"2026-08": 103.0, "2026-09": 104.0, "2025-09": 100.0, "2025-08": 100.0}
    # 10/5에는 9월 지수가 아직 발표 전이라 8월분, 10/6부터 9월분
    assert dm.core_gap_on(core, date(2026, 10, 5))[1] == "2026-08"
    assert dm.core_gap_on(core, date(2026, 10, 6))[1] == "2026-09"
    # 순서형 로지스틱: 변수가 커질수록 인상 확률이 올라간다
    rows = [{"spread_bp": v, "cd_chg_bp": v, "core_gap": v / 10, "actual": a}
            for v, a in [(-30, "cut"), (-25, "cut"), (-5, "hold"), (0, "hold"), (5, "hold"), (2, "hold"), (25, "hike"), (30, "hike")]]
    m = dm.fit(rows)
    lo, hi = dm.predict(m, {"spread_bp": -30, "cd_chg_bp": -30, "core_gap": -3}), dm.predict(m, {"spread_bp": 30, "cd_chg_bp": 30, "core_gap": 3})
    assert hi["hike"] > lo["hike"] and lo["cut"] > hi["cut"] and abs(sum(hi.values()) - 1) < 1e-3
