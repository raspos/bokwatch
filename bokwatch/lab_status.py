"""BOK LAB 현황: 데이터 구분표(어떤 금리가 무엇이고 지금 쓰는지), ACM·AFNS 연구 진행 상태, 모형 버전·변경 이력.

'합성 OIS'는 실제 거래 가격이 아니다. KOFR 자체의 거래 유동성과 KOFR-OIS 시장의 유동성도 다른 것이다.
수집하지 않는 항목은 '미수집'으로 적고 값을 만들지 않는다. 진행 단계는 실제로 한 것만 '완료'로 적는다.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .common import DATA, load_yaml

RATE_ITEMS = [
    # (표시명, rates.csv id 또는 None, 성격, 쓰임)
    ("CD 91일물", "cd91", "평가·시장금리(ECOS)", "CD 91일 모형·합성 OIS의 입력, 종합 예측 비교용"),
    ("KOFR 익일물", "kofr", "공시 일복리 금리(ECOS)", "합성 OIS의 스프레드 계산(실제 KOFR). KOFR 자체의 실거래 유동성과 별개"),
    ("통안증권 91일", "msb91", "시장금리(ECOS)", "종합 예측(M5)의 한 축"),
    ("국고채 3년물", "ktb3y", "시장금리(ECOS)", "수집 중. 확률 계산에는 쓰지 않음(ACM·AFNS 연구용 후보)"),
    ("국고채 5년물", None, "—", "미수집"),
    ("국고채 10년물", None, "—", "미수집"),
    ("KOFR 기반 기간금리", None, "—", "미수집(공식 기간금리 공표 자료 없음)"),
    ("실제 거래 기반 KOFR-OIS", None, "—", "미수집. 한국예탁결제원 공시가 2025-10-24 이후 없음, 거래 호가·거래량 자료 없음"),
    ("합성 KOFR OIS", None, "자체 산출 추정치", "CD 시가평가 − 스프레드(과거 CD−KOFR 중앙값). 거래 가격이 아님. 기본 확률의 한 축"),
]
ACM_AFNS = [
    ("1", "필요한 국채 수익률 데이터 확인", "부분 완료", "국고채 3년물만 수집 중. ACM은 1~10년 만기 여러 개, AFNS는 3~4개 만기가 필요"),
    ("2", "데이터 수집 가능성 점검", "미착수", "ECOS 국고채 5년·10년 계열 코드 확인 필요(코드를 추측해 쓰지 않는다)"),
    ("3", "기간구조 추정", "미착수", ""),
    ("4", "기대 단기금리와 기간 프리미엄 분리", "미착수", ""),
    ("5", "금통위 결정 확률로 변환하는 별도 모형 설계", "미착수", "기간 프리미엄 추정치가 곧 인상 확률은 아니다"),
    ("6", "과거 예측 성능 검증", "미착수", "워크포워드, 금통위 단위 군집 부트스트랩(AWM과 같은 방식)"),
    ("7", "기존 모형과 비교", "미착수", "검증 전에는 공식 확률에 반영하지 않는다"),
]


def rate_stats(rates_csv: Path) -> dict[str, dict]:
    st: dict[str, dict] = {}
    if not rates_csv.exists():
        return st
    for r in csv.DictReader(open(rates_csv, encoding="utf-8")):
        s = st.setdefault(r["id"], {"n": 0, "first": r["date"], "last": r["date"]})
        s["n"] += 1
        s["first"], s["last"] = min(s["first"], r["date"]), max(s["last"], r["date"])
    return st


def build() -> dict:
    st = rate_stats(DATA / "rates.csv")
    items = []
    for name, rid, kind, use in RATE_ITEMS:
        s = st.get(rid) if rid else None
        items.append({"name": name, "kind": kind, "use": use, "status": "수집 중" if s else ("추정치(자체 산출)" if name == "합성 KOFR OIS" else "미수집"),
                      "n": s["n"] if s else None, "first": s["first"] if s else None, "last": s["last"] if s else None})
    log = load_yaml("model_changelog.yaml") or {}
    return {"data": items, "acm_afns": [{"step": a, "name": b, "status": c, "note": d} for a, b, c, d in ACM_AFNS],
            "changelog": sorted(log.get("changes", []), key=lambda x: x["date"], reverse=True),
            "note": "ACM·AFNS는 연구용이며 검증 전에는 공식 확률에 반영하지 않는다."}
