"""연합뉴스 RSS 수집·필터 → site/data/news.jsonl (링크 기준 중복 제거, 90일 유지).

저작권: 본문 전문은 받지도 저장하지도 않는다. 제목·시각·링크·피드 제공 요약만.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

from .common import KST, SITE_DATA, load_config, now_kst, record_status

NEWS = SITE_DATA / "news.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (BOK Watch RSS reader)"}


def _clean(s: str, n: int | None = None) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = " ".join(s.split())
    return s[:n] + "…" if n and len(s) > n else s


def parse_feed(xml: str, feed_name: str) -> list[dict]:
    import feedparser
    fp = feedparser.parse(xml)
    out = []
    for e in fp.entries:
        link = e.get("link", "").strip()
        if not link:
            continue
        ts = None
        for k in ("published", "updated", "pubDate"):
            if e.get(k):
                try:
                    ts = parsedate_to_datetime(e[k])
                except (TypeError, ValueError):
                    try:
                        ts = datetime.fromisoformat(e[k])
                    except ValueError:
                        pass
                if ts:
                    break
        if ts is None:
            ts = now_kst()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        out.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "title": _clean(e.get("title", "")),
            "published": ts.astimezone(KST).isoformat(timespec="minutes"),
            "link": link,
            "feed": feed_name,
            "summary": _clean(e.get("summary", "") or e.get("description", ""), 200),
        })
    return out


def match_keywords(item: dict, main_kw: str, chips: list[str]) -> list[str]:
    text = f"{item['title']} {item['summary']}"
    norm = text.replace(" ", "")
    return [k for k in [main_kw] + chips if k.replace(" ", "") in norm]


def merge(existing: list[dict], new: list[dict], keep_days: int, now: datetime) -> list[dict]:
    by_link = {x["link"]: x for x in existing}
    for x in new:
        if x["link"] in by_link:
            old = by_link[x["link"]]
            old["feeds"] = sorted(set(old.get("feeds", [old["feed"]])) | {x["feed"]})
            old["keywords"] = sorted(set(old["keywords"]) | set(x["keywords"]),
                                     key=lambda k: (k != x["keywords"][0] if x["keywords"] else 0, k))
        else:
            by_link[x["link"]] = x
    cutoff = now - timedelta(days=keep_days)
    out = [x for x in by_link.values() if datetime.fromisoformat(x["published"]) >= cutoff]
    return sorted(out, key=lambda x: x["published"], reverse=True)


def load_news() -> list[dict]:
    if not NEWS.exists():
        return []
    return [json.loads(l) for l in NEWS.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_news(items: list[dict]) -> None:
    NEWS.parent.mkdir(parents=True, exist_ok=True)
    NEWS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")


def main(argv=None) -> int:
    cfg = load_config()["news"]
    got, errors = [], []
    for f in cfg["feeds"]:
        try:
            r = requests.get(f["url"], headers=UA, timeout=20)
            r.raise_for_status()
            items = parse_feed(r.content, f["name"])
            if not items:
                raise ValueError("항목 0건")
            got += items
        except Exception as e:
            errors.append(f"{f['name']}: {type(e).__name__}: {e}")
    if not got:
        record_status("news", False, "; ".join(errors))
        print("RSS 수집 실패:", errors, file=sys.stderr)
        return 1
    matched = []
    for x in got:
        kws = match_keywords(x, cfg["main_keyword"], cfg["chips"])
        if kws:
            matched.append(dict(x, keywords=kws))
    items = merge(load_news(), matched, cfg["keep_days"], now_kst())
    save_news(items)
    record_status("news", not errors, "; ".join(errors) or f"피드 {len(got)}건 중 {len(matched)}건 매칭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
