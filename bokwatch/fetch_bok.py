"""한국은행 홈페이지에서 회의별 결정문·기자간담회·의사록을 모아 minutes.json을 만든다.

1차 출처: '통화정책방향 결정회의 일정 및 자료' 연도별 표(회의일 행 × 결정문·기자간담회·의사록 칸, 첨부 PDF).
보조 출처: 금융통화위원회 의사록 목록(게시일·게시물 주소). 목록은 'view.do 링크 + 같은 행의 날짜'만 본다.
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
UA = {"User-Agent": "Mozilla/5.0 (BOK Watch; internal newsroom dashboard)"}
DATE_RE = re.compile(r"(20\d{2})[.\-/년]\s?(\d{1,2})[.\-/월]\s?(\d{1,2})")


# ---------------------------------------------------------------- 날짜 규칙
def minutes_release_date(meeting: date, offset_days: int = 14, override: dict | None = None) -> date:
    """의사록 공개 예정일: 회의일 + offset 이후 첫 화요일 (실측: 회의 18~19일 뒤 화요일).
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


YEAR_COLS = {"결정문": "statement", "기자간담회": "press", "의사록": "minutes"}
MD_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _files(td, base: str) -> list[dict]:
    """칸 안의 첨부(fileDown) → [{name, url}], PDF 먼저."""
    out, seen = [], set()
    for a in td.find_all("a", href=True):
        h = a["href"]
        if "fileDown" not in h:
            continue
        url = urljoin(base, h)
        if url in seen:
            continue
        seen.add(url)
        out.append({"name": " ".join((a.get("title") or a.get_text(" ", strip=True)).split()), "url": url})
    return sorted(out, key=lambda x: not x["name"].lower().endswith(".pdf"))


def parse_meeting_year(html: str, year: int, base: str) -> dict[str, dict]:
    """'통화정책방향 결정회의 일정 및 자료' 연도별 표 → {회의일: {kind: doc}}.
    자료가 아직 없는 회의(미래 회의)도 빈 docs로 돌려준다."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict] = {}
    for table in soup.find_all("table"):
        hdr = [" ".join(th.get_text(" ", strip=True).split()) for th in table.select("thead th")]
        if not hdr or "회의일자" not in hdr[0]:
            continue
        cols = [next((v for k, v in YEAR_COLS.items() if k in h), None) for h in hdr[1:]]
        for tr in table.select("tbody tr"):
            th = tr.find("th")
            m = MD_RE.search(th.get_text(" ", strip=True)) if th else None
            if not m:
                continue
            md = date(year, int(m.group(1)), int(m.group(2)))
            docs = {}
            for kind, td in zip(cols, tr.find_all("td")):
                if not kind:
                    continue
                files = _files(td, base)
                if not files:
                    continue
                view = next((urljoin(base, a["href"]) for a in td.find_all("a", href=True) if "view.do" in a["href"]), None)
                pdf = next((f for f in files if f["name"].lower().endswith(".pdf")), files[0])
                docs[kind] = {"title": re.sub(r"\.(pdf|hwp|hwpx)$", "", pdf["name"], flags=re.I),
                              "posted": md.isoformat() if kind != "minutes" else None,
                              "url": view or pdf["url"], "attachments": files}
            out[md.isoformat()] = {"date": md.isoformat(), "docs": docs}
    return out


def meeting_for_post(kind: str, title: str, posted: date | None, meetings: list[date]):
    """게시물을 회의에 연결. 제목의 날짜를 우선, 없으면 게시일 기준."""
    td = parse_date(title)
    if td:
        # 제목에 회의일이 있으면 그 날짜만 본다. 정책회의가 아닌 금통위(예: 2026-07-23) 의사록을
        # 게시일 창으로 엉뚱한 정책회의에 붙이지 않는다.
        return td if td in meetings else None
    if posted is None:
        return None
    if kind == "minutes":  # 의사록은 회의 7~30일 뒤 게시
        cands = [m for m in meetings if 7 <= (posted - m).days <= 30]
    else:                  # 결정문·간담회는 회의 당일(±1일)
        cands = [m for m in meetings if abs((posted - m).days) <= 1]
    return max(cands) if cands else None


# ---------------------------------------------------------------- 의사록 PDF 분석
# 위원 발언 첫머리: '일부 위원은', '다른 일부 위원은', '또 다른 일부 위원은', '한편(,) 일부 위원은'
_WHO = r"(?:한편\s*,?\s*)?(?:(?:또\s*)?다른\s*)?(?:일부|한)\s*위원(?:은|들은)"
MEMBER_PARA = re.compile(_WHO)
# 위원별 의견 구간: '(4) 한국은행 기준금리 결정에 관한 위원별 의견 개진' ~ '(5) 토의결론'
SECTION_START = [r"위원별\s*의견\s*개진", r"위원별\s*의견", r"정책\s*결정", r"통화정책방향\s*결정"]
SECTION_END = r"\(\s*\d\s*\)\s*토의\s*결론|토의\s*결론"
# PDF 줄바꿈 자리의 공백('적 절', '인상하 는')을 지운 문장에 적용
STANCE = re.compile(r"(인상|인하|동결|유지)(?:하는|하여|해|할)[^.]{0,20}?것(?:이|을)(?:적절|바람직|좋|주장)")


def member_section(text: str) -> str:
    for pat in SECTION_START:  # 앞쪽 '의결안건' 등에 걸리지 않도록 우선순위대로 찾는다
        m = re.search(pat, text)
        if m:
            body = text[m.start():]
            e = re.search(SECTION_END, body)
            return body[:e.start()] if e else body
    return text


def member_paragraphs(text: str) -> list[str]:
    """의사록 텍스트에서 위원별 의견 단락을 뽑는다(정책결정 부분)."""
    body = re.sub(r"[ \t]+", " ", member_section(text))
    parts = re.split(r"\n\s*(?=" + _WHO + ")", body)
    paras = [p.strip().replace("\n", " ") for p in parts if MEMBER_PARA.match(p.strip())]
    return [p for p in paras if len(p) > 40]


def lead_sentence(p: str) -> str:
    """단락 첫 문장('…의견을 나타내었음.' 등)."""
    m = re.search(r"음\s*\.", p)
    return p[: m.end()] if m and m.end() <= 400 else p[:200]


def stance_of(lead: str, lexicon: dict) -> tuple[str, dict]:
    """첫 문장의 '…하는 것이 적절/바람직' 동사로 입장을 정한다. 없으면 사전 빈도."""
    cnt = {k: sum(lead.count(w) for w in ws) for k, ws in lexicon.items()}
    m = STANCE.search(re.sub(r"\s+", "", lead))
    if m:
        v = m.group(1)
        return ("동결" if v == "유지" else v), cnt
    lead_k = max(cnt, key=cnt.get) if any(cnt.values()) else "판단 어려움"
    if any(cnt.values()) and sorted(cnt.values())[-1] == sorted(cnt.values())[-2]:
        lead_k = "판단 어려움"
    return lead_k, cnt


def classify_views(paras: list[str], lexicon: dict) -> dict:
    """위원별 입장(첫 문장 기준). 자동 분류 — 원문 확인 필요."""
    out = []
    totals = {k: 0 for k in lexicon}
    for p in paras:
        lead = lead_sentence(p)
        k, cnt = stance_of(lead, lexicon)
        if k in totals:
            totals[k] += 1
        out.append({"excerpt": lead[:200] + ("…" if len(lead) > 200 else ""), "counts": cnt, "lean": k})
    return {"paragraphs": out, "totals": totals}


def decision_summary(text: str) -> dict:
    """토의결론(만장일치·다수결)과 의결문 단서의 소수의견 위원 실명."""
    t = re.sub(r"\s+", " ", text)
    out = {"result": None, "dissent": []}
    m = re.search(r"토의\s*결론.{0,80}?(만장일치|다수결)", t)
    if m:
        out["result"] = m.group(1)
    for m in re.finditer(r"\(다만,\s*(.{2,40}?)\s*위원은(.{0,200}?)\)", t):
        names = [x.strip() for x in re.split(r"\s*위원과\s*|\s*위원,\s*|,\s*", m.group(1)) if x.strip()]
        names = [re.sub(r"\s+", "", x) for x in names]
        tail = m.group(2)
        view = next((v for v in ("인상", "인하") if re.search(v + r"할 것을 주장", tail)), None) or \
            ("동결" if re.search(r"(동결|유지)할 것을 주장", tail) else None)
        out["dissent"] += [{"name": n, "view": view} for n in names]
    return out


def pdf_text(url: str) -> str:
    import pdfplumber
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


# ---------------------------------------------------------------- 실행
def build_minutes(cfg, boards: dict[str, list[dict]], meetings: list[date], prev: dict | None,
                  attach_fetcher=None, year_docs: dict[str, dict] | None = None) -> dict:
    prev = prev or {}
    prev_ids = {(m["date"], k) for m in prev.get("meetings", []) for k, v in m.get("docs", {}).items() if v}
    bok = cfg["bok"]
    by_meeting: dict[str, dict] = {}
    # 1차 출처(연도별 회의 표). 의사록은 목록 게시물의 게시일·주소를 덧붙인다.
    for md, e in (year_docs or {}).items():
        by_meeting[md] = {"date": md, "docs": {k: dict(v) for k, v in e["docs"].items()}}
    for p in boards.get("minutes", []) if year_docs else []:
        md = meeting_for_post("minutes", p["title"], d(p["posted"]) if p["posted"] else None, meetings)
        doc = by_meeting.get(md.isoformat(), {}).get("docs", {}).get("minutes") if md else None
        if doc:
            doc.update(title=p["title"], posted=p["posted"], url=p["url"])
    if year_docs:
        boards = {}
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
    bok = cfg["bok"]
    prev = read_json(MINUTES_JSON, {}) or {}
    g = load_guidance()
    meetings = sorted({d(x["date"]) for x in cfg.get("past_decisions", [])} |
                      {d(m["date"]) for m in g.get("meetings", [])} |
                      {d(x) for ys in cfg["meetings"].values() for x in (ys or [])})
    errors, notes = [], []

    # 1) 연도별 회의 표: config에 있는 해 + 올해·내년(일정 공지 확인용)
    year_docs: dict[str, dict] = {}
    this_year = now_kst().year
    for y in sorted({m.year for m in meetings} | {this_year, this_year + 1}):
        url = bok["meetings_page"]["url"].format(year=y)
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            got = parse_meeting_year(r.text, y, bok["base"])
            if not got and y <= this_year:
                raise ValueError("회의 0건 — 페이지 구조 변경 의심")
            year_docs.update(got)
        except Exception as e:
            errors.append(f"{bok['meetings_page']['label']} {y}: {type(e).__name__}: {e}")
    # config 일정과 한은 표 대조
    official = {d(x) for x in year_docs}
    years_ok = {d(x).year for x in year_docs}
    extra = sorted(x for x in official - set(meetings))
    missing = sorted(x for x in set(meetings) - official if x.year in years_ok)
    if extra:
        notes.append("config에 없는 한은 회의일: " + ", ".join(x.isoformat() for x in extra))
    if missing:
        notes.append("한은 표에 없는 config 회의일: " + ", ".join(x.isoformat() for x in missing))

    # 2) 의사록 목록(게시일)
    boards = {}
    try:
        r = requests.get(bok["minutes_list"]["url"], headers=UA, timeout=30)
        r.raise_for_status()
        posts = parse_board(r.text, bok["base"])
        if not posts:
            raise ValueError("게시물 0건 — 게시판 구조 변경 의심")
        boards["minutes"] = posts
    except Exception as e:
        errors.append(f"{bok['minutes_list']['label']}: {type(e).__name__}: {e}")

    if not year_docs:
        record_status("bok", False, "; ".join(errors))
        print("한은 수집 실패:", errors, file=sys.stderr)
        return 1
    res = build_minutes(cfg, boards, meetings, prev, year_docs=year_docs)
    # 표를 못 받은 해의 회의는 직전 값 유지
    old = {m["date"]: m for m in prev.get("meetings", [])}
    for e in res["meetings"]:
        if e["date"] not in year_docs:
            for k, v in old.get(e["date"], {}).get("docs", {}).items():
                e["docs"].setdefault(k, v)
    # 의사록 PDF 키워드 분석(최근 회의만)
    lex = cfg["tone"]["minutes_views"]
    with_min = [e for e in res["meetings"] if e["docs"].get("minutes")][: bok.get("views_max_meetings", 2)]
    for e in with_min:
        if "views" in e:
            continue
        atts = e["docs"]["minutes"].get("attachments", [])
        pdfs = [a for a in atts if a["name"].lower().endswith(".pdf")] or atts
        if pdfs:
            try:
                txt = pdf_text(pdfs[0]["url"])
                e["views"] = classify_views(member_paragraphs(txt), lex)
                e["views"].update(decision_summary(txt), source=pdfs[0]["url"])
            except Exception as ex:
                errors.append(f"의사록 PDF {e['date']}: {ex}")
    write_json(MINUTES_JSON, res)
    n_docs = sum(len(e["docs"]) for e in year_docs.values())
    msg = "; ".join(errors + notes) or f"회의 {len(year_docs)}건·자료 {n_docs}건 확인"
    record_status("bok", not errors, msg)
    for x in errors + notes:
        print(x, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
