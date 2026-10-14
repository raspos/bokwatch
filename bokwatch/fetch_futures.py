"""KRX Open API '선물 일별매매정보(주식선물外)' → 3개월무위험금리(KOFR) 선물 정산가격 → data/futures.csv

  python -m bokwatch.fetch_futures            # 최근 10일
  python -m bokwatch.fetch_futures --full     # 상장일(2022-03-28)부터 전체 (영업일당 1회 호출)

키: KRX_API_KEY (openapi.krx.co.kr → 서비스 '선물 일별매매정보(주식선물外)' 이용 신청). 요청 헤더 AUTH_KEY.
API는 다음 영업일 오전에 전일 자료를 준다. 거래가 없는 결제월의 정산가격은 거래소 이론가다(거래량·미결제약정을 함께 저장).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import date, timedelta

import requests

from .common import DATA, now_kst, record_status

FUT_CSV = DATA / "futures.csv"
FIELDS = ["date", "month", "settle", "close", "volume", "oi", "isu_cd"]
URL = "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd"
PROD = "3개월무위험금리 선물"
LISTED = date(2022, 3, 28)


class KrxError(RuntimeError):
    pass


def parse_items(items: list[dict], day: str) -> list[dict]:
    """응답 OutBlock_1 → KOFR 선물 결제월별 행. 스프레드 종목(SP)은 뺀다."""
    out = []
    for it in items:
        name = it.get("ISU_NM", "")
        if it.get("PROD_NM") != PROD or " F " not in name or not it.get("SETL_PRC"):
            continue
        ym = name.split()[-1]  # '202611'
        out.append({"date": day, "month": f"{ym[:4]}-{ym[4:6]}", "settle": float(it["SETL_PRC"]),
                    "close": float(it["TDD_CLSPRC"]) if it.get("TDD_CLSPRC") else "",
                    "volume": int(it.get("ACC_TRDVOL") or 0), "oi": int(it.get("ACC_OPNINT_QTY") or 0),
                    "isu_cd": it.get("ISU_CD", "")})
    return out


def fetch_day(day: date, key: str) -> list[dict]:
    for i in range(3):
        try:
            r = requests.get(URL, params={"basDd": day.strftime("%Y%m%d")}, headers={"AUTH_KEY": key}, timeout=60)
            r.raise_for_status()
            return parse_items(r.json().get("OutBlock_1") or [], day.isoformat())
        except Exception as e:  # 키가 오류 문구에 섞이지 않게 지운다
            err = f"{type(e).__name__}: {str(e).replace(key, '***')}"
            time.sleep(2 ** i)
    raise KrxError(err)


def load_futures() -> list[dict]:
    if not FUT_CSV.exists():
        return []
    with open(FUT_CSV, encoding="utf-8") as f:
        return [dict(r, settle=float(r["settle"]), volume=int(r["volume"] or 0), oi=int(r["oi"] or 0))
                for r in csv.DictReader(f)]


def save_futures(rows: list[dict]) -> None:
    uniq = {(r["date"], r["month"]): r for r in rows}
    with open(FUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for k in sorted(uniq):
            w.writerow({x: uniq[k].get(x, "") for x in FIELDS})


def by_date(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["date"], []).append(r)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--days", type=int, default=10)
    a = ap.parse_args(argv)
    key = os.environ.get("KRX_API_KEY", "").strip()
    if not key:
        record_status("krx", False, "KRX_API_KEY 없음 — 직전 선물 가격 유지")
        print("KRX_API_KEY 없음", file=sys.stderr)
        return 1
    rows = load_futures()
    have = {r["date"] for r in rows}
    today = now_kst().date()
    start = LISTED if a.full else today - timedelta(days=a.days)
    got, errors, d = 0, [], start
    while d < today:
        if d.weekday() < 5 and (d.isoformat() not in have or d >= today - timedelta(days=a.days)):
            try:
                new = fetch_day(d, key)
                rows = [r for r in rows if r["date"] != d.isoformat()] + new
                got += len(new)
            except KrxError as e:
                errors.append(f"{d}: {e}")
                if len(errors) >= 5:
                    break
        d += timedelta(days=1)
    save_futures(rows)
    last = max((r["date"] for r in rows), default="없음")
    record_status("krx", not errors, "; ".join(errors[:3]) or f"KOFR 선물 {got}행 수신, 최신 {last}")
    print(f"KOFR 선물 {got}행 수신, 최신 {last}" + (f", 오류 {len(errors)}건" if errors else ""))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
