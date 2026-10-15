"""금융투자협회 채권정보센터 'CD시가평가수익률'(AAA, 평가사 5사 평균) → data/cd_curve.csv

  python -m bokwatch.fetch_cdcurve            # 최근 14일
  python -m bokwatch.fetch_cdcurve --full     # 5사 평균 공시 시작(2023-01-09)부터 전체 (영업일당 1회 호출)

만기 7일·15일·1개월·3개월·6개월·1년. 평가사가 당일 18시 이후 제공하므로 오전 갱신에서는 전 영업일 값까지 들어온다.
값은 협회 공시대로 소수 둘째 자리(버림)다. 날짜를 넣어 조회하면 그날('당일')과 직전 영업일('전일') 행이 오는데,
날짜를 분명히 하려고 '당일' 행만 저장한다. 휴일은 행이 없다.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import date, timedelta

import requests

from .common import DATA, now_kst, record_status

CSV_PATH = DATA / "cd_curve.csv"
TENORS = ["d7", "d15", "m1", "m3", "m6", "y1"]
FIELDS = ["date", *TENORS, "source"]
URL = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"
FIRST = date(2023, 1, 9)
SOURCE = "금융투자협회 CD시가평가수익률 AAA 5사 평균"
BODY = """<?xml version="1.0" encoding="utf-8"?>
<message><proframeHeader><pfmAppName>BIS-KOFIABOND</pfmAppName><pfmSvcName>BISCDSrtPrcSrchSO</pfmSvcName>
<pfmFnName>listDay</pfmFnName></proframeHeader><systemHeader></systemHeader>
<BISComDspDatDTO><val21>{day}</val21><val22>A20000</val22><val1>A10002</val1><val2>A10003</val2>
<val3>A10004</val3><val4>A10005</val4><val5>A10006</val5></BISComDspDatDTO></message>"""


def parse_day(xml: str, day: str) -> dict | None:
    """응답 XML → AAA·당일·5사 평균 행."""
    for blk in re.findall(r"<BISComDspDatDTO>(.*?)</BISComDspDatDTO>", xml, re.S):
        v = {k: (x or "").strip() for k, x in re.findall(r"<(val\d+)>([^<]*)</val\d+>", blk)}
        if v.get("val1") == "AAA" and v.get("val2") == "당일" and v.get("val3") == "5사 평균":
            nums = [v.get(f"val{i}", "") for i in range(4, 10)]
            if not all(re.fullmatch(r"-?\d+(\.\d+)?", x) for x in nums):
                return None
            return {"date": day, **{t: float(x) for t, x in zip(TENORS, nums)}, "source": SOURCE}
    return None


def fetch_day(day: date, session: requests.Session) -> dict | None:
    err = None
    for i in range(3):
        try:
            r = session.post(URL, data=BODY.format(day=day.strftime("%Y%m%d")).encode("utf-8"), timeout=30,
                             headers={"Content-Type": "text/xml; charset=UTF-8", "User-Agent": "Mozilla/5.0",
                                      "Referer": "https://www.kofiabond.or.kr/"})
            r.raise_for_status()
            r.encoding = "utf-8"
            return parse_day(r.text, day.isoformat())
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (i + 1))
    raise RuntimeError(err)


def load_curve() -> dict[str, dict]:
    if not CSV_PATH.exists():
        return {}
    with open(CSV_PATH, encoding="utf-8") as f:
        return {r["date"]: {**r, **{t: float(r[t]) for t in TENORS}} for r in csv.DictReader(f)}


def save(rows: dict[str, dict]) -> None:
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        for k in sorted(rows):
            w.writerow({x: rows[k][x] for x in FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    rows = load_curve()
    today = now_kst().date()
    start = FIRST if a.full else today - timedelta(days=a.days)
    s = requests.Session()
    got, fails, day = 0, 0, start
    try:
        while day <= today:
            if day.weekday() < 5 and (a.full is False or day.isoformat() not in rows):
                try:
                    r = fetch_day(day, s)
                    if r:
                        rows[r["date"]] = r
                        got += 1
                except RuntimeError as e:
                    fails += 1
                    print(f"{day} 실패: {e}", file=sys.stderr)
                    if fails >= 10:
                        raise
                time.sleep(0.15)
                if got and got % 100 == 0:
                    save(rows)
                    print(f"{day} 까지 {got}일", flush=True)
            day += timedelta(days=1)
        save(rows)
        last = max(rows) if rows else "-"
        record_status("cdcurve", True, f"{got}일 갱신 · 최신 {last}" + (f" · 실패 {fails}일" if fails else ""))
        print(f"CD 단기물 {got}일 갱신, 최신 {last}")
        return 0
    except Exception as e:
        save(rows)
        record_status("cdcurve", False, f"{type(e).__name__}: {e}")
        print(f"실패: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
