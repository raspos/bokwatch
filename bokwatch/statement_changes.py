"""통화정책방향 결정문의 정책 범주별 핵심 변화(규칙 기반, 모델 호출 없음).

직전 결정문과 이번 결정문을 범주(물가·성장·소비·고용·금융안정·가계부채·환율·대외 경제·향후 통화정책 운용 방향)별로 나눠 비교한다.
각 범주: 이전 표현, 이번 표현, 변화 유형(신설·삭제·표현 변경·변화 없음), 사전에 든 핵심어의 등장·소멸, 통화정책상 가능한 의미(규칙표),
원문 출처. 중요도는 범주 가중치 × 문장 변화 정도 + 핵심어 변화로 매겨 첫 화면에는 상위 5개만 보인다.
의미 해석은 INTERPRET 규칙표에 걸린 것만 '읽힐 수 있다'로 쓰고 단정하지 않는다. 규칙에 없으면 '해석 보류'다.
전체 문장 비교(guidance.statement_diff)는 그대로 유지한다.
"""
from __future__ import annotations

import difflib
import re

from .guidance import read_statement, sentences

CATEGORIES = {
    "향후 통화정책 운용 방향": ("통화정책을 운용", "기준금리를", "기준금리의", "향후", "앞으로", "추가 인상", "점검할 필요", "파급영향", "인상 여부", "속도"),
    "물가": ("물가", "오름세", "인플레이션", "소비자물가", "근원"),
    "금융안정": ("금융안정", "리스크", "금융시장", "금융불균형", "금융기관", "변동성"),
    "가계부채": ("가계대출", "가계부채", "주택가격", "부동산", "주택시장", "주택"),
    "성장": ("성장", "경기", "수출", "투자", "내수", "경제활동"),
    "환율": ("환율", "원/달러", "원화"),
    "대외 경제": ("세계경제", "국제금융시장", "연준", "중동", "주요국", "미 달러", "국제유가", "관세", "AI 투자"),
    "소비": ("소비", "소매판매"),
    "고용": ("고용", "취업자", "실업"),
}
WEIGHT = {"향후 통화정책 운용 방향": 1.5, "물가": 1.3, "금융안정": 1.0, "가계부채": 1.0, "성장": 1.0, "환율": 0.9, "대외 경제": 0.8, "소비": 0.7, "고용": 0.7}
VOCAB = ("상방", "하방", "불확실성", "높은", "낮은", "둔화", "확대", "상회", "하회", "유의", "점검", "인상", "인하", "상향", "유지", "선제", "긴축",
         "완화", "지속", "상존", "확산", "상승", "하락", "높아진", "커진", "조정", "당분간", "상당기간", "견조", "양호", "부진", "안정")
# (등장/소멸, 핵심어) → 가능한 의미(단정 아님)
SCOPE = {"유지": ("향후 통화정책 운용 방향",), "상향": ("향후 통화정책 운용 방향",), "인하": ("향후 통화정책 운용 방향",), "선제": ("향후 통화정책 운용 방향", "물가"),
         "점검": ("향후 통화정책 운용 방향",), "둔화": ("물가", "성장", "소비", "고용"), "부진": ("성장", "소비", "고용")}
INTERPRET = {
    ("new", "상방"): "상방 위험 언급이 새로 나옴: 긴축 쪽 근거로 읽힐 수 있음",
    ("new", "하방"): "하방 위험 언급이 새로 나옴: 완화 쪽 근거로 읽힐 수 있음",
    ("new", "불확실성"): "불확실성 강조가 늘어남: 관망·신중한 운용과 함께 거론되는 표현",
    ("gone", "선제"): "선제 대응 표현이 빠짐: 인상 속도 조절 신호로 읽힐 수 있음",
    ("new", "선제"): "선제 대응 표현이 새로 나옴: 긴축 쪽 신호로 읽힐 수 있음",
    ("new", "점검"): "파급영향 점검 표현이 나옴: 추가 결정 전 관망으로 읽힐 수 있음",
    ("new", "유지"): "기준금리 '유지' 표현이 나옴: 직전의 조정(인상·인하)과 달라진 결정",
    ("gone", "상향"): "'상향 조정' 표현이 빠짐: 직전 인상과 달리 이번에는 인상이 아님",
    ("new", "인하"): "인하 언급이 새로 나옴: 완화 쪽 신호로 읽힐 수 있음",
    ("gone", "인하"): "인하 언급이 빠짐",
    ("new", "둔화"): "둔화 언급이 새로 나옴: 경기·물가 압력 완화로 읽힐 수 있음",
    ("new", "부진"): "부진 언급이 새로 나옴: 완화 쪽 근거로 읽힐 수 있음",
}


def clauses(sentence: str) -> list[str]:
    """긴 문장을 절로 나눈다(쉼표·'가운데'·'지만' 앞뒤). 한 문장에 여러 주제가 들어 있어 범주가 뒤섞이는 것을 줄인다."""
    parts = re.split(r"[,，]\s*|(?<=가운데)\s+|(?<=지만)\s+|(?<=으며)\s+|(?<=이며)\s+|(?<=하고)\s+|(?<=으나)\s+", sentence)
    return [p.strip() for p in parts if len(p.strip()) >= 8]


DECISION = ("유지", "인상", "인하", "상향", "하향")


def best_category(c: str) -> str | None:
    """절 하나는 범주 하나에만 넣는다. 기준금리 결정 표현은 '향후 통화정책 운용 방향', 그 밖에는 주제어가 가장 많이 걸린 범주(동수면 사전 순서)."""
    if ("기준금리" in c and any(d in c for d in DECISION)) or "통화정책을 운용" in c:
        return "향후 통화정책 운용 방향"
    best, hits = None, 0
    for cat, keys in CATEGORIES.items():
        n = sum(1 for k in keys if k in c)
        if n > hits:
            best, hits = cat, n
    return best


def categorize(sents: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in sents:
        for c in clauses(s) or [s]:
            cat = best_category(c)
            if cat:
                out.setdefault(cat, []).append(c)
    return out


def terms_in(texts: list[str]) -> set[str]:
    blob = " ".join(texts)
    return {w for w in VOCAB if w in blob}


def trim(texts: list[str], n: int = 2, limit: int = 220) -> str:
    t = " ".join(texts[:n])
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


def compare(prev_text: str, cur_text: str) -> list[dict]:
    pc, cc = categorize(sentences(prev_text)), categorize(sentences(cur_text))
    rows = []
    for cat in CATEGORIES:
        a, b = pc.get(cat, []), cc.get(cat, [])
        if not a and not b:
            continue
        ratio = difflib.SequenceMatcher(a=" ".join(a), b=" ".join(b), autojunk=False).ratio() if a and b else 0.0
        kind = "신설" if not a else "삭제" if not b else "변화 없음" if ratio >= 0.97 else "표현 변경"
        ta, tb = terms_in(a), terms_in(b)
        new_t, gone_t = sorted(tb - ta), sorted(ta - tb)
        ok = lambda w: cat in SCOPE.get(w, tuple(CATEGORIES))      # noqa: E731  일부 핵심어는 해당 범주에서만 해석한다
        reads = [INTERPRET[("new", w)] for w in new_t if ("new", w) in INTERPRET and ok(w)] + [INTERPRET[("gone", w)] for w in gone_t if ("gone", w) in INTERPRET and ok(w)]
        change = 1.0 if kind in ("신설", "삭제") else (1 - ratio) if kind == "표현 변경" else 0.0
        rows.append({"category": cat, "change": kind, "similarity": round(ratio, 2), "prev": trim(a), "cur": trim(b),
                     "new_terms": new_t, "gone_terms": gone_t, "reads": reads or (["해석 보류(규칙표에 해당 없음)"] if kind != "변화 없음" else []),
                     "importance": round(WEIGHT[cat] * change + 0.1 * (len(new_t) + len(gone_t)), 3) if kind != "변화 없음" else 0.0})
    return sorted(rows, key=lambda r: -r["importance"])


def source_of(path: str | None) -> str | None:
    """결정문 파일 첫 줄('# 원문: …')의 출처 표기."""
    from .common import ROOT
    p = ROOT / path if path else None
    if not p or not p.exists():
        return None
    first = p.read_text(encoding="utf-8").lstrip().splitlines()[0]
    return first.lstrip("# ").strip()[:200] if first.startswith("#") else None


def build(meetings: list[dict], k: int = 3) -> dict:
    """meetings: guidance.yaml의 회의 목록(date, statement_file). 결정문이 있는 인접 회의끼리 비교한다(최근 k쌍)."""
    have = [m for m in sorted(meetings, key=lambda m: m["date"]) if read_statement(m.get("statement_file"))]
    pairs = []
    for prev, cur in zip(have, have[1:]):
        rows = compare(read_statement(prev["statement_file"]), read_statement(cur["statement_file"]))
        pairs.append({"cur": cur["date"], "prev": prev["date"], "top": rows[:5], "all": rows, "n_changed": sum(1 for r in rows if r["change"] != "변화 없음"),
                      "source_cur": source_of(cur.get("statement_file")), "source_prev": source_of(prev.get("statement_file")),
                      "provisional": bool(re.search(r"임시본", source_of(cur.get("statement_file")) or ""))})
    return {"pairs": list(reversed(pairs))[:k],
            "method": "규칙 기반(범주 키워드·핵심어 사전). 이전·이번 표현은 결정문 원문 문장이며, '가능한 의미'는 규칙표에 걸린 경우에만 적고 단정하지 않는다."}
