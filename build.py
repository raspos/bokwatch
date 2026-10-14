"""수집된 원자료 → site/data/*.json 생성.

  python build.py            # 전체 빌드
  python build.py --only news  # 기사 배지 등 가벼운 갱신
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import timedelta

from bokwatch import market
from bokwatch.common import SITE_DATA, all_meetings, d, load_config, now_kst, read_json, write_json
from bokwatch.fetch_news import load_news
from bokwatch.guidance import build_guidance
from bokwatch.memo import build_memo
from bokwatch.reports import build_reports

SNAP = SITE_DATA / "snapshots"


def build_market(cfg, today):
    rows = market.all_rate_rows()
    spreads = market.estimate_spreads(rows, cfg)
    dates = [x for x in market.data_dates(rows, cfg) if x <= today]
    SNAP.mkdir(parents=True, exist_ok=True)
    hist, index = [], []
    for day in dates:
        res = market.run_day(rows, cfg, day, spreads)
        if not res:
            continue
        res["spreads"] = spreads
        write_json(SNAP / f"{day.isoformat()}.json", res)
        index.append(day.isoformat())
        for scen, r in res["scenarios"].items():
            for m in r["meetings"]:
                if m["in_range"]:
                    hist.append({"date": day.isoformat(), "scenario": scen, "meeting": m["date"],
                                 "p_hike": m["p_hike"], "p_hold": m["p_hold"], "p_cut": m["p_cut"],
                                 "expected": m["expected"]})
    with open(SITE_DATA / "history.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["date", "scenario", "meeting", "p_hike", "p_hold", "p_cut", "expected"])
        w.writeheader()
        w.writerows(hist)
    write_json(SITE_DATA / "backtest.json", market.backtest(rows, cfg, spreads))
    return index


def snap(index, target):
    """target 이하 가장 가까운 스냅샷."""
    c = [x for x in index if x <= target.isoformat()]
    return read_json(SNAP / f"{c[-1]}.json") if c else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["news"], default=None)
    a = ap.parse_args(argv)
    cfg = load_config()
    now = now_kst()
    today = now.date()
    meta = read_json(SITE_DATA / "meta.json", {}) or {}
    if read_json(SITE_DATA / "status.json") is None:
        write_json(SITE_DATA / "status.json", {})

    news = load_news()
    main_kw = cfg["news"]["main_keyword"]
    # '새 신현송 기사' = 최근 24시간 게재분 (화면에서는 마지막 방문 이후분을 따로 센다)
    cutoff = (now - timedelta(hours=24)).isoformat()
    new_main = [x["id"] for x in news if main_kw in x["keywords"] and x["published"] >= cutoff]

    if a.only != "news":
        index = build_market(cfg, today)
        minutes = read_json(SITE_DATA / "minutes.json")
        if not minutes:  # 한은 수집 전: 일정·공개 예정일만 있는 골격
            from bokwatch.fetch_bok import build_minutes
            from bokwatch.guidance import load_guidance
            ms = sorted({d(x["date"]) for x in load_guidance()["meetings"]} | set(all_meetings(cfg)))
            minutes = build_minutes(cfg, {}, ms, None)
            minutes["skeleton"] = True
            write_json(SITE_DATA / "minutes.json", minutes)
        guidance = build_guidance(cfg, minutes, today)
        write_json(SITE_DATA / "guidance.json", guidance)
        upcoming = [m.isoformat() for m in all_meetings(cfg) if m > today]
        reports = build_reports(upcoming, today)
        write_json(SITE_DATA / "reports.json", reports)

        cur = snap(index, today)
        prev = week = None
        if cur:
            cd = d(cur["asof"])
            prev = snap(index, cd - timedelta(days=1))
            week = snap(index, cd - timedelta(days=7))
            if week and prev and week["asof"] == prev["asof"] and (cd - d(week["asof"])).days < 5:
                week = None
        events = read_json(SITE_DATA / "events.json")
        if not events or events.get("skeleton"):  # 이벤트 수집 전: 금통위·의사록·수기 일정만
            from bokwatch.fetch_events import build_events
            events = build_events(cfg, {}, {}, minutes, today)
            events["skeleton"] = True
            write_json(SITE_DATA / "events.json", events)
        qual = read_json(SITE_DATA / "qual.json", {}) or {}
        memo = build_memo(now, cur, prev, week, guidance, minutes, reports, events, qual)
        write_json(SITE_DATA / "memo.json", memo)

        warnings = []
        for y, ds in cfg["meetings"].items():
            if not ds:
                warnings.append(f"{y}년 금통위 일정 미입력")
        if cur:
            warnings += cur.get("warnings", [])
            if any("수기입력" in i["source"] or "수동" in i["source"] for i in cur["inputs"] if i["used"]):
                warnings.append("시장금리 일부가 수기 입력값(ECOS 대조 필요)")
        meta.update({
            "snapshots": index,
            "latest": cur["asof"] if cur else None,
            "r0": cur["r0"] if cur else None,
            "upcoming": upcoming,
            "warnings": warnings,
            "new_minutes": [m["date"] for m in minutes.get("meetings", []) if "minutes" in (m.get("new") or [])],
            "new_reports": reports["new"],
            "events": [e for e in events.get("all", []) if e["kind"] in cfg["events"]["chart_kinds"]],
            "next_event": next((e for e in events.get("upcoming", []) if e["kind"] not in ("bok", "minutes")
                                and e.get("importance", 0) >= 3), None),
            "levels": cfg["model"]["levels"],
            "banner": cfg["site"]["show_internal_banner"],
            "sources": [
                {"name": "한국은행 ECOS Open API", "what": "기준금리(722Y001), 시장금리(817Y002)", "url": "https://ecos.bok.or.kr/"},
                {"name": "한국은행 홈페이지", "what": "통화정책방향 결정문, 금통위 의사록, 기자간담회", "url": "https://www.bok.or.kr/"},
                {"name": "연합뉴스 RSS", "what": "제목·시각·링크·피드 요약", "url": "https://www.yna.co.kr/rss/index"},
                {"name": "BLS·연준·FRED", "what": "미국 CPI·고용 일정, FOMC 일정, 미국 CPI 실제치", "url": "https://www.bls.gov/schedule/"},
                {"name": "네이버 뉴스 검색 API", "what": "제목·검색 요약·링크(AI 정성 판단 입력)", "url": "https://developers.naver.com/docs/serviceapi/search/news/news.md"},
                {"name": "Anthropic Claude API", "what": "기사 태깅·정성 종합 판단(자동, 참고용)", "url": None},
                {"name": "data/reports.yaml", "what": "증권사·IB 전망(수기, 보도 인용)", "url": None},
                {"name": "data/guidance.yaml", "what": "결정·표결·점도표·발언(수기, 보도 인용)", "url": None},
            ],
        })
    meta["new_main_news"] = new_main
    meta["news_count"] = len(news)
    meta["built"] = now.isoformat(timespec="minutes")
    write_json(SITE_DATA / "meta.json", meta)
    # 기사 목록은 jsonl 그대로 두고 화면용 json도 만든다
    write_json(SITE_DATA / "news.json", {"main_keyword": main_kw, "chips": cfg["news"]["chips"], "items": news})
    print(json.dumps({k: meta.get(k) for k in ("latest", "r0", "warnings", "built")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
