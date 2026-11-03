"""언론사 도메인 검증: 후보 도메인의 실제 페이지에서 매체명을 확인해 data/press_verified.json에 근거와 함께 남긴다.

도메인은 추측으로 등록하지 않는다. 후보(CANDIDATES)는 검증 대상일 뿐이며, 아래 둘 중 하나로 매체명이 확인될 때만 verified=true다.
 1) 도메인 대표 페이지(https://도메인/)의 <title>·og:site_name·og:title·application-name에 매체명(또는 영문명)이 들어 있음
 2) 우리가 수집한 실제 기사 링크(site/data/naver.jsonl)의 페이지에서 같은 확인
확인하지 못하면 verified=false로 남기고 공식 정성평가에서 그 도메인을 쓰지 않는다(수동 검토 대상).

실행: python -m bokwatch.press_verify
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime

import requests

from .common import DATA, SITE_DATA, now_kst

UA = {"User-Agent": "Mozilla/5.0 (compatible; bokwatch-press-verify/1.0)"}
OUT = DATA / "press_verified.json"

# 후보 도메인(검증 대상). 결과는 아래 검증으로만 확정된다.
CANDIDATES = {
    "chosun": ["chosun.com"], "donga": ["donga.com"], "joongang": ["joongang.co.kr"], "seoul": ["seoul.co.kr"],
    "segye": ["segye.com"], "hankookilbo": ["hankookilbo.com"], "kmib": ["kmib.co.kr"],
    "kbs": ["news.kbs.co.kr"], "mbc": ["imnews.imbc.com"], "sbs": ["news.sbs.co.kr"],
    "sedaily": ["sedaily.com"], "mk": ["mk.co.kr"], "hankyung": ["hankyung.com"], "edaily": ["edaily.co.kr"],
    "etoday": ["etoday.co.kr"], "asiae": ["asiae.co.kr"], "fnnews": ["fnnews.com"], "heraldcorp": ["heraldcorp.com"],
    "ajunews": ["ajunews.com"], "mt": ["mt.co.kr"],
    "jtbc": ["jtbc.co.kr"], "tvchosun": ["news.tvchosun.com"], "channela": ["ichannela.com"],
    "yna": ["yna.co.kr"], "newsis": ["newsis.com"], "news1": ["news1.kr"], "newspim": ["newspim.com"], "einfomax": ["einfomax.co.kr"],
    "etnews": ["etnews.com"], "zdnet": ["zdnet.co.kr"], "inews24": ["inews24.com"],
    "yonhapnewstv": ["yonhapnewstv.co.kr"], "ytn": ["ytn.co.kr"], "sbsbiz": ["biz.sbs.co.kr"],
    "chosunbiz": ["biz.chosun.com"], "econovill": ["econovill.com"], "joseilbo": ["joseilbo.com"], "nocutnews": ["nocutnews.co.kr"],
}


def meta_names(html: str) -> list[str]:
    out = []
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if t:
        out.append(t.group(1))
    for key in ("og:site_name", "og:title", "application-name", "twitter:site", "author", "copyright"):
        for m in re.finditer(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']*)["\']' % re.escape(key), html, re.I):
            out.append(m.group(1))
        for m in re.finditer(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']%s["\']' % re.escape(key), html, re.I):
            out.append(m.group(1))
    return [" ".join(x.split()) for x in out if x and x.strip()]


def norm(s: str) -> str:
    return re.sub(r"[\s\-_·.]", "", s).lower()


def check_page(url: str, names: list[str]) -> dict:
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        r.encoding = r.apparent_encoding or r.encoding
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"{type(e).__name__}"}
    if r.status_code != 200:
        return {"ok": False, "why": f"HTTP {r.status_code}"}
    metas = meta_names(r.text[:200000])
    hay = [norm(m) for m in metas]
    for nm in names:
        n = norm(nm)
        if n and any(n in h for h in hay):
            ev = next(m for m, h in zip(metas, hay) if n in h)
            if ev.startswith("@") or ".com" in ev.lower() and len(ev) < 25:   # 도메인·계정명만 있는 값은 근거로 인정하지 않는다
                continue
            return {"ok": True, "matched": nm, "evidence": ev[:120], "final_url": r.url}
    return {"ok": False, "why": "매체명 없음", "seen": [m[:60] for m in metas[:3]]}


def sample_article(host: str) -> str | None:
    p = SITE_DATA / "naver.jsonl"
    if not p.exists():
        return None
    for line in open(p, encoding="utf-8"):
        try:
            a = json.loads(line)
        except ValueError:
            continue
        h = re.sub(r"^https?://(?:www\.|m\.)?([^/]+).*$", r"\1", a.get("link", ""))
        if h == host or h.endswith("." + host):
            return a["link"]
    return None


def verify_all(outlets: list[dict]) -> dict:
    res = {"checked": now_kst().isoformat(timespec="minutes"), "domains": {}}
    for o in outlets:
        names = [o["name"], o.get("name_en", "")] + [a for a in o.get("aliases", []) if len(a) >= 3]
        for dom in CANDIDATES.get(o["id"], []):
            r = check_page(f"https://{dom}/", names)
            how = "홈페이지"
            if not r["ok"]:
                s = sample_article(dom)
                if s:
                    r2 = check_page(s, names)
                    if r2["ok"]:
                        r, how = r2, "수집 기사 페이지"
            res["domains"][dom] = {"outlet": o["id"], "verified": bool(r["ok"]), "how": how if r["ok"] else None,
                                   "evidence": r.get("evidence"), "why": r.get("why"), "seen": r.get("seen")}
    return res


def main() -> int:
    from .press import load_outlets
    res = verify_all(load_outlets(raw=True))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [d for d, v in res["domains"].items() if v["verified"]]
    bad = [d for d, v in res["domains"].items() if not v["verified"]]
    print(f"검증 {len(ok)}개, 미확인 {len(bad)}개")
    for d in bad:
        print("  미확인:", d, res["domains"][d]["why"], res["domains"][d].get("seen"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
