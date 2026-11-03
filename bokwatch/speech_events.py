"""한국은행 발언 통합: 같은 행사(날짜+장소)의 발언을 하나의 이벤트로 묶고, 종합 논조·이전 행사 대비 변화·정책 주제별 신호를 만든다.

모두 규칙 기반이며 모델을 부르지 않는다. 화면에 보이는 '분석'은 이 규칙의 결과이고, 발언 원문(인용)은 data/guidance.yaml의 값 그대로다.
- 종합 논조: 발언별 tone(hawk +1, neutral 0, dove −1) 평균. +0.25 초과 매파 / −0.25 미만 비둘기 / 그 사이 중립.
  인용이 1개뿐이면 '신뢰도 낮음'으로 표시하고, 논조를 단정하지 않는다(판단 유보 대상).
- 이전 대비 변화: 직전 행사의 평균 점수와 비교(차이 ±0.34 이상이면 강화·완화, 그 안이면 변화 없음). 발언자가 같은 직전 행사끼리 비교한다.
- 주제별 신호: 인용문에 주제어가 들어 있는 발언만 센다(물가·성장·금리 경로·금융안정·환율).
- 표현 변화: 정책 표현 사전(EXPRS)에 든 표현이 이전 행사에는 없고 이번에 나온 것(새로 등장), 이전에는 있고 이번에 없는 것(사라짐).
  사전에 없는 표현은 보지 못한다. 문장 단위 의미 비교가 아니라 표현 유무 비교임을 화면에 밝힌다.
"""
from __future__ import annotations

TONE = {"hawk": 1, "neutral": 0, "dove": -1}
VERDICT = {1: "매파", 0: "중립", -1: "비둘기파"}
TOPICS = {
    "물가": ("물가", "인플레", "CPI", "소비자물가"),
    "성장": ("성장", "GDP", "경기", "수출", "소비", "투자"),
    "금리 경로": ("금리", "인상", "인하", "동결", "긴축", "정책 기조", "통화정책"),
    "금융안정": ("금융안정", "가계부채", "부동산", "집값", "주택", "금융시장", "금융불안"),
    "환율": ("환율", "원화", "달러", "외환"),
}
EXPRS = ("긴축", "호미", "가래", "상방 위험", "하방 위험", "고성장", "고금리", "저금리", "초저금리", "선제", "속도 조절", "추가 인상", "인상 사이클",
         "데이터", "확인", "늦지 않다", "적절한 시기", "불확실성", "경계", "가계부채", "집값", "환율", "안정", "수렴", "동결", "인하", "인상 기조")
RISK = ("상방 위험", "하방 위험", "불확실성", "가계부채", "금융불안", "집값", "환율")
UP, DOWN = 0.25, -0.25
CHANGE = 0.34


def score(tones: list[str]) -> float:
    return sum(TONE.get(t, 0) for t in tones) / len(tones) if tones else 0.0


def verdict(sc: float) -> str:
    return "매파" if sc > UP else "비둘기파" if sc < DOWN else "중립"


def terms(texts: list[str], vocab=EXPRS) -> set[str]:
    blob = " ".join(texts)
    return {w for w in vocab if w in blob}


def group_events(speeches: list[dict]) -> list[dict]:
    """같은 날짜·같은 장소는 한 이벤트. 날짜가 같아도 장소가 다르면 별도."""
    by: dict[tuple, list[dict]] = {}
    for s in speeches:
        by.setdefault((s["date"], s["venue"]), []).append(s)
    return [{"date": d, "venue": v, "items": its} for (d, v), its in sorted(by.items(), key=lambda kv: kv[0], reverse=True)]


def build(speeches: list[dict]) -> dict:
    events = group_events(speeches)
    out = []
    for i, ev in enumerate(events):
        its = ev["items"]
        sc = score([s.get("tone", "neutral") for s in its])
        speakers = sorted({s["speaker"] for s in its})
        # 직전 행사: 같은 발언자가 있는 가장 가까운 이전 행사
        prev = next((e for e in events[i + 1:] if {s["speaker"] for s in e["items"]} & set(speakers)), None)
        change = None
        new_t = gone_t = []
        if prev:
            psc = score([s.get("tone", "neutral") for s in prev["items"]])
            diff = sc - psc
            change = {"vs": f"{prev['date']} {prev['venue']}", "diff": round(diff, 2),
                      "label": "매파 강화" if diff >= CHANGE else "비둘기파 쪽 완화" if diff <= -CHANGE else "변화 없음"}
            cur_t, pr_t = terms([s["quote"] for s in its]), terms([s["quote"] for s in prev["items"]])
            new_t, gone_t = sorted(cur_t - pr_t), sorted(pr_t - cur_t)
        topics = {}
        for name, keys in TOPICS.items():
            hit = [s for s in its if any(k in s["quote"] for k in keys)]
            if hit:
                topics[name] = {"n": len(hit), "tone": verdict(score([s.get("tone", "neutral") for s in hit]))}
        low = len(its) < 2
        out.append({
            "id": f"{ev['date']}|{ev['venue']}", "date": ev["date"], "venue": ev["venue"], "speakers": speakers,
            "verdict": "판단 유보(인용 1개)" if low else verdict(sc), "score": round(sc, 2), "confidence": "낮음" if low else "보통",
            "n_quotes": len(its), "change": change, "topics": topics,
            "new_terms": new_t, "gone_terms": gone_t, "risk_terms": sorted(terms([s["quote"] for s in its], RISK)),
            "quotes": [{k: s.get(k) for k in ("speaker", "tone", "quote", "link", "note", "verify")} for s in its],
        })
    return {"events": out, "method": "규칙 기반(발언 tone 평균·주제어·표현 사전). 발언 원문은 data/guidance.yaml 인용 그대로이며 AI 요약이 아니다."}
