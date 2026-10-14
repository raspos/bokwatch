"""ECOS Open API로 기준금리·일별 시장금리를 받아 data/rates.csv에 누적한다.

  python -m bokwatch.fetch_rates --resolve   # StatisticItemList로 항목코드 확인 → config 기록
  python -m bokwatch.fetch_rates             # 최근 구간 갱신(기본 30일)
  python -m bokwatch.fetch_rates --full      # history_start부터 전체

수동 입력: data/manual/ois_YYYY-MM-DD.csv, data/manual/rates_YYYY-MM-DD.csv
  (열: id,rate,source  — id는 config의 ecos.market.items / ecos.ois.items의 id)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from .common import DATA, d, load_config, now_kst, record_status

RATES_CSV = DATA / "rates.csv"
FIELDS = ["date", "id", "value", "source"]


class EcosError(RuntimeError):
    pass


# ---------------------------------------------------------------- ECOS 호출
def ecos_get(cfg, service: str, params: list, key: str | None = None) -> list[dict]:
    key = key or os.environ.get(cfg["ecos"]["key_env"], "")
    if not key:
        raise EcosError("ECOS_API_KEY 없음")
    rows, start, page = [], 1, 1000
    while True:
        url = "/".join([cfg["ecos"]["base_url"], service, key, "json", "kr",
                        str(start), str(start + page - 1)] + [str(p) for p in params])
        data = None
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=(20, 60))
                r.raise_for_status()
                data = r.json()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                # 해외 서버(GitHub Actions)에서 ECOS 접속이 가끔 늦다 → 5·15·45초 뒤 다시 시도
                if attempt < 3:
                    time.sleep(5 * 3 ** attempt)
                    continue
                raise EcosError(f"{type(e).__name__}(4회 시도): {str(e).replace(key, '***')}") from None
            except Exception as e:
                # 키가 URL 경로에 들어가므로 오류 문구에서 지운다(status.json은 공개 사이트에 실린다)
                raise EcosError(f"{type(e).__name__}: {str(e).replace(key, '***')}") from None
        if "RESULT" in data:
            code = data["RESULT"].get("CODE", "")
            if code == "INFO-200":   # 해당 데이터 없음
                return rows
            raise EcosError(f"{code} {data['RESULT'].get('MESSAGE', '')}")
        body = data[next(iter(data))]
        got = body.get("row", [])
        rows += got
        if len(got) < page:
            return rows
        start += page


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def match_items(item_rows: list[dict], items: list[dict]) -> dict:
    """StatisticItemList 결과에서 이름으로 항목코드를 찾는다."""
    out = {}
    for it in items:
        want = _norm(it["match"])
        hits = [r for r in item_rows if want in _norm(r.get("ITEM_NAME", ""))]
        # 가장 이름이 짧은(=정확히 일치에 가까운) 항목
        hits.sort(key=lambda r: len(r.get("ITEM_NAME", "")))
        if hits:
            out[it["id"]] = (hits[0]["ITEM_CODE"], hits[0]["ITEM_NAME"])
    return out


def write_item_codes(codes: dict, cfg_path: Path = DATA / "config.yaml") -> None:
    """주석을 보존하려고 해당 줄의 item_code만 치환한다."""
    text = cfg_path.read_text(encoding="utf-8")
    for iid, (code, _name) in codes.items():
        text = re.sub(rf"(\{{id: {iid},.*?item_code: )([^}}]*)(\}})",
                      lambda m: f"{m.group(1)}\"{code}\"{m.group(3)}", text)
    cfg_path.write_text(text, encoding="utf-8", newline="\n")


def resolve(cfg) -> dict:
    mk = cfg["ecos"]["market"]
    codes = match_items(ecos_get(cfg, "StatisticItemList", [mk["stat"]]), mk["items"])
    br = cfg["ecos"]["base_rate"]
    base_rows = ecos_get(cfg, "StatisticItemList", [br["stat"]])
    if base_rows:
        codes_br = match_items(base_rows, [{"id": "base", "match": br["item_name"]}]) or \
            {"base": (base_rows[0]["ITEM_CODE"], base_rows[0]["ITEM_NAME"])}
        text = (DATA / "config.yaml").read_text(encoding="utf-8")
        text = re.sub(r"(base_rate: \{.*?item_code: )([^}]*)(\})",
                      lambda m: f"{m.group(1)}\"{codes_br['base'][0]}\"{m.group(3)}", text)
        (DATA / "config.yaml").write_text(text, encoding="utf-8", newline="\n")
    write_item_codes(codes)
    return codes


# ---------------------------------------------------------------- 저장소
def load_rates(path: Path = RATES_CSV) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [dict(r, value=float(r["value"])) for r in csv.DictReader(f)]


def save_rates(rows: list[dict], path: Path = RATES_CSV) -> None:
    uniq = {(r["date"], r["id"]): r for r in rows}
    out = sorted(uniq.values(), key=lambda r: (r["date"], r["id"]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for r in out:
            w.writerow({k: r[k] for k in FIELDS})


def manual_rows() -> list[dict]:
    """data/manual/*.csv 수동 입력 (같은 날짜·id면 ECOS 값보다 우선하지 않음; OIS는 수동만)."""
    out = []
    for p in sorted((DATA / "manual").glob("*_????-??-??.csv")):
        day = p.stem.split("_")[-1]
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(r for r in f if not r.startswith("#")):
                if r.get("id") and r.get("rate"):
                    out.append({"date": day, "id": r["id"].strip(), "value": float(r["rate"]),
                                "source": (r.get("source") or f"수동입력 {p.name}").strip()})
    return out


def series(rows: list[dict], iid: str) -> dict[str, float]:
    return {r["date"]: r["value"] for r in rows if r["id"] == iid}


def value_on(ser: dict[str, float], day: date, max_back: int = 10):
    """휴일이면 직전 영업일 값. (값, 실제 기준일) 반환."""
    for i in range(max_back + 1):
        k = (day - timedelta(days=i)).isoformat()
        if k in ser:
            return ser[k], k
    return None, None


# ---------------------------------------------------------------- 수집
def fetch(cfg, start: date, end: date) -> list[dict]:
    rows = []
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    mk = cfg["ecos"]["market"]
    missing = [it["id"] for it in mk["items"] if not it.get("item_code")]
    if missing:
        raise EcosError(f"항목코드 미확인: {missing} → --resolve 먼저 실행")
    for it in mk["items"]:
        for r in ecos_get(cfg, "StatisticSearch", [mk["stat"], mk["cycle"], s, e, it["item_code"]]):
            if r.get("DATA_VALUE") not in (None, ""):
                t = r["TIME"]
                rows.append({"date": f"{t[:4]}-{t[4:6]}-{t[6:]}", "id": it["id"],
                             "value": float(r["DATA_VALUE"]),
                             "source": f"ECOS {mk['stat']}/{it['item_code']}"})
    br = cfg["ecos"]["base_rate"]
    for r in ecos_get(cfg, "StatisticSearch", [br["stat"], br["cycle"], s, e, br.get("item_code") or ""]):
        if r.get("DATA_VALUE") not in (None, ""):
            t = r["TIME"]
            rows.append({"date": f"{t[:4]}-{t[4:6]}-{t[6:]}", "id": "base",
                         "value": float(r["DATA_VALUE"]), "source": f"ECOS {br['stat']}"})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args(argv)
    cfg = load_config()
    try:
        if a.resolve or any(not it.get("item_code") for it in cfg["ecos"]["market"]["items"]):
            codes = resolve(cfg)
            print("항목코드:", codes)
            cfg = load_config()
        end = now_kst().date()
        start = d(cfg["ecos"]["history_start"]) if a.full else end - timedelta(days=a.days)
        new = fetch(cfg, start, end)
        save_rates(load_rates() + new)
        record_status("ecos", True, f"{len(new)}건")
        print(f"ECOS {len(new)}건 저장")
    except Exception as e:  # 실패해도 직전 데이터 유지
        record_status("ecos", False, f"{type(e).__name__}: {e}")
        print(f"ECOS 수집 실패: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
