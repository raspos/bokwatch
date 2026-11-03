"""언론사 화이트리스트와 기사 출처 판정.

- 허용 38곳은 data/press.yaml, 검증된 도메인은 data/press_verified.json(press_verify가 만든다)에서 읽는다.
- 기사 출처는 '포털'이 아니라 원래 기사를 낸 언론사로 판정한다. 포털(네이버·다음·구글 등) 링크만 있고 원출처를 확인할 수 없으면 제외하고 검토 대상으로 남긴다.
- 도메인은 가장 구체적인 것(서브도메인 포함)부터 맞춘다. 예: biz.chosun.com은 조선비즈, chosun.com은 조선일보.
"""
from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

from .common import DATA, load_yaml, read_json

PORTAL_HOSTS = ("news.naver.com", "n.news.naver.com", "m.news.naver.com", "naver.com", "v.daum.net", "news.daum.net", "daum.net",
                "news.google.com", "google.com", "news.nate.com", "nate.com", "msn.com", "zum.com")
EXPECTED_COUNT = 38


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/:?#]+)", url or "")
    h = m.group(1).lower() if m else ""
    return re.sub(r"^(www|m|mobile)\.", "", h)


def load_outlets(raw: bool = False) -> list[dict]:
    """허용 언론사 목록. raw=False면 검증된 도메인(domains)을 붙인다."""
    outlets = load_yaml("press.yaml").get("outlets", [])
    if raw:
        return outlets
    ver = (read_json(DATA / "press_verified.json", {}) or {}).get("domains", {})
    for o in outlets:
        o["domains"] = sorted(d for d, v in ver.items() if v.get("outlet") == o["id"] and v.get("verified"))
    return outlets


def validate_config(outlets: list[dict] | None = None) -> list[str]:
    """설정 점검: 38곳, id·이름·별칭 중복 없음. 문제 목록(비어 있으면 정상)."""
    outlets = outlets if outlets is not None else load_outlets(raw=True)
    errs = []
    if len(outlets) != EXPECTED_COUNT:
        errs.append(f"언론사 {len(outlets)}곳(기대 {EXPECTED_COUNT}곳)")
    ids = Counter(o["id"] for o in outlets)
    errs += [f"id 중복: {k}" for k, n in ids.items() if n > 1]
    names = Counter(o["name"] for o in outlets)
    errs += [f"표준명 중복: {k}" for k, n in names.items() if n > 1]
    seen: dict[str, str] = {}
    for o in outlets:
        for a in [o["name"], *o.get("aliases", [])]:
            k = norm_name(a)
            if k in seen and seen[k] != o["id"]:
                errs.append(f"별칭 충돌: {a} ({seen[k]} / {o['id']})")
            seen[k] = o["id"]
    return errs


def norm_name(s: str) -> str:
    return re.sub(r"[\s\-_·.\[\]()]", "", s or "").lower()


class PressIndex:
    def __init__(self, outlets: list[dict] | None = None):
        outlets = outlets if outlets is not None else load_outlets()
        self.outlets = {o["id"]: o for o in outlets}
        self.by_host: dict[str, str] = {}
        for o in outlets:
            if not o.get("allowed", True):
                continue
            for d in o.get("domains", []):
                self.by_host[d] = o["id"]
        self.by_alias: dict[str, str] = {}
        for o in outlets:
            for a in [o["name"], o.get("name_en", ""), *o.get("aliases", [])]:
                if a:
                    self.by_alias[norm_name(a)] = o["id"]

    def match_host(self, host: str) -> str | None:
        """가장 구체적인 도메인부터 맞춘다(biz.chosun.com → chosunbiz, chosun.com → chosun)."""
        parts = host.split(".")
        for i in range(len(parts) - 1):
            cand = ".".join(parts[i:])
            if cand in self.by_host:
                return self.by_host[cand]
        return None

    def by_label(self, label: str) -> str | None:
        return self.by_alias.get(norm_name(label))

    def identify(self, article: dict) -> dict:
        """기사 → {outlet, status, reason}. status: allowed | excluded | review(원출처 미확인)."""
        link = article.get("link") or ""
        host = host_of(link)
        if host and any(host == p or host.endswith("." + p) for p in PORTAL_HOSTS):
            # 포털 링크는 언론사가 아니다. 원출처(originallink)가 따로 없으면 확인 불가
            return {"outlet": None, "status": "review", "reason": f"포털 링크({host}): 원출처 확인 불가"}
        oid = self.match_host(host)
        if oid:
            return {"outlet": oid, "status": "allowed", "reason": f"도메인 {host}"}
        # 표기(RSS의 매체명 등)로 맞추되, 도메인이 허용 목록 밖이면 인정하지 않는다(이름만 같은 다른 매체 방지)
        lab = article.get("press_label") or article.get("source")
        if lab and self.by_label(lab) and not host:
            return {"outlet": self.by_label(lab), "status": "review", "reason": "표기만 일치(링크 없음)"}
        return {"outlet": None, "status": "excluded", "reason": f"허용 목록 밖: {host or '링크 없음'}"}


@lru_cache(maxsize=1)
def default_index() -> PressIndex:
    return PressIndex()


def clear_cache() -> None:
    default_index.cache_clear()
