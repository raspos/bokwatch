"""배포용 폴더 dist/ 만들기 (Cloudflare Pages 끌어다 놓기 업로드는 파일 1,000개 한도).

  python make_dist.py            # 스냅샷은 최근 365일만
  python make_dist.py --days 180

site/를 그대로 복사하고, data/snapshots만 최근 N일로 줄인 뒤 meta.json의 날짜 목록을 맞춘다.
확률 추이(history.csv)·백테스트·날짜별 기록은 별도 파일이라 그대로 남는다.
GitHub Actions 배포(_deploy.yml, wrangler)는 site/ 전체를 올리므로 이 스크립트가 필요 없다.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE, DIST = ROOT / "site", ROOT / "dist"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    a = ap.parse_args(argv)
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(SITE, DIST)
    meta_p = DIST / "data" / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    latest = date.fromisoformat(meta.get("latest") or date.today().isoformat())
    cut = (latest - timedelta(days=a.days)).isoformat()
    snaps = DIST / "data" / "snapshots"
    for f in snaps.glob("*.json"):
        if f.stem < cut:
            f.unlink()
    meta["snapshots"] = [d for d in meta.get("snapshots", []) if d >= cut]
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(1 for _ in DIST.rglob("*") if _.is_file())
    print(f"dist/ 파일 {n}개 (스냅샷 {cut} 이후 {len(meta['snapshots'])}일)")
    return 0 if n <= 1000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
