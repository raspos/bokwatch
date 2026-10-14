"""경제지표·이벤트 캘린더 수집 → site/data/events.json

일정
  - 미국 CPI·고용보고서: BLS 발표 일정 페이지 (시각은 미 동부 → KST 변환)
  - FOMC: 연준 FOMC 일정 페이지 (결정 발표 = 회의 둘째 날 14:00 ET)
  - 금통위·의사록 공개: config·minutes.json에서
  - 한국 CPI·GDP·수출입 등: data/events.yaml 수기 입력 (공식 일정 페이지 구조 미확인)
실제치
  - 미국 CPI·근원 CPI: FRED (CPIAUCNS, CPILFENS 원계열) 전년동월비
  - 한국 CPI·근원(농산물·석유류 제외): ECOS 901Y009 전년동월비
실패한 소스는 직전 값을 유지한다.
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .common import (DATA, SITE_DATA, KST, all_meetings, d, load_config, load_yaml, now_kst,
                     read_json, record_status, write_json)

EVENTS_JSON = SITE_DATA / "events.json"
ET = ZoneInfo("America/New_York")
# BLS는 Accept·Accept-Language가 없으면 403을 준다(2026-10-14 확인).
UA = {"User-Agent": "Mozilla/5.0 (BOK Watch newsroom calendar; contact via repo)",
      "Accept": "text/html,application/xhtml+xml,text/csv;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def et_to_kst(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), ET).astimezone(KST)


def _month(s: str) -> int | None:
    return MONTHS.get(s.strip(". ").lower()[:3])


# ---------------------------------------------------------------- BLS
DATE_EN = re.compile(r"([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),\s*(\d{4})")
TIME_EN = re.compile(r"(\d{1,2}):(\d{2})\s*([AP])\.?M", re.I)
REFM = re.compile(r"([A-Z][a-z]{2,8})\.?\s+(\d{4})")


def parse_bls_schedule(html: str) -> list[dict]:
    """BLS 'Schedule of Releases' 표 → [{ref_month, release_kst}]"""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        ref = REFM.search(cells[0])
        rel = next((DATE_EN.search(c) for c in cells[1:] if DATE_EN.search(c)), None)
        if not (ref and rel and _month(ref.group(1)) and _month(rel.group(1))):
            continue
        tm = next((TIME_EN.search(c) for c in cells[1:] if TIME_EN.search(c)), None)
        hh, mm = (8, 30)
        if tm:
            hh, mm = int(tm.group(1)) % 12 + (12 if tm.group(3).upper() == "P" else 0), int(tm.group(2))
        rd = date(int(rel.group(3)), _month(rel.group(1)), int(rel.group(2)))
        out.append({"ref_month": f"{ref.group(2)}-{_month(ref.group(1)):02d}", "release": et_to_kst(rd, hh, mm)})
    return out


def parse_bls_ics(text: str, summary: str) -> list[dict]:
    """BLS 캘린더(bls.ics) → [{release}] (summary 정확 일치). 일정표 페이지는 당일·지난 발표를 빼고 보여 주므로
    당일 발표는 ics로 보강한다. ics에는 기준월이 없다."""
    out = []
    for block in text.split("BEGIN:VEVENT")[1:]:
        s = re.search(r"^SUMMARY:(.*)$", block, re.M)
        m = re.search(r"^DTSTART[^:\n]*:(\d{8})T(\d{2})(\d{2})", block, re.M)
        if not (s and m) or s.group(1).strip() != summary:
            continue
        day = datetime.strptime(m.group(1), "%Y%m%d").date()
        out.append({"release": et_to_kst(day, int(m.group(2)), int(m.group(3)))})
    return out


# ---------------------------------------------------------------- FOMC
def parse_fomc(html: str) -> list[dict]:
    """연준 FOMC 일정 → [{start, end, decision_kst, sep(점도표 여부)}]"""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for panel in soup.select(".panel"):
        head = panel.find(["h4", "h5", "a"], string=re.compile(r"\d{4} FOMC Meetings")) or \
            panel.find(string=re.compile(r"(\d{4}) FOMC Meetings"))
        if not head:
            continue
        year = int(re.search(r"(\d{4})", head if isinstance(head, str) else head.get_text()).group(1))
        for row in panel.select(".fomc-meeting"):
            mon = row.select_one(".fomc-meeting__month")
            dd = row.select_one(".fomc-meeting__date")
            if not (mon and dd):
                continue
            mtxt, dtxt = mon.get_text(" ", strip=True), dd.get_text(" ", strip=True)
            mons = [m for m in (_month(x) for x in re.split(r"[/\-\s]+", mtxt)) if m]
            days = [int(x) for x in re.findall(r"\d{1,2}", dtxt)]
            if not mons or not days:
                continue
            m_end = mons[-1]
            end = date(year, m_end, days[-1])
            start = date(year, mons[0], days[0])
            out.append({"start": start, "end": end, "sep": "*" in dtxt,
                        "unscheduled": "unscheduled" in dtxt.lower() or "notation" in dtxt.lower(),
                        "decision": et_to_kst(end, 14, 0)})
    return [x for x in out if not x["unscheduled"]]


# ---------------------------------------------------------------- 실제치
def r1(x: float) -> float:
    """공표 방식대로 소수 첫째 자리 한 번만 반올림(사사오입). 2.44598 → 2.4 (2.45를 거쳐 2.5가 되지 않게)."""
    from decimal import ROUND_HALF_UP, Decimal
    return float(Decimal(repr(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def yoy_from_series(points: list[tuple[str, float]]) -> dict | None:
    """[(YYYY-MM, 지수)] → 최신 전년동월비와 직전 달 전년동월비."""
    ser = dict(points)
    months = sorted(ser)
    out = []
    for m in months:
        y, mo = int(m[:4]), int(m[5:7])
        prev = f"{y - 1}-{mo:02d}"
        if prev in ser and ser[prev]:
            out.append((m, (ser[m] / ser[prev] - 1) * 100))
    if not out:
        return None
    last = out[-1]
    return {"month": last[0], "yoy": r1(last[1]), "prev_month": out[-2][0] if len(out) > 1 else None,
            "prev_yoy": r1(out[-2][1]) if len(out) > 1 else None}


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in ("", "."):
            out.append((r[0][:7], float(r[1])))
    return out


def fred(series_id: str) -> list[tuple[str, float]]:
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", headers=UA, timeout=30)
    r.raise_for_status()
    return parse_fred_csv(r.text)


BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def parse_bls_api(j: dict) -> dict[str, list[tuple[str, float]]]:
    """BLS API 응답 → {시리즈: [(YYYY-MM, 지수)]}. 값이 '-'(미발표·결측)인 달과 연간(M13)은 뺀다."""
    if j.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS API: {j.get('status')} {j.get('message')}")
    out = {}
    for s in j["Results"]["series"]:
        pts = []
        for x in s["data"]:
            if x["period"].startswith("M") and x["period"] != "M13":
                try:
                    pts.append((f"{x['year']}-{x['period'][1:]}", float(x["value"])))
                except ValueError:
                    continue
        out[s["seriesID"]] = sorted(pts)
    return out


def bls_cpi() -> dict[str, list[tuple[str, float]]]:
    """BLS 공식 API(키 없이 하루 25회): CPI-U 전체(CUUR0000SA0)·근원(CUUR0000SA0L1E), 계절조정 전.
    FRED CPIAUCNS·CPILFENS와 같은 지수이고, 발표 직후 바로 반영된다."""
    y = now_kst().year
    r = requests.post(BLS_API, json={"seriesid": ["CUUR0000SA0", "CUUR0000SA0L1E"], "startyear": str(y - 2), "endyear": str(y)},
                      headers={**UA, "Content-type": "application/json"}, timeout=60)
    r.raise_for_status()
    return parse_bls_api(r.json())


def ecos_cpi(cfg) -> dict:
    from .fetch_rates import ecos_get, match_items
    c = cfg["events"]["kr_cpi_ecos"]
    end = now_kst().strftime("%Y%m")
    start = f"{now_kst().year - 2}01"
    out = {}
    for k, it in c["items"].items():
        rows = [r for r in ecos_get(cfg, "StatisticItemList", [it["stat"]]) if r.get("CYCLE") == "M"]
        hit = match_items(rows, [{"id": k, "match": it["match"]}]).get(k)
        if not hit:
            raise ValueError(f"ECOS {it['stat']}에서 '{it['match']}' 항목을 찾지 못함")
        code = hit[0]
        rows = ecos_get(cfg, "StatisticSearch", [it["stat"], "M", start, end, code])
        pts = [(f"{r['TIME'][:4]}-{r['TIME'][4:6]}", float(r["DATA_VALUE"])) for r in rows if r.get("DATA_VALUE")]
        out[k] = yoy_from_series(pts)
    return out


# ---------------------------------------------------------------- 묶기
def ev(dt: datetime | date, label: str, country: str, kind: str, importance: int, source: str, **kw) -> dict:
    if isinstance(dt, datetime):
        day, tm = dt.date().isoformat(), dt.strftime("%H:%M")
    else:
        day, tm = dt.isoformat(), kw.pop("time", None)
    return {"date": day, "time": tm, "label": label, "country": country, "kind": kind,
            "importance": importance, "source": source, **kw}


def internal_events(cfg, minutes: dict) -> list[dict]:
    out = [ev(m, "금통위 통화정책방향 결정", "KR", "bok", 3, "config") for m in all_meetings(cfg)]
    for m in (minutes or {}).get("meetings", []):
        if m.get("minutes_expected"):
            out.append(ev(d(m["minutes_expected"]), f"금통위 의사록 공개({md(m['date'])} 회의)", "KR", "minutes", 2,
                          "규칙 계산" if "minutes" not in m.get("docs", {}) else "한은",
                          verify="minutes" not in m.get("docs", {})))
    return out


def md(s) -> str:
    x = d(s)
    return f"{x.month}/{x.day}"


def manual_events() -> list[dict]:
    y = load_yaml("events.yaml")
    out = []
    for e in y.get("events", []) or []:
        out.append({"date": str(e["date"]), "time": e.get("time"), "label": e["label"],
                    "country": e.get("country", "KR"), "kind": e.get("kind", "custom"),
                    "importance": int(e.get("importance", 2)), "source": e.get("source", "수기 입력"),
                    "verify": bool(e.get("verify", False)), "link": e.get("link")})
    return out


def build_events(cfg, scraped: dict, indicators: dict, minutes: dict, today: date) -> dict:
    evs = list(scraped.get("us_cpi", [])) + list(scraped.get("us_jobs", [])) + list(scraped.get("fomc", []))
    evs += internal_events(cfg, minutes) + manual_events()
    # 같은 날짜·라벨 중복 제거(수기 입력이 우선)
    uniq = {}
    for e in evs:
        uniq[(e["date"], e["label"])] = e
    evs = sorted(uniq.values(), key=lambda e: (e["date"], e.get("time") or "99"))
    lookahead = cfg["events"].get("lookahead_days", 45)
    lookback = cfg["events"].get("lookback_days", 30)
    for e in evs:
        e["status"] = "지남" if e["date"] < today.isoformat() else ("오늘" if e["date"] == today.isoformat() else "예정")
    return {
        "updated": now_kst().isoformat(timespec="minutes"),
        "upcoming": [e for e in evs if today.isoformat() <= e["date"] <= (today + timedelta(days=lookahead)).isoformat()],
        "recent": [e for e in evs if (today - timedelta(days=lookback)).isoformat() <= e["date"] < today.isoformat()][::-1],
        "all": [e for e in evs if e["date"] >= (today - timedelta(days=400)).isoformat()],
        "indicators": indicators,
    }


def attach_consensus(indicators: dict) -> None:
    """data/consensus.yaml의 시장 예상치를 실제치와 같은 기준월일 때만 붙인다."""
    try:
        cons = load_yaml("consensus.yaml")
    except FileNotFoundError:
        return
    for key, ind in indicators.items():
        ind.pop("consensus", None)
        hit = next((c for c in (cons.get(key) or []) if str(c.get("month")) == ind.get("month")), None)
        if hit:
            ind["consensus"] = {k: hit.get(k) for k in ("yoy", "core_yoy", "source", "link")}


def main(argv=None) -> int:
    cfg = load_config()
    ec = cfg["events"]
    prev = read_json(EVENTS_JSON, {}) or {}
    prev_all = prev.get("all", [])
    scraped, errors = {}, []

    def keep(kind):  # 실패 시 직전 값
        return [e for e in prev_all if e.get("kind") == kind and e.get("source", "").startswith(("BLS", "Fed"))]

    ics = None
    if ec.get("bls_ics_url"):
        try:
            r = requests.get(ec["bls_ics_url"], headers=UA, timeout=30)
            r.raise_for_status()
            ics = r.text
        except Exception as e:
            errors.append(f"BLS 캘린더: {type(e).__name__}: {e}")
    for key, url, label, kind, summary in [("us_cpi", ec["bls_cpi_url"], "미국 CPI", "cpi", "Consumer Price Index"),
                                           ("us_jobs", ec["bls_jobs_url"], "미국 고용보고서", "jobs", "Employment Situation")]:
        imp = 3 if kind == "cpi" else 2
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            rows = parse_bls_schedule(r.text)
            if not rows:
                raise ValueError("일정 0건 — 페이지 구조 변경 의심")
            scraped[key] = [ev(x["release"], f"{label}({int(x['ref_month'][5:])}월분)", "US", kind,
                               imp, "BLS", ref_month=x["ref_month"]) for x in rows]
        except Exception as e:
            errors.append(f"{label} 일정: {type(e).__name__}: {e}")
            scraped[key] = [x for x in keep(kind) if x["country"] == "US"]
        if ics:  # 일정표에 없는 날(당일·지난 발표)만 보강. 기준월은 붙이지 않는다.
            have = {x["date"] for x in scraped[key]}
            scraped[key] += [ev(x["release"], f"{label} 발표", "US", kind, imp, "BLS 캘린더")
                             for x in parse_bls_ics(ics, summary) if x["release"].date().isoformat() not in have]
    try:
        r = requests.get(ec["fomc_url"], headers=UA, timeout=30)
        r.raise_for_status()
        rows = parse_fomc(r.text)
        if not rows:
            raise ValueError("일정 0건 — 페이지 구조 변경 의심")
        scraped["fomc"] = [ev(x["decision"], "FOMC 결정" + (" (점도표·SEP)" if x["sep"] else ""), "US", "fomc", 3,
                              "Fed", meeting=f"{x['start']}~{x['end']}") for x in rows]
    except Exception as e:
        errors.append(f"FOMC 일정: {type(e).__name__}: {e}")
        scraped["fomc"] = keep("fomc")

    indicators = dict(prev.get("indicators", {}))
    us = core = None
    try:  # BLS 공식 API 우선(발표 직후 반영), 실패하면 FRED
        b = bls_cpi()
        us, core = yoy_from_series(b["CUUR0000SA0"]), yoy_from_series(b["CUUR0000SA0L1E"])
        src = "BLS CPI-U CUUR0000SA0·CUUR0000SA0L1E (계절조정 전, 전년동월비)"
    except Exception as e:
        errors.append(f"BLS API: {type(e).__name__}: {e} → FRED로 대체")
        try:
            us, core = yoy_from_series(fred("CPIAUCNS")), yoy_from_series(fred("CPILFENS"))
            src = "FRED CPIAUCNS·CPILFENS (BLS 원계열, 전년동월비)"
        except Exception as e2:
            errors.append(f"FRED: {type(e2).__name__}: {e2}")
    if us:
        indicators["us_cpi"] = {**us, "core_yoy": core["yoy"] if core and core["month"] == us["month"] else None,
                                "prev_core_yoy": core.get("prev_yoy") if core and core["month"] == us["month"] else None,
                                "source": src, "label": "미국 CPI"}
    if os.environ.get(cfg["ecos"]["key_env"]):
        try:
            kr = ecos_cpi(cfg)
            if kr.get("headline"):
                indicators["kr_cpi"] = {**kr["headline"], "core_yoy": (kr.get("core") or {}).get("yoy"),
                                        "source": "ECOS 901Y009 총지수·901Y010 식료품 및 에너지 제외(전년동월비)",
                                        "label": "한국 CPI"}
        except Exception as e:
            errors.append(f"ECOS CPI: {type(e).__name__}: {e}")
    else:
        errors.append("ECOS CPI: ECOS_API_KEY 없음")

    attach_consensus(indicators)
    minutes = read_json(SITE_DATA / "minutes.json", {}) or {}
    write_json(EVENTS_JSON, build_events(cfg, scraped, indicators, minutes, now_kst().date()))
    record_status("events", not errors, "; ".join(errors) or "정상")
    if errors:
        print("일부 실패:", errors, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
