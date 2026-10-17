"""하루 한 번(오전 10시 KST) 전체 갱신.

  python run_daily.py

순서: 시장금리 → KOFR 선물 → 한은 홈페이지 → 연합뉴스 RSS → 네이버 → 지표 일정·실제치 → 빌드 → AI 태깅·종합 → 빌드(확률 기록)
단계가 실패해도 다음 단계로 넘어간다. 실패한 데이터원은 직전 값을 유지하고 화면 상단에 '갱신 실패'로 뜬다.
GitHub Actions(daily.yml)와 PC 예약 작업이 같은 스크립트를 쓴다.
"""
from __future__ import annotations

import subprocess
import sys
import time

STEPS = [
    ("시장금리(ECOS)", ["-m", "bokwatch.fetch_rates"]),
    ("KOFR 선물(KRX)", ["-m", "bokwatch.fetch_futures"]),
    ("CD 단기물(금투협)", ["-m", "bokwatch.fetch_cdcurve"]),
    ("한은 홈페이지", ["-m", "bokwatch.fetch_bok"]),
    ("연합뉴스 RSS", ["-m", "bokwatch.fetch_news"]),
    ("네이버 뉴스", ["-m", "bokwatch.fetch_naver"]),
    ("지표 일정·실제치", ["-m", "bokwatch.fetch_events"]),
    ("결정 예측 모형(실험)", ["-m", "bokwatch.decision_model", "--fetch"]),
    ("빌드", ["build.py"]),
    ("AI 태깅·종합", ["-m", "bokwatch.ai_judge"]),
    ("빌드·확률 기록", ["build.py", "--log"]),
]


def already_done_today() -> bool:
    """오늘 날짜별 확률 기록에 '산출' 줄이 있으면 True(그날 정기 갱신을 이미 마침)."""
    import csv
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    log = Path(__file__).parent / "data" / "prob_log.csv"
    if not log.exists():
        return False
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    with open(log, encoding="utf-8") as f:
        return any(r["date"] == today and r["status"] == "산출" for r in csv.DictReader(f))


def main() -> int:
    import os
    # 예약 실행은 같은 날 두 번 이상 돌지 않는다(AI 비용·기록 보호). 수동 실행은 이 값을 주지 않으면 그대로 돈다.
    if os.environ.get("SKIP_IF_DONE_TODAY") == "1" and already_done_today():
        print("오늘 정기 갱신 기록이 이미 있어 건너뜀")
        return 0
    failed = []
    for label, args in STEPS:
        t = time.time()
        r = subprocess.run([sys.executable, *args])
        print(f"[{'성공' if r.returncode == 0 else '실패'}] {label} ({time.time() - t:.0f}초)", flush=True)
        if r.returncode != 0:
            failed.append(label)
    print("실패 단계: " + (", ".join(failed) if failed else "없음"))
    # 마지막 빌드가 실패하면 화면이 갱신되지 않으므로 그때만 오류로 끝낸다
    return 1 if "빌드·확률 기록" in failed else 0


if __name__ == "__main__":
    sys.exit(main())
