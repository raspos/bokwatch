"""공통 유틸: 경로, 설정, KST 시각, 수집 상태 기록."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"
KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def load_yaml(name: str):
    with open(DATA / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict:
    return load_yaml("config.yaml")


def d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


STATUS = SITE_DATA / "status.json"


def record_status(source: str, ok: bool, message: str = "") -> None:
    """데이터원별 수집 결과. 실패해도 last_success는 유지한다."""
    st = read_json(STATUS, {}) or {}
    cur = st.get(source, {})
    t = now_kst().isoformat(timespec="minutes")
    cur["last_attempt"] = t
    cur["ok"] = ok
    cur["message"] = message[:300]
    if ok:
        cur["last_success"] = t
    st[source] = cur
    write_json(STATUS, st)


def all_meetings(cfg: dict) -> list[date]:
    out = []
    for y, ds in (cfg.get("meetings") or {}).items():
        out += [d(x) for x in (ds or [])]
    return sorted(out)
