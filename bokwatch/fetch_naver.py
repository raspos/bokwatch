"""네이버 뉴스 검색 API 수집 → site/data/naver.jsonl (AI 정성 판단 입력)

화면 크롤링 대신 공식 검색 API(NAVER API HUB: naverapihub.apigw.ntruss.com/search/v1/news)를 쓴다.
저장은 API가 주는 제목·요약(description)·링크·시각까지만. 본문은 받지 않는다.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

from .common import KST, SITE_DATA, load_config, now_kst, record_status

NAVER = SITE_DATA / "naver.jsonl"


def clean(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s or "")).split())


def press_from(url: str) -> str:
    m = re.match(r"https?://(?:www\.|m\.)?([^/]+)", url or "")
    return m.group(1) if m else ""


def parse_items(payload: dict, query: str) -> list[dict]:
    out = []
    for it in payload.get("items", []):
        link = it.get("originallink") or it.get("link")
        if not link:
            continue
        try:
            ts = parsedate_to_datetime(it["pubDate"]).astimezone(KST)
        except (KeyError, TypeError, ValueError):
            ts = now_kst()
        out.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "title": clean(it.get("title")),
            "summary": clean(it.get("description"))[:300],
            "link": link,
            "naver_link": it.get("link") if it.get("link") != link else None,
            "press": press_from(link),
            "published": ts.isoformat(timespec="minutes"),
            "queries": [query],
        })
    return out


def norm_title(t: str) -> str:
    """통신사 기사 재전송·제목 미세수정 중복을 잡기 위한 정규화."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|[\"'“”‘’…·,.!?]", "", t)
    return re.sub(r"\s+", "", t)[:40]


def merge(existing: list[dict], new: list[dict], keep_days: int, now: datetime) -> list[dict]:
    by_link = {x["link"]: x for x in existing}
    titles = {norm_title(x["title"]): x for x in existing}
    for x in new:
        if x["link"] in by_link:
            old = by_link[x["link"]]
            old["queries"] = sorted(set(old["queries"]) | set(x["queries"]))
            continue
        dup = titles.get(norm_title(x["title"]))
        if dup:  # 같은 제목 다른 매체 → 하나로, 매체 수만 기록
            dup["dup_press"] = sorted(set(dup.get("dup_press", [])) | {x["press"]})
            dup["queries"] = sorted(set(dup["queries"]) | set(x["queries"]))
            continue
        by_link[x["link"]] = x
        titles[norm_title(x["title"])] = x
    cutoff = now - timedelta(days=keep_days)
    out = [x for x in by_link.values() if datetime.fromisoformat(x["published"]) >= cutoff]
    return sorted(out, key=lambda x: x["published"], reverse=True)


def load() -> list[dict]:
    if not NAVER.exists():
        return []
    return [json.loads(l) for l in NAVER.read_text(encoding="utf-8").splitlines() if l.strip()]


def save(items: list[dict]) -> None:
    NAVER.parent.mkdir(parents=True, exist_ok=True)
    NAVER.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")


def main(argv=None) -> int:
    cfg = load_config()["naver"]
    cid, sec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and sec):
        record_status("naver", False, "NAVER_CLIENT_ID/SECRET 없음")
        print("네이버 API 키 없음", file=sys.stderr)
        return 1
    got, errors = [], []
    for q in cfg["queries"]:
        try:
            r = requests.get(cfg["endpoint"], params={"query": q, "display": cfg["display"], "sort": "date"},
                             headers={"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": sec}, timeout=20)
            r.raise_for_status()
            got += parse_items(r.json(), q)
        except Exception as e:
            errors.append(f"'{q}': {type(e).__name__}: {e}")
    if not got:
        record_status("naver", False, "; ".join(errors) or "0건")
        return 1
    items = merge(load(), got, cfg["keep_days"], now_kst())
    save(items)
    record_status("naver", not errors, "; ".join(errors) or f"{len(got)}건 수신, 보관 {len(items)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
