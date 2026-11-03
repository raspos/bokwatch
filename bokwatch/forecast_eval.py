"""기관·전문가 전망의 수집 현황과 적중률(표본 수 필수 공개).

원칙
- 전망 시점을 통일한다: 금통위 30일·7일·1일 전. 그 시점까지 발표된 전망 중 기관별 가장 최근 것만 쓴다(발표일이 시점 뒤인 전망은 쓰지 않는다).
- 전망을 내지 않은 기관을 동결 전망으로 처리하지 않는다. 시점 안에 전망이 없으면 그 기관은 그 시점 표본에서 빠진다.
- 방향 전망(인상·동결·인하)은 적중률로만 본다. 확률 전망이 있어야 Brier·LogLoss를 낼 수 있고, 지금 수집된 전망은 모두 방향 전망이라 계산하지 않는다.
- BOK WATCH 예측도 같은 시점·같은 회의에서 비교한다(기록이 있는 날만. 사후 재계산·당시 저장 구분을 표시).
- 표본이 작으면 순위를 만들지 않는다(MIN_RANK 회의 미만이면 순위 생략).
"""
from __future__ import annotations

from datetime import date, timedelta

from .common import d

HORIZONS = (30, 7, 1)
MIN_RANK = 5            # 순위를 내려면 필요한 평가 회의 수
CALL = {"인상": "hike", "동결": "hold", "인하": "cut"}
KO = {"hike": "인상", "hold": "동결", "cut": "인하"}


def records(reports: list[dict]) -> list[dict]:
    """reports.yaml 항목 → (기관, 회의, 방향, 발표일) 목록. 같은 기관이 같은 회의를 여러 번 냈으면 모두 남긴다(수정 이력)."""
    out = []
    for r in reports:
        for meeting, c in (r.get("calls") or {}).items():
            call = CALL.get((c or {}).get("call"))
            if call and r.get("published"):
                out.append({"institution": r["institution"], "meeting": str(meeting), "call": call, "published": str(r["published"]),
                            "size": (c or {}).get("size"), "source": r.get("source"), "link": r.get("link"), "verify": bool(r.get("verify"))})
    return out


def latest_before(recs: list[dict], meeting: str, cutoff: date) -> dict[str, dict]:
    """기관별로 cutoff(포함) 이전에 발표된 가장 최근 전망."""
    best: dict[str, dict] = {}
    for x in recs:
        if x["meeting"] != meeting or d(x["published"]) > cutoff:
            continue
        cur = best.get(x["institution"])
        if cur is None or x["published"] > cur["published"]:
            best[x["institution"]] = x
    return best


def revisions(recs: list[dict]) -> list[dict]:
    """같은 기관·같은 회의 전망이 바뀐 이력(방향이 달라진 경우만)."""
    by: dict[tuple, list[dict]] = {}
    for x in recs:
        by.setdefault((x["institution"], x["meeting"]), []).append(x)
    out = []
    for (inst, m), xs in by.items():
        xs.sort(key=lambda x: x["published"])
        for a, b in zip(xs, xs[1:]):
            if a["call"] != b["call"]:
                out.append({"institution": inst, "meeting": m, "from": KO[a["call"]], "to": KO[b["call"]], "date": b["published"]})
    return out


def model_pick(series_day: dict | None) -> dict | None:
    """awm_series 한 날의 M5 확률 → 가장 높은 결과(동률이면 적중으로 치지 않기 위해 None)."""
    if not series_day or not series_day.get("m5"):
        return None
    p = series_day["m5"]
    top = max(p, key=p.get)
    ties = [k for k in p if abs(p[k] - p[top]) < 1e-9]
    return {"top": top if len(ties) == 1 else None, "p": p, "kind": series_day.get("kind")}


def series_before(series: dict, meeting: str, cutoff: date) -> tuple[str | None, dict | None]:
    days = (series.get("meetings") or {}).get(meeting) or {}
    ok = [k for k in days if d(k) <= cutoff]
    k = max(ok) if ok else None
    return k, days.get(k) if k else None


def evaluate(reports: list[dict], outcomes: dict[str, str], series: dict) -> dict:
    """outcomes: 회의일 → hike|hold|cut(이미 결정된 회의). series: site/data/awm_series.json 내용."""
    recs = records(reports)
    meetings = sorted(m for m in outcomes)
    table = []
    for m in meetings:
        md = d(m)
        for H in HORIZONS:
            cut = md - timedelta(days=H)
            best = latest_before(recs, m, cut)
            n = len(best)
            hits = sum(1 for x in best.values() if x["call"] == outcomes[m])
            sk, sd = series_before(series, m, cut)
            mp = model_pick(sd)
            table.append({"meeting": m, "horizon": H, "actual": outcomes[m], "n_institutions": n, "hits": hits,
                          "hit_rate": round(hits / n, 3) if n else None,
                          "bokwatch": ({"asof": sk, "top": mp["top"], "p_actual": round(mp["p"][outcomes[m]], 3), "kind": mp["kind"],
                                        "hit": (mp["top"] == outcomes[m]) if mp["top"] else False} if mp else None)})
    insts = sorted({x["institution"] for x in recs})
    status = []
    for inst in insts:
        mine = [x for x in recs if x["institution"] == inst]
        status.append({"institution": inst, "meetings": sorted({x["meeting"] for x in mine}), "n_forecasts": len(mine),
                       "first": min(x["published"] for x in mine), "last": max(x["published"] for x in mine)})
    evaluated = len({t["meeting"] for t in table if t["n_institutions"]})
    return {
        "horizons": list(HORIZONS), "table": table, "status": status, "revisions": revisions(recs),
        "n_forecasts": len(recs), "n_institutions": len(insts), "meetings_evaluated": evaluated,
        "ranking": None if evaluated < MIN_RANK else "별도 계산",
        "notes": [f"평가된 금통위 {evaluated}회 — 순위는 {MIN_RANK}회 이상일 때만 만든다. 지금은 표본이 작아 확정적 결론을 내지 않는다.",
                  "수집된 전망은 모두 방향 전망(인상·동결·인하)이라 Brier·LogLoss는 계산하지 않는다.",
                  "전망을 내지 않은 기관은 동결로 처리하지 않고 그 시점 표본에서 뺐다.",
                  "기관 전망은 대부분 보도 인용이며 보고서 원문은 확인하지 못했다(verify 표시)."],
    }
