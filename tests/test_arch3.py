import json
from datetime import date, datetime

import pytest

from bokwatch3 import champion, checks, state, store

M = date(2026, 11, 26)


def test_state_machine():
    dec = set()
    assert state.meeting_state(M, datetime(2026, 11, 25, 9), dec) == state.State.UPCOMING
    assert state.meeting_state(M, datetime(2026, 11, 26, 8, 30), dec) == state.State.MEETING_DAY_PRE_DECISION
    assert state.meeting_state(M, datetime(2026, 11, 26, 10, 1), dec) == state.State.DECISION_RELEASED
    assert state.meeting_state(M, datetime(2026, 11, 26, 8, 30), {M}) == state.State.DECISION_RELEASED     # 결정이 먼저 입력됨
    assert state.meeting_state(M, datetime(2026, 11, 27, 9), {M}) == state.State.POST_DECISION


def test_target_stays_on_meeting_day():
    ms = [date(2026, 10, 22), M, date(2027, 1, 14)]
    t = state.target(ms, {date(2026, 10, 22), M}, datetime(2026, 11, 26, 9))
    assert t.meeting == M and t.state == state.State.DECISION_RELEASED          # 결정이 입력돼도 당일 대상은 그 회의
    t2 = state.target(ms, {date(2026, 10, 22), M}, datetime(2026, 11, 27, 9))
    assert t2.meeting == date(2027, 1, 14)
    assert state.may_write_forecast(state.State.MEETING_DAY_PRE_DECISION)
    assert not state.may_write_forecast(state.State.DECISION_RELEASED)


def rec(asof, slot="daily", ph=0.5, ver="rep-1"):
    p = {"hike": ph, "hold": 1 - ph, "cut": 0.0}
    return {"meeting": "2026-11-26", "asof": asof, "made_at": asof + "T09:00", "model_version": ver, "state": "UPCOMING", "slot": slot,
            "representative": p, "components": {"ois": {"hike": ph + 0.1, "hold": 0.9 - ph, "cut": 0.0}, "msb91": p}}


def test_store_append_only(tmp_path):
    s = store.Store(tmp_path)
    s.append(rec("2026-11-24"))
    with pytest.raises(store.DuplicateForecast):
        s.append(rec("2026-11-24"))
    s.append(rec("2026-11-25", slot="morning_of"))
    assert s.morning_of("2026-11-26")["asof"] == "2026-11-25"
    assert len(s.read("live")) == 2 and s.read("backtest") == []             # live·backtest 분리
    bad = rec("2026-11-23")
    bad["representative"] = {"hike": 0.9, "hold": 0.5, "cut": 0.0}
    with pytest.raises(ValueError):
        s.append(bad)


def test_champion_waits_for_enough_meetings(tmp_path):
    s = store.Store(tmp_path)
    s.append(rec("2026-11-24", ph=0.52))
    sc = champion.standings(s.read("live"), {"2026-11-26": "hike"})
    assert not sc["ready"] and sc["ranking"] == []
    assert abs(sc["scores"]["대표"]["brier"] - (0.48 ** 2 + 0.48 ** 2)) < 1e-9


def test_predeploy_detects_missing_snapshot(tmp_path):
    sd = tmp_path
    for f in checks.REQUIRED_DATA:
        (sd / f).write_text("{}" if f.endswith(".json") else "x", encoding="utf-8")
    (sd / "snapshots").mkdir()
    (sd / "meta.json").write_text(json.dumps({"latest": "2026-11-25", "snapshots": ["2026-11-24", "2026-11-25"]}), encoding="utf-8")
    (sd / "snapshots" / "2026-11-24.json").write_text("{}", encoding="utf-8")
    errs = checks.predeploy(sd)
    assert any("2026-11-25" in e for e in errs)
    (sd / "snapshots" / "2026-11-25.json").write_text("{}", encoding="utf-8")
    assert checks.predeploy(sd) == []


def test_consistency_and_turning_points():
    ok = {"hike": 0.523, "hold": 0.477, "cut": 0.0}
    assert checks.consistency(ok, dict(ok), dict(ok)) == []
    assert checks.consistency(ok, {"hike": 0.481, "hold": 0.519, "cut": 0.0}, ok)
    tp = checks.turning_points(["a", "b", "c"], [0.9, 0.73, 0.70])
    assert len(tp) == 1 and tp[0]["date"] == "b"
    assert checks.probability_range([0.5, 0.2, 0.7]) == (0.2, 0.7)
