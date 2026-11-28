"""금통위 상태 기계. 한 회의는 네 상태를 순서대로 지난다.

UPCOMING                 회의일 전날까지. 확률은 매일 아침 갱신한다.
MEETING_DAY_PRE_DECISION 회의 당일, 결정 발표(기본 10:00 KST) 전. 당일 아침 예측은 영구 저장하고 이 상태에서만 만든다.
DECISION_RELEASED        결정이 발표된 뒤(발표 시각 이후 또는 결정이 입력됨). 새 예측을 만들지 않고 결과·검증만 보여 준다.
POST_DECISION            회의 다음 날 이후. 다음 회의가 대상이 된다.

대상 회의(target)는 상태가 POST_DECISION이 될 때까지 바뀌지 않는다. 결정 입력이 늦어도 당일에는 같은 회의가 유지된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum

DECISION_TIME = time(10, 0)


class State(str, Enum):
    UPCOMING = "UPCOMING"
    MEETING_DAY_PRE_DECISION = "MEETING_DAY_PRE_DECISION"
    DECISION_RELEASED = "DECISION_RELEASED"
    POST_DECISION = "POST_DECISION"


def meeting_state(meeting: date, now: datetime, decided: set[date], decision_time: time = DECISION_TIME) -> State:
    today = now.date()
    if today < meeting:
        return State.UPCOMING
    if today == meeting:
        if meeting in decided or now.time() >= decision_time:
            return State.DECISION_RELEASED
        return State.MEETING_DAY_PRE_DECISION
    return State.POST_DECISION


@dataclass
class Target:
    meeting: date
    state: State


def target(meetings: list[date], decided: set[date], now: datetime) -> Target | None:
    """지금 화면의 대표 회의. POST_DECISION이 아닌 첫 회의(결정이 입력됐어도 당일에는 그 회의)."""
    for m in sorted(meetings):
        st = meeting_state(m, now, decided)
        if st != State.POST_DECISION:
            return Target(m, st)
    return None


def may_write_forecast(st: State) -> bool:
    """새 예측 기록은 회의 전날까지(UPCOMING)와 당일 결정 전(MEETING_DAY_PRE_DECISION)에만 한다."""
    return st in (State.UPCOMING, State.MEETING_DAY_PRE_DECISION)
