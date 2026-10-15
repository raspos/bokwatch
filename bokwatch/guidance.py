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
def _stems(text: str) -> set[str]:
    """한글·영문 낱말의 어간 비슷한 앞부분(끝 글자 하나는 조사일 수 있어 뗀다)."""
    import re
    out = set()
    for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text or ""):
        out.add(w[:-1] if len(w) >= 3 else w)
    return out


VENUE_KEYS = {  # 발언 자리별로 기사 제목·요약에서 찾을 말
    "국회": ["국감", "국정감사", "국회"],
    "IMF": ["IMF", "총재와의 대화", "연차총회", "자연이자율", "중립금리"],
    "CNN": ["CNN", "퍼스펙티브", "K자", "양극화", "저소득"],
    "간담회": ["기자간담회", "간담회"],
    "설명회": ["설명회"],
    "잭슨홀": ["잭슨홀", "특파원"],
    "면담": ["부총리", "면담"],
}
RATE_WORDS = ("금리", "물가", "인상", "인하", "환율", "통화정책", "긴축", "중립", "인플레", "AI", "양극화", "성장", "원화")


def related_articles(speeches: list[dict], press: dict, days: int = 2) -> None:
    """발언 자리(날짜+장소)마다 관련 기사를 모은다. 지정 언론사, 발언일~2일 뒤, 제목에 총재·금리 관련 말.
    기사 하나는 점수가 가장 높은 자리 하나에만 붙인다(자리 낱말 2점 + 발언 낱말 1점, 2점 이상)."""
    import json
    from datetime import timedelta
    from urllib.parse import urlparse
    from .common import SITE_DATA
    arts = []
    for f in ("naver.jsonl", "news.jsonl"):
        path = SITE_DATA / f
        if path.exists():
            arts += [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool, seen = [], set()
    for a in arts:
        name = press.get(urlparse(a["link"]).netloc)
        t = a["title"]
        if not name or a["link"] in seen or not any(k in t for k in ("신현송", "총재")) or not any(k in t for k in RATE_WORDS):
            continue
        seen.add(a["link"])
        pool.append({**a, "press_name": name, "text": t + " " + (a.get("summary") or "")})
    events: dict[tuple, dict] = {}
    for s in speeches:
        ev = events.setdefault((s["date"], s["venue"]), {"stems": set(), "keys": []})
        ev["stems"] |= _stems(s.get("quote", ""))
        ev["keys"] = next((v for k, v in VENUE_KEYS.items() if k in s["venue"]), [])
    found: dict[tuple, list] = {k: [] for k in events}
    for a in pool:
        best, best_sc = None, 0
        for (dd, venue), ev in events.items():
            d0 = date.fromisoformat(dd)
            if not (d0.isoformat() <= a["published"] <= (d0 + timedelta(days=days)).isoformat() + "T23:59"):
                continue
            sc = 2 * sum(1 for k in ev["keys"] if k in a["text"]) + sum(1 for w in ev["stems"] if w in a["text"])
            if sc > best_sc:
                best, best_sc = (dd, venue), sc
        if best and best_sc >= 2:
            found[best].append({"press": a["press_name"], "title": a["title"], "link": a["link"], "published": a["published"]})
    first = set()
    for s in speeches:
        k = (s["date"], s["venue"])
        s["articles"] = sorted(found[k], key=lambda x: x["published"]) if k not in first else []
        first.add(k)


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
    related_articles(speeches, (cfg.get("news") or {}).get("press") or {})
    return {
        "meetings": list(reversed(out_meetings)),
        "dotplots": [{"date": m["date"], "rate": m["rate"], **m["dotplot"]} for m in reversed(dots)],
        "next_dotplot": nxt.isoformat() if nxt else None,
        "speeches": speeches,
        "speakers": sorted({s["speaker"] for s in speeches}),
        "venues": sorted({s["venue"] for s in speeches}),
    }
