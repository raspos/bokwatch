"""수집된 원자료 → site/data/*.json 생성.

  python build.py            # 전체 빌드
  python build.py --only news  # 기사 배지 등 가벼운 갱신
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import timedelta

from bokwatch import cd_short, kofr_ois, market
from bokwatch.fetch_cdcurve import load_curve
from bokwatch.common import DATA, SITE_DATA, all_meetings, d, load_config, now_kst, read_json, write_json
from bokwatch.fetch_futures import by_date, load_futures
from bokwatch.fetch_news import load_news
from bokwatch.guidance import build_guidance
from bokwatch.memo import build_memo
from bokwatch.reports import build_reports

SNAP = SITE_DATA / "snapshots"


def build_market(cfg, today):
    rows = market.all_rate_rows()
    spreads = market.estimate_spreads(rows, cfg)
    fut = by_date(load_futures())
    curve = load_curve()
    ois = kofr_ois.OIS(curve, market.series(rows, "cd91"), market.series(rows, "kofr")) if curve else None
    dates = [x for x in market.data_dates(rows, cfg, fut) if x <= today]
    SNAP.mkdir(parents=True, exist_ok=True)
    hist, index, last_cs, last_ko = [], [], None, None
    for day in dates:
        res = market.run_day(rows, cfg, day, spreads, fut_by_date=fut, curve=curve, ois=ois)
        if not res:
            continue
        res["spreads"] = spreads
        last_cs = res["components"].get("cd_short") or last_cs
        last_ko = res["components"].get("kofr_ois") or last_ko
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
    bt = market.backtest(rows, cfg, spreads, fut_by_date=fut)
    write_json(SITE_DATA / "backtest.json", bt)
    if curve:
        cd_short.write_backtest(curve, market.series(rows, "base"), market.meetings_after(cfg, d("2000-01-01")),
                                cfg.get("past_decisions", []), bt.get("rows", []), current=last_cs)
        kofr_ois.write(ois, lambda x: market.kofr_spread(rows, x, cfg)[0], market.meetings_after(cfg, d("2000-01-01")),
                       cfg.get("past_decisions", []), bt.get("rows", []), current=last_ko,
                       cd91_second=lambda obs, m: market.cd91_meeting_at(rows, cfg, obs, m))
    return index


PROB_LOG = DATA / "prob_log.csv"
LOG_FIELDS = ["date", "asof", "status", "meeting", "p_hike", "p_hold", "p_cut", "expected", "instrument", "spread_bp", "note"]


QUAL_WEIGHTS = (0.1, 0.2)


def qual_mix(cur, qual) -> dict | None:
    """실험값 3: CD 모형 + AI 정성 확률(시장 확률을 보지 않고 낸 값) 가중평균. 다음 회의만."""
    qp = (qual or {}).get("probs")
    if not cur or not qp:
        return None
    cd = next((m for m in cur["scenarios"]["0"]["meetings"] if m["in_range"] and m["date"] == qp["meeting"]), None)
    out = {"meeting": qp["meeting"], "qual": {k: qp[k] for k in ("p_hike", "p_hold", "p_cut")}, "reason": qp.get("reason", ""),
           "generated": qp.get("generated")}
    if cd:
        for w in QUAL_WEIGHTS:
            out[f"w{int(w * 100)}"] = {k: round((1 - w) * cd[k] + w * qp[k], 4) for k in ("p_hike", "p_hold", "p_cut")}
    return out


def experimental_note(cur, date_s: str) -> str:
    """기록 비고: 실험값(KOFR 선물, CD·KOFR 혼합, AI 정성 확률·CD+정성) 인상확률."""
    comp = (cur or {}).get("components") or {}
    out = []
    kf = next((m for m in (comp.get("kofr_futures") or {}).get("meetings", []) if m["date"] == date_s), None)
    bl = next((m for m in (comp.get("blend_experimental") or {}).get("meetings", []) if m["date"] == date_s), None)
    ko = next((x for x in (comp.get("kofr_ois") or {}).get("path", []) if x["meeting"] == date_s), None)
    if ko:
        out.append(f"KOFR OIS 자체(실험) {ko['p_hike'] * 100:.1f}%")
    cs_ = (comp.get("cd_short") or {}).get("m1")
    if cs_ and cs_["meeting"] == date_s:
        out.append(f"CD1개월(실험) {cs_['p_hike'] * 100:.1f}%")
    if kf:
        out.append(f"KOFR선물(실험) {kf['p_hike'] * 100:.1f}%")
    if bl:
        out.append(f"혼합(실험) {bl['p_hike'] * 100:.1f}%")
    qm = comp.get("qual_mix")
    if qm and qm["meeting"] == date_s:
        out.append(f"AI정성 {qm['qual']['p_hike'] * 100:.1f}%")
        for w in QUAL_WEIGHTS:
            k = f"w{int(w * 100)}"
            if k in qm:
                out.append(f"CD+정성{int(w * 100)}% {qm[k]['p_hike'] * 100:.1f}%")
    return " · ".join(out)


def update_prob_log(cur, today, stalled: str | None, write: bool) -> list[dict]:
    """매일 화면에 낸 확률을 날짜별로 고정 저장한다(재계산으로 바뀌지 않는 기록).
    write=True(일일 실행)일 때만 오늘 줄을 새로 쓰고, 같은 날 다시 돌리면 오늘 줄만 바꾼다."""
    rows = []
    if PROB_LOG.exists():
        with open(PROB_LOG, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    if write:
        day = today.isoformat()
        rows = [r for r in rows if r["date"] != day]
        if cur and not stalled:
            used = next((i for i in cur["inputs"] if i["used"]), {})
            for m in cur["scenarios"]["0"]["meetings"]:
                if m["in_range"]:
                    rows.append({"date": day, "asof": cur["asof"], "status": "산출", "meeting": m["date"],
                                 "p_hike": m["p_hike"], "p_hold": m["p_hold"], "p_cut": m["p_cut"],
                                 "expected": m["expected"], "instrument": used.get("label", ""),
                                 "spread_bp": round(used.get("spread", 0) * 100, 1),
                                 "note": experimental_note(cur, m["date"])})
        else:
            exp = " / ".join(f"{d(m['date']).month}/{d(m['date']).day} {experimental_note(cur, m['date'])}"
                             for m in ((cur or {}).get("components", {}).get("kofr_futures") or {}).get("meetings", []))
            rows.append({"date": day, "asof": cur["asof"] if cur else "", "status": "중단", "meeting": "",
                         "p_hike": "", "p_hold": "", "p_cut": "", "expected": "", "instrument": "", "spread_bp": "",
                         "note": (stalled or "시장금리 없음") + (f" | 실험값 {exp}" if exp else "")})
        rows.sort(key=lambda r: (r["date"], r["meeting"]))
        with open(PROB_LOG, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, LOG_FIELDS)
            w.writeheader()
            w.writerows(rows)
    return rows


def snap(index, target):
    """target 이하 가장 가까운 스냅샷."""
    c = [x for x in index if x <= target.isoformat()]
    return read_json(SNAP / f"{c[-1]}.json") if c else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["news"], default=None)
    ap.add_argument("--log", action="store_true", help="오늘 확률을 data/prob_log.csv에 기록(일일 실행 전용)")
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
        if cur:  # 실험값 3을 오늘 스냅샷에 붙인다(화면·기록용)
            cur.setdefault("components", {})["qual_mix"] = qual_mix(cur, qual)
            write_json(SNAP / f"{cur['asof']}.json", cur)
        memo = build_memo(now, cur, prev, week, guidance, minutes, reports, events, qual)
        # 시장금리는 들어왔는데 확률을 못 낸 날(투입 상품 만기가 확정 일정 밖) → 멈춤을 알린다
        stalled = None
        if cur and not cur.get("default_ok", True):
            ok = [x for x in index if (read_json(SNAP / f"{x}.json", {}) or {}).get("default_ok", True)]
            last_ok = d(ok[-1]) if ok else None
            stalled = (f"{d(cur['asof']).month}/{d(cur['asof']).day} CD 91일 만기가 확정·가정 일정({cfg.get('assumed_known_through') or cfg['schedule_known_through']}) 밖이라 "
                       "기본 추정치(CD 모형) 산출 중단"
                       + (f". 마지막 산출 {last_ok.month}/{last_ok.day}" if last_ok else "")
                       + ". 다음 해 금통위 일정 공지 후 재개. KOFR 선물 실험값은 계속 표시")
            lines = memo["text"].split("\n")
            lines.insert(2, f"- 산출 중단: {stalled}.")
            memo["text"] = "\n".join(lines)
        write_json(SITE_DATA / "memo.json", memo)
        write_json(SITE_DATA / "prob_log.json", update_prob_log(cur, today, stalled, a.log))

        warnings = [stalled] if stalled else []
        for y, ds in cfg["meetings"].items():
            if not ds:
                warnings.append(f"{y}년 금통위 일정 미입력")
        if cur:
            # 산출 중단 문구를 이미 넣었으면 같은 뜻의 스냅샷 경고는 빼서 겹치지 않게 한다
            warnings += [w for w in cur.get("warnings", []) if not (stalled and "확정 일정" in w)]
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
                                and e.get("importance", 0) >= 3
                                and f"{e['date']} {e.get('time') or '23:59'}" > now.strftime("%Y-%m-%d %H:%M")), None),
            "levels": cfg["model"]["levels"],
            "banner": cfg["site"]["show_internal_banner"],
            "sources": [
                {"name": "한국은행 ECOS Open API", "what": "기준금리(722Y001), 시장금리(817Y002)", "url": "https://ecos.bok.or.kr/"},
                {"name": "한국은행 홈페이지", "what": "통화정책방향 결정문, 금통위 의사록, 기자간담회", "url": "https://www.bok.or.kr/"},
                {"name": "연합뉴스 RSS", "what": "제목·시각·링크·피드 요약", "url": "https://www.yna.co.kr/rss/index"},
                {"name": "BLS·연준·FRED", "what": "미국 CPI·고용 일정, FOMC 일정, 미국 CPI 실제치", "url": "https://www.bls.gov/schedule/"},
                {"name": "네이버 뉴스 검색 API(NAVER API HUB)", "what": "제목·검색 요약·링크(AI 정성 판단 입력)", "url": "https://api.ncloud-docs.com/docs/naver-api-hub-search-news"},
                {"name": "OpenAI API", "what": "기사 태깅·정성 종합 판단(자동, 참고용)", "url": None},
                {"name": "data/reports.yaml", "what": "증권사·IB 전망(수기, 보도 인용)", "url": None},
                {"name": "data/guidance.yaml", "what": "결정·표결·점도표(한은 공보 대조), 발언(보도 인용)", "url": None},
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
