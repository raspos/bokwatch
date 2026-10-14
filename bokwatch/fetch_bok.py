"""한국은행 홈페이지 게시판(의사록·통화정책방향·기자간담회)에서 링크·날짜를 모아 minutes.json을 만든다.

게시판 HTML 구조가 바뀌어도 버티도록 'view.do 링크 + 같은 행의 날짜'만 본다.
실패하면 직전 minutes.json을 유지하고 status.json에 원인을 남긴다.
"""
from __future__ import annotations

import io
import re
import sys
from datetime import date, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .common import SITE_DATA, d, load_config, now_kst, read_json, record_status, write_json

MINUTES_JSON = SITE_DATA / "minutes.json"
UA = {"User-Agent": "Mozilla/5.0 (JoongAng BOK Watch; internal newsroom dashboard)"}
DATE_RE = re.compile(r"(20\d{2})[.\-/년]\s?(\d{1,2})[.\-/월]\s?(\d{1,2})")


# ---------------------------------------------------------------- 날짜 규칙
def minutes_release_date(meeting: date, offset_days: int = 12, override: dict | None = None) -> date:
    """의사록 공개 예정일: 회의일 + offset 이후 첫 화요일 (통상 회의 약 2주 뒤 화요일).
    한은 공지(override)가 있으면 그 날짜."""
    if override and meeting.isoformat() in override:
        return d(override[meeting.isoformat()])
    t = meeting + timedelta(days=offset_days)
    return t + timedelta(days=(1 - t.weekday()) % 7)  # 화요일=1


def parse_date(text: str):
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------- 게시판 파싱
def parse_board(html: str, base: str) -> list[dict]:
    """목록 페이지 → [{title, posted, url}]"""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "view.do" not in href and "nttId" not in href:
            continue
        url = urljoin(base, href)
        if url in seen:
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title:
            continue
        row = a.find_parent(["li", "tr"]) or a.parent
        posted = None
        # 날짜 전용 칸을 먼저, 없으면 행 전체 텍스트에서
        for el in row.select(".date, .td_date, td.date, span.date"):
            posted = parse_date(el.get_text())
            if posted:
                break
        posted = posted or parse_date(row.get_text(" "))
        seen.add(url)
        out.append({"title": title, "posted": posted.isoformat() if posted else None, "url": url})
    return out


def parse_attachments(html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        h, t = a["href"], a.get_text(" ", strip=True)
        if re.search(r"fileDown|FileDown|download|\.pdf", h, re.I) or t.lower().endswith(".pdf"):
            out.append({"name": t or "첨부", "url": urljoin(base, h)})
    return out


def meeting_for_post(kind: str, title: str, posted: date | None, meetings: list[date]):
    """게시물을 회의에 연결. 제목의 날짜를 우선, 없으면 게시일 기준."""
    td = parse_date(title)
    if td and td in meetings:
        return td
    if posted is None:
        return None
    if kind == "minutes":  # 의사록은 회의 7~30일 뒤 게시
        cands = [m for m in meetings if 7 <= (posted - m).days <= 30]
    else:                  # 결정문·간담회는 회의 당일(±1일)
        cands = [m for m in meetings if abs((posted - m).days) <= 1]
    return max(cands) if cands else None


# ---------------------------------------------------------------- 의사록 PDF 분석
_WHO = r"(?:(?:또\s*)?다른\s*)?(?:일부|한|[가-힣]{2,4})\s*위원(?:은|들은)"
MEMBER_PARA = re.compile(_WHO)


def member_paragraphs(text: str) -> list[str]:
    """의사록 텍스트에서 위원 발언 단락을 뽑는다(정책결정 부분 우선)."""
    text = re.sub(r"[ \t]+", " ", text)
    m = re.search(r"(정책\s*결정|통화정책방향\s*결정|위원별\s*의견|의결안)", text)
    body = text[m.start():] if m else text
    parts = re.split(r"\n\s*(?=(?:\(?\d+\)?\s*)?" + _WHO + ")", body)
    paras = [p.strip().replace("\n", " ") for p in parts if MEMBER_PARA.match(p.strip())]
    return [p for p in paras if len(p) > 40]


def classify_views(paras: list[str], lexicon: dict) -> dict:
    """단락별 인상/동결/인하 키워드 빈도. 자동 분류 — 참고용."""
    out = []
    totals = {k: 0 for k in lexicon}
    for p in paras:
        cnt = {k: sum(p.count(w) for w in ws) for k, ws in lexicon.items()}
        for k, v in cnt.items():
            totals[k] += v
        lead = max(cnt, key=cnt.get) if any(cnt.values()) else "판단 어려움"
        out.append({"excerpt": p[:160] + ("…" if len(p) > 160 else ""), "counts": cnt, "lean": lead})
    return {"paragraphs": out, "totals": totals}


def pdf_text(url: str) -> str:
    import pdfplumber
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


# ---------------------------------------------------------------- 실행
def build_minutes(cfg, boards: dict[str, list[dict]], meetings: list[date], prev: dict | None,
                  attach_fetcher=None) -> dict:
    prev = prev or {}
    prev_ids = {(m["date"], k) for m in prev.get("meetings", []) for k, v in m.get("docs", {}).items() if v}
    bok = cfg["bok"]
    by_meeting: dict[str, dict] = {}
    for kind, posts in boards.items():
        for p in posts:
            md = meeting_for_post(kind, p["title"], d(p["posted"]) if p["posted"] else None, meetings)
            if not md:
                continue
            entry = by_meeting.setdefault(md.isoformat(), {"date": md.isoformat(), "docs": {}})
            if kind not in entry["docs"]:
                doc = dict(p)
                if attach_fetcher:
                    try:
                        doc["attachments"] = attach_fetcher(p["url"])
                    except Exception as e:  # 첨부 실패는 무시
                        doc["attachments"] = []
                        doc["attach_error"] = str(e)[:100]
                entry["docs"][kind] = doc
    today = now_kst().date()
    out = []
    for m in meetings:
        if m > today + timedelta(days=60):
            continue
        e = by_meeting.get(m.isoformat(), {"date": m.isoformat(), "docs": {}})
        rel = minutes_release_date(m, bok["minutes_release_offset_days"], bok.get("minutes_release_override"))
        e["minutes_expected"] = rel.isoformat()
        e["minutes_status"] = "공개" if "minutes" in e["docs"] else ("공개 예정" if rel >= today else "확인 필요")
        e["new"] = [k for k in e["docs"] if (e["date"], k) not in prev_ids] if prev and not prev.get("skeleton") else []
        out.append(e)
    out.sort(key=lambda x: x["date"], reverse=True)
    # 직전 결과의 키워드 분석은 보존
    old = {m["date"]: m for m in prev.get("meetings", [])}
    for e in out:
        if "views" in old.get(e["date"], {}) and "views" not in e:
            e["views"] = old[e["date"]]["views"]
    return {"updated": now_kst().isoformat(timespec="minutes"), "meetings": out}


def main(argv=None) -> int:
    from .guidance import load_guidance
    cfg = load_config()
    prev = read_json(MINUTES_JSON, {}) or {}
    g = load_guidance()
    meetings = sorted({d(x["date"]) for x in cfg.get("past_decisions", [])} |
                      {d(m["date"]) for m in g.get("meetings", [])} |
                      {d(x) for ys in cfg["meetings"].values() for x in (ys or [])})
    boards, errors = {}, []
    for kind, b in cfg["bok"]["boards"].items():
        try:
            r = requests.get(b["url"], headers=UA, timeout=30)
            r.raise_for_status()
            posts = parse_board(r.text, cfg["bok"]["base"])
            if not posts:
                raise ValueError("게시물 0건 — 게시판 구조 변경 의심")
            boards[kind] = posts
        except Exception as e:
            errors.append(f"{b['label']}: {type(e).__name__}: {e}")

    def fetch_attach(url):
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        return parse_attachments(r.text, cfg["bok"]["base"])

    if not boards:
        record_status("bok", False, "; ".join(errors))
        print("한은 수집 실패:", errors, file=sys.stderr)
        return 1
    # 일부 게시판만 실패하면 그 종류는 직전 값 유지
    res = build_minutes(cfg, boards, meetings, prev, fetch_attach)
    if errors:
        old = {m["date"]: m for m in prev.get("meetings", [])}
        for e in res["meetings"]:
            for k, v in old.get(e["date"], {}).get("docs", {}).items():
                e["docs"].setdefault(k, v)
    # 새 의사록 PDF 키워드 분석
    lex = cfg["tone"]["minutes_views"]
    for e in res["meetings"]:
        doc = e["docs"].get("minutes")
        if doc and "views" not in e:
            pdfs = [a for a in doc.get("attachments", []) if a["url"].lower().endswith(".pdf") or "pdf" in a["name"].lower()]
            pdfs = pdfs or doc.get("attachments", [])
            if pdfs:
                try:
                    e["views"] = classify_views(member_paragraphs(pdf_text(pdfs[0]["url"])), lex)
                    e["views"]["source"] = pdfs[0]["url"]
                except Exception as ex:
                    errors.append(f"의사록 PDF {e['date']}: {ex}")
    write_json(MINUTES_JSON, res)
    record_status("bok", not errors, "; ".join(errors) or f"{sum(len(v) for v in boards.values())}건 확인")
    return 0


if __name__ == "__main__":
    sys.exit(main())
