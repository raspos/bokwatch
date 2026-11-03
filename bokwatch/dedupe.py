"""기사 중복 판정(규칙 기반, 모델 호출 없음).

유형
  1 재수집        같은 언론사의 같은 제목(링크만 다름)
  2 통신사 전재    다른 언론사가 통신사 기사를 거의 그대로 실음(제목·요약 거의 동일)
  3 제목 변경     제목만 바꾼 전재(제목은 비슷하고 요약이 사실상 같음)
  4 수정·업데이트  같은 언론사가 같은 기사를 고쳐 다시 올림(제목이 크게 겹침)
  5 같은 사건     같은 보도자료·사건에 근거한 비슷한 기사. 묶되 지우지 않는다(독립 분석이 있을 수 있음)
  6 독립 보도     그 밖 모두. 각각 인정
1~4는 가장 먼저 나온 기사만 남기고 나머지는 점수·태깅에서 뺀다(dup_of에 남긴 기사 id 기록). 5·6은 그대로 둔다.
기준 값은 data/config.yaml이 아니라 이 파일 상단에 둔다. 임계값을 바꾸면 tests/test_dedupe.py의 표본도 함께 본다.
"""
from __future__ import annotations

import re
from datetime import datetime

WINDOW_H = 72
T_SAME = 0.9          # 제목 거의 동일
T_UPDATE = 0.6        # 같은 언론사 수정·업데이트
T_RETITLE = 0.6       # 제목 변경 전재의 제목 하한
S_COPY = 0.8          # 요약이 사실상 같음
T_WIRE = 0.75         # 통신사 기사 전재로 보는 제목 하한(요약도 어느 정도 겹칠 때)
S_WIRE = 0.3
S_RETITLE = 0.7
T_EVENT = 0.5         # 같은 사건으로 묶는 하한(ai_judge.group_by_title과 같은 값)
WIRE = {"yna", "newsis", "news1", "newspim", "einfomax", "yonhapnewstv"}
REMOVE = {1, 2, 3, 4}
NAMES = {1: "재수집", 2: "통신사 전재", 3: "제목 변경", 4: "수정·업데이트", 5: "같은 사건", 6: "독립 보도"}


def bigrams(s: str) -> set[str]:
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|[^가-힣A-Za-z0-9]", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def classify_pair(a: dict, b: dict, ga: set, gb: set, sa: set, sb: set) -> int:
    """a가 먼저 나온 기사, b가 나중 기사일 때 b의 유형(1~6)."""
    tj, sj = jac(ga, gb), jac(sa, sb)
    same_press = bool(a.get("press_id")) and a.get("press_id") == b.get("press_id")
    wire = a.get("press_id") in WIRE or b.get("press_id") in WIRE
    if tj >= T_SAME:
        if same_press:
            return 1
        if wire or sj >= S_COPY:
            return 2
        return 3
    if wire and not same_press and tj >= T_WIRE and sj >= S_WIRE:
        return 2                                       # 통신사 제목을 따옴표·접두어만 고쳐 실은 경우
    if same_press and tj >= T_UPDATE:
        return 4
    if not same_press and ((tj >= T_RETITLE and sj >= S_RETITLE) or (tj >= 0.4 and sj >= S_COPY)):
        return 3                                       # 요약(본문 첫머리)이 사실상 같으면 제목이 달라도 같은 글
    if tj >= T_EVENT:
        return 5
    return 6


def mark(articles: list[dict], window_h: int = WINDOW_H) -> dict:
    """기사에 dup_type·dup_of를 달고 유형별 개수를 돌려준다. 입력 순서와 무관하게 발행 시각 순으로 판정한다."""
    order = sorted(range(len(articles)), key=lambda i: articles[i]["published"])
    g = {i: bigrams(articles[i]["title"]) for i in order}
    s = {i: bigrams((articles[i].get("summary") or "")[:200]) for i in order}
    t = {i: datetime.fromisoformat(articles[i]["published"]) for i in order}
    keep: dict[int, int] = {}          # 남기는 기사의 위치(자기 자신이면 그대로)
    cnt = {k: 0 for k in NAMES}
    for pos, j in enumerate(order):
        a = articles[j]
        best, best_of = 6, None
        for k in order[max(0, pos - 400):pos]:           # 앞선 기사들과만 비교(시간 창)
            if (t[j] - t[k]).total_seconds() > window_h * 3600:
                continue
            kk = keep[k]                      # 비교 대상은 그 기사가 속한 '남긴 기사'
            ty = classify_pair(articles[kk], a, g[kk], g[j], s[kk], s[j])
            if ty < best:
                best, best_of = ty, kk
        a["dup_type"] = NAMES[best]
        if best in REMOVE:
            a["dup_of"] = articles[best_of]["id"]
            keep[j] = best_of
        else:
            a.pop("dup_of", None)
            keep[j] = j
        cnt[best] += 1
    return {NAMES[k]: v for k, v in cnt.items()}


def unique(articles: list[dict]) -> list[dict]:
    """점수·태깅 대상: 중복(1~4)으로 판정된 기사를 뺀 목록."""
    return [a for a in articles if a.get("dup_type") not in {NAMES[k] for k in REMOVE}]
