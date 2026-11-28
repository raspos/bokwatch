"""Champion–Challenger. 저장소의 live 예측을 결과가 나온 뒤 모형별로 채점한다. 챔피언(운영 모형)은 승인 없이 바뀌지 않는다.

- 챌린저는 같은 (회의, 기준일)에 components에 함께 저장된 구성 모형 확률이다(별도 예측을 만들 필요 없음).
- 결과(outcome)는 회의 결정 입력 뒤에만 들어오며, 채점은 live 예측에만 쓴다(사후 재계산 backtest 파일은 쓰지 않는다).
- 전향적 검증이 충분히 쌓이기 전(최소 회의 수 미만)에는 순위를 내지 않는다.
"""
from __future__ import annotations

from collections import defaultdict

CL = ("hike", "hold", "cut")
MIN_MEETINGS = 12


def brier(p: dict, actual: str) -> float:
    return sum((p.get(c, 0.0) - (1.0 if c == actual else 0.0)) ** 2 for c in CL)


def score(records: list[dict], outcomes: dict[str, str], horizons: dict | None = None) -> dict:
    """records: Store.read('live'), outcomes: {meeting: 'hike'|'hold'|'cut'}. 모형별 회의 수·평균 Brier."""
    by = defaultdict(lambda: defaultdict(list))        # model → meeting → [brier]
    for r in records:
        a = outcomes.get(r["meeting"])
        if a is None:
            continue
        by["대표"][r["meeting"]].append(brier(r["representative"], a))
        for name, p in r["components"].items():
            by[name][r["meeting"]].append(brier(p, a))
    out = {}
    for m, d in by.items():
        per_meeting = [sum(v) / len(v) for v in d.values()]
        out[m] = {"meetings": len(per_meeting), "brier": sum(per_meeting) / len(per_meeting)}
    return out


def standings(records: list[dict], outcomes: dict[str, str], champion: str = "대표") -> dict:
    s = score(records, outcomes)
    n = s.get(champion, {}).get("meetings", 0)
    ready = n >= MIN_MEETINGS
    ranking = sorted(s.items(), key=lambda kv: kv[1]["brier"]) if ready else []
    return {"champion": champion, "ready": ready, "meetings_scored": n, "min_meetings": MIN_MEETINGS, "scores": s,
            "ranking": [k for k, _ in ranking], "note": "" if ready else f"전향적 검증 회의 {n}개 < {MIN_MEETINGS}개: 순위 보류"}
