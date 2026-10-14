"""보고 메모 초안 (중앙일보 경제부 내부 메모 형식).

첫 줄 "HH시/E▶" 헤드라인, 다음 줄부터 '-' 문단 5~7개. 마크다운·번호목록 없음.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .common import d

BANNED = ("이는", "이러한", "한편", "할 예정", "살펴볼 계획")


def md(day: str | date) -> str:
    x = d(day)
    return f"{x.month}월 {x.day}일"


def mon(day: str) -> str:
    return f"{d(day).month}월"


def pct(x) -> str:
    if x is None:
        return "-"
    from decimal import ROUND_HALF_UP, Decimal
    return f"{Decimal(str(round(x * 100, 6))).quantize(Decimal('0.1'), ROUND_HALF_UP)}%"


def pp(a, b) -> str:
    if a is None or b is None:
        return ""
    v = (a - b) * 100
    return f"{v:+.1f}%p"


def _meet(snap, scen="0"):
    return [m for m in snap["scenarios"][scen]["meetings"] if m["in_range"]] if snap else []


def _find(snap, date_, scen="0"):
    return next((m for m in _meet(snap, scen) if m["date"] == date_), None)


def headline_flags(cur, prev, minutes_new: bool, gov_count: int) -> list[str]:
    flags = []
    if minutes_new:
        flags.append("[의사록]")
    big = any(p and abs(m["p_hike"] - p["p_hike"]) >= 0.10
              for m in _meet(cur) for p in [_find(prev, m["date"])])
    if big or gov_count >= 3:
        flags.append("[급변]")
    return flags


def build_memo(now: datetime, cur: dict | None, prev: dict | None, week: dict | None,
               guidance: dict, minutes: dict, reports: dict) -> dict:
    lines: list[str] = []
    today = now.date()
    ms = _meet(cur)[:2]
    gov_recent = [s for s in guidance.get("speeches", []) if d(s["date"]) >= today - timedelta(days=1)]
    gov_count = sum(1 for s in gov_recent if "총재" in s["speaker"] and "부총재" not in s["speaker"])
    new_minutes = [m for m in minutes.get("meetings", []) if "minutes" in (m.get("new") or [])]
    flags = headline_flags(cur, prev, bool(new_minutes), gov_count)

    # 헤드라인
    if ms:
        a = ms[0]
        pa = _find(prev, a["date"])
        h = f"{mon(a['date'])} 인상확률 " + (f"{pct(pa['p_hike'])}→{pct(a['p_hike'])}" if pa else pct(a["p_hike"]))
        if len(ms) > 1:
            h += f", {mon(ms[1]['date'])}은 {pct(ms[1]['p_hike'])}"
    else:
        h = "시장금리 미수집, 한은·전문가 동향만 정리"
    head = f"{now.hour:02d}시/E▶" + " ".join(flags + [f"중앙 BOK워치: {h}"])

    # 1. 시장 확률
    if cur:
        sp = next((i for i in cur["inputs"] if i["used"]), None)
        parts = []
        for m in ms:
            p, w = _find(prev, m["date"]), _find(week, m["date"])
            ch = []
            if p:
                ch.append(f"전일 대비 {pp(m['p_hike'], p['p_hike'])}")
            if w:
                ch.append(f"1주 전 대비 {pp(m['p_hike'], w['p_hike'])}")
            parts.append(f"{md(m['date'])} 회의 인상확률 {pct(m['p_hike'])}" + (f"({', '.join(ch)})" if ch else "")
                         + f", 회의 뒤 기대금리 {m['expected']:.2f}%")
        movers = sorted([i for i in cur["inputs"] if i["chg_bp"] is not None], key=lambda i: -abs(i["chg_bp"]))
        mv = ", ".join(f"{i['label']} {i['rate']:.2f}%({i['chg_bp']:+.0f}bp)" for i in movers[:3])
        basis = f"{sp['label']} 기준, 정상 스프레드 {sp['spread'] * 100:.0f}bp 가정" if sp else ""
        txt = f"- 시장 확률({md(cur['asof'])} 종가, {basis}): " + ". ".join(parts) + "."
        txt += f" 금리 움직임은 {mv}." if mv else " 전일 비교 금리 없음."
        lines.append(txt)
    else:
        lines.append("- 시장 확률: 시장금리 수집 실패로 산출하지 못했다.")

    # 2. 총재·한은 발언, 통방문·의사록
    if gov_recent:
        qs = "; ".join(f"{s['speaker']}({s['venue']}) \"{s['quote']}\"" for s in gov_recent[:3])
        lines.append(f"- 한은 발언(24시간 내 {len(gov_recent)}건): {qs}.")
    else:
        last = guidance.get("speeches", [])[:2]
        if last:
            qs = "; ".join(f"{md(s['date'])} {s['speaker']}({s['venue']}) \"{s['quote']}\"" for s in last)
            lines.append(f"- 24시간 내 새 한은 발언은 없다. 최근 발언은 {qs}.")
    if new_minutes:
        m = new_minutes[0]
        v = m.get("views", {}).get("totals")
        vs = f" 위원 단락 키워드는 인상 {v.get('인상', 0)}·동결 {v.get('동결', 0)}·인하 {v.get('인하', 0)}회(자동 추출, 참고용)." if v else ""
        lines.append(f"- {md(m['date'])} 회의 의사록이 공개됐다.{vs}")
    latest_m = next((m for m in guidance.get("meetings", []) if m.get("diff")), None)
    if latest_m and not new_minutes:
        adds = [x["text"] for x in latest_m["diff"] if x["op"] == "add"]
        dels = [x["text"] for x in latest_m["diff"] if x["op"] == "del"]
        if adds or dels:
            t = f"- 직전 통방문({md(latest_m['date'])})은"
            if adds:
                t += f" \"{adds[-1].rstrip('.')}\" 문구를 넣고"
            if dels:
                t += f" \"{dels[-1].rstrip('.')}\" 문구를 뺐다."
            else:
                t += " 다른 문구는 그대로 뒀다."
            if latest_m.get("statement_provisional"):
                t += " 보도 기준이고 원문 대조 전이다."
            lines.append(t)

    # 3. 점도표
    dps = guidance.get("dotplots", [])
    if dps:
        a = dps[0]
        t = (f"- 최신 점도표({md(a['date'])}): 점 {a['n']}개 중간값 {a['median']:.2f}%, "
             f"현 기준금리({a['rate']:.2f}%) 위 {a['above']}개·같음 {a['at']}개·아래 {a['below']}개.")
        if len(dps) > 1:
            b = dps[1]
            t += f" 직전({md(b['date'])}) 중간값 {b['median']:.2f}%에서 {(a['median'] - b['median']) * 100:+.0f}bp 이동."
        if guidance.get("next_dotplot"):
            t += f" 다음 점도표는 {md(guidance['next_dotplot'])} 회의."
        lines.append(t)

    # 4. 보고서·컨센서스
    reps = reports.get("reports", [])
    if reps:
        new = [r for r in reps if r["institution"] in reports.get("new", [])]
        cons = reports["consensus"]["by_meeting"]
        t = "- "
        if new:
            t += "새 전망: " + "; ".join(
                f"{r['institution']}" + (f" {r['author']}" + (f" {r['title']}" if r.get("title") else "") if r.get("author") else "")
                + f" {r['rationale']}" for r in new[:3]) + ". "
        cc = []
        for m in ms:
            c = cons.get(m["date"])
            if c and c["n"]:
                cc.append(f"{mon(m['date'])} 인상 전망 {c['counts'].get('인상', 0)}/{c['n']}곳({pct(c['hike_share'])}) vs 시장 {pct(m['p_hike'])}")
        if cc:
            t += "컨센서스는 " + ", ".join(cc) + "."
        if any(r.get("verify") for r in new):
            t += " 보도 인용 수치라 원문 대조가 필요하다."
        lines.append(t.rstrip())

    # 5. 민감도
    if cur and ms:
        lo, hi = cur["scenarios"].get("-5"), cur["scenarios"].get("5")
        if lo and hi:
            a = ms[0]
            l, h = _find(cur, a["date"], "-5"), _find(cur, a["date"], "5")
            t = f"- 민감도: 정상 스프레드를 5bp 낮추면 {mon(a['date'])} 인상확률 {pct(l['p_hike'])}, 5bp 높이면 {pct(h['p_hike'])}."
            if len(ms) > 1:
                l2, h2 = _find(cur, ms[1]["date"], "-5"), _find(cur, ms[1]["date"], "5")
                t += f" {mon(ms[1]['date'])}은 {pct(l2['p_hike'])}~{pct(h2['p_hike'])}."
            t += " 스프레드 가정에 따라 결과가 크게 갈리는 것으로 풀이된다." if abs(l["p_hike"] - h["p_hike"]) > 0.3 else ""
            lines.append(t)

    # 6. 리스크·관전 포인트
    nxt = ms[0]["date"] if ms else None
    t = "- 관전 포인트:"
    pts = []
    if nxt:
        pts.append(f"{md(nxt)} 회의 결정과 소수의견 수")
    pend = [m for m in minutes.get("meetings", []) if m.get("minutes_status") == "공개 예정"]
    if pend:
        p = min(pend, key=lambda m: m["minutes_expected"])
        pts.append(f"{md(p['date'])} 회의 의사록 공개({md(p['minutes_expected'])} 예정)")
    if guidance.get("next_dotplot"):
        pts.append(f"{md(guidance['next_dotplot'])} 점도표 중간값")
    t += " " + ", ".join(pts) + "." if pts else " 다음 금통위 일정 미입력."
    t += " CD 금리에는 은행 자금사정이 섞여 확률이 과장될 수 있다."
    lines.append(t)

    lines = [l for l in lines if l.strip() != "-"][:7]
    text = head + "\n" + "\n".join(lines)
    return {"text": text, "flags": flags, "generated": now.isoformat(timespec="minutes"),
            "lint": lint(text)}


def lint(text: str) -> list[str]:
    """문체 규칙 위반 점검."""
    probs = [f"금지 표현 '{w}'" for w in BANNED if w in text]
    body = text.splitlines()[1:]
    if not (5 <= len(body) <= 7):
        probs.append(f"문단 수 {len(body)}개(5~7개 필요)")
    if any(not l.startswith("-") for l in body):
        probs.append("'-'로 시작하지 않는 문단")
    if any(c in text for c in ("**", "##", "* ")) or any(re.match(r"\s*-?\s*\d+[.)]\s", l) for l in body):
        probs.append("마크다운·번호목록 의심")
    return probs
