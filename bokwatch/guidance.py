"""통방문 문구 비교, 매파·비둘기 보조점수, 발언 타임라인, 점도표 집계."""
from __future__ import annotations

import difflib
import re
from datetime import date

from .common import ROOT, d, load_yaml


def load_guidance() -> dict:
    g = load_yaml("guidance.yaml")
    g.setdefault("meetings", [])
    g.setdefault("speeches", [])
    return g


# ---------------------------------------------------------------- 점도표
def dot_list(dots: dict) -> list[float]:
    out = []
    for lv, n in sorted((float(k), int(v)) for k, v in (dots or {}).items()):
        out += [lv] * n
    return out


def dotplot_summary(dots: dict, current: float) -> dict:
    pts = dot_list(dots)
    if not pts:
        return {}
    n = len(pts)
    med = pts[n // 2] if n % 2 else (pts[n // 2 - 1] + pts[n // 2]) / 2
    return {
        "n": n,
        "median": med,
        "above": sum(p > current + 1e-9 for p in pts),
        "at": sum(abs(p - current) < 1e-9 for p in pts),
        "below": sum(p < current - 1e-9 for p in pts),
        "min": pts[0], "max": pts[-1],
        "dist": {f"{float(k):.2f}": int(v) for k, v in sorted((float(k), v) for k, v in dots.items())},
    }


def next_dotplot_meeting(meetings: list[date], months: list[int], after: date):
    for m in sorted(meetings):
        if m > after and m.month in months:
            return m
    return None


# ---------------------------------------------------------------- 통방문
def read_statement(path: str | None) -> str | None:
    if not path:
        return None
    p = ROOT / path
    if not p.exists():
        return None
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")]
    return "\n".join(lines).strip()


def is_provisional(path: str | None) -> bool:
    if not path or not (ROOT / path).exists():
        return False
    first = (ROOT / path).read_text(encoding="utf-8").lstrip()
    return first.startswith("#") and "임시본" in first.splitlines()[0]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=\.)\s+|\n+", (text or "").strip())
    return [" ".join(p.split()) for p in parts if p.strip(" .")]


def statement_diff(prev: str | None, cur: str | None) -> list[dict]:
    """문장 단위 diff. op: same | add | del"""
    a, b = sentences(prev or ""), sentences(cur or "")
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [{"op": "same", "text": s} for s in a[i1:i2]]
        else:
            out += [{"op": "del", "text": s} for s in a[i1:i2]]
            out += [{"op": "add", "text": s} for s in b[j1:j2]]
    return out


# ---------------------------------------------------------------- 보조점수
def tone_score(texts: list[str], lex: dict) -> dict:
    """사전 기반 매파(+)·비둘기(−) 점수. 문장 수로 나눠 -1~1 근처로. 자동 산출, 참고용."""
    hawk = dove = 0.0
    hits = []
    n = 0
    for t in texts:
        for s in sentences(t):
            n += 1
            for w, v in (lex.get("hawkish") or {}).items():
                if w in s:
                    # '인상' 사전어가 '추가 인상'과 겹쳐 두 번 세지지 않게 더 긴 단어 우선
                    if any(w != w2 and w in w2 and w2 in s for w2 in lex["hawkish"]):
                        continue
                    hawk += v
                    hits.append(("hawk", w))
            for w, v in (lex.get("dovish") or {}).items():
                if w in s:
                    if any(w != w2 and w in w2 and w2 in s for w2 in lex["dovish"]):
                        continue
                    dove += v
                    hits.append(("dove", w))
    score = (hawk - dove) / max(n, 1)
    return {"score": round(score, 3), "hawk": hawk, "dove": dove, "sentences": n, "hits": hits}


# ---------------------------------------------------------------- 묶음
def build_guidance(cfg: dict, minutes: dict | None = None, today: date | None = None) -> dict:
    g = load_guidance()
    meets = sorted(g["meetings"], key=lambda m: m["date"])
    links = {m["date"]: m for m in (minutes or {}).get("meetings", [])}
    out_meetings = []
    prev_text = None
    prev_rate = None
    for m in meets:
        text = read_statement(m.get("statement_file"))
        texts = [t for t in [text] + [q["text"] for q in m.get("press_quotes") or []] if t]
        e = {
            "date": m["date"], "rate": m.get("rate"), "decision": m.get("decision"),
            "prev_rate": prev_rate,
            "vote": m.get("vote"), "forward_guidance": m.get("forward_guidance"),
            "press_quotes": m.get("press_quotes") or [],
            "outlook": m.get("outlook"), "verify": bool(m.get("verify")), "source": m.get("source"),
            "statement_provisional": is_provisional(m.get("statement_file")),
            "has_statement": text is not None,
            "diff": statement_diff(prev_text, text) if (text and prev_text) else None,
            "tone": tone_score(texts, cfg["tone"]) if texts else None,
            "dotplot": dotplot_summary(m["dotplot"], m.get("rate")) if m.get("dotplot") else None,
            "links": links.get(m["date"], {}).get("docs", {}),
            "minutes_expected": links.get(m["date"], {}).get("minutes_expected"),
            "minutes_status": links.get(m["date"], {}).get("minutes_status"),
        }
        if text:
            prev_text = text
        prev_rate = m.get("rate")
        out_meetings.append(e)
    dots = [m for m in out_meetings if m["dotplot"]]
    from .common import all_meetings
    nxt = next_dotplot_meeting(all_meetings(cfg), cfg.get("dotplot_months", []), today or date.today())
    speeches = sorted(g["speeches"], key=lambda s: s["date"], reverse=True)
    return {
        "meetings": list(reversed(out_meetings)),
        "dotplots": [{"date": m["date"], "rate": m["rate"], **m["dotplot"]} for m in reversed(dots)],
        "next_dotplot": nxt.isoformat() if nxt else None,
        "speeches": speeches,
        "speakers": sorted({s["speaker"] for s in speeches}),
        "venues": sorted({s["venue"] for s in speeches}),
    }
