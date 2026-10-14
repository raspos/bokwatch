"""공통 유틸: 경로, 설정, KST 시각, 수집 상태 기록."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"
KST = timezone(timedelta(hours=9))


def load_dotenv(path: Path) -> None:
    """KEY=VALUE 형식 .env를 읽어 환경변수에 넣는다. 이미 있는 환경변수(Actions Secrets 등)는 덮어쓰지 않는다."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k and v and not os.environ.get(k):
            os.environ[k] = v


# 키 파일: BOKWATCH_ENV_FILE(OneDrive 밖 경로 권장)이 있으면 그것, 없으면 저장소의 .env
load_dotenv(Path(os.environ.get("BOKWATCH_ENV_FILE") or ROOT / ".env"))

# API 키 환경변수. GitHub Secrets에 붙여넣을 때 섞인 앞뒤 공백·줄바꿈을 지운다(헤더 오류·인증 실패 방지).
KEY_ENVS = ("ECOS_API_KEY", "KRX_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "OPENAI_API_KEY",
            "CLOUDFLARE_API_TOKEN", "DATA_GO_KR_KEY")
for _k in KEY_ENVS:
    if os.environ.get(_k) and os.environ[_k] != os.environ[_k].strip():
        os.environ[_k] = os.environ[_k].strip()


def redact(text: str) -> str:
    """상태 문구는 공개 사이트에 실린다. 키 값과 키처럼 생긴 문자열(sk-…, Bearer …)을 가린다."""
    import re
    for k in KEY_ENVS:
        v = os.environ.get(k, "")
        if len(v) >= 6:
            text = text.replace(v, "***")
    text = re.sub(r"sk-[A-Za-z0-9_\-*]{6,}", "sk-***", text)
    text = re.sub(r"(Bearer|AUTH_KEY|serviceKey=)\s*[A-Za-z0-9%._\-]{8,}", r"\1 ***", text)
    text = re.sub(r"Invalid header value b'[^']*'", "Invalid header value(키 값 형식 오류)", text)
    return text


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
    cur["message"] = redact(message)[:300]
    if ok:
        cur["last_success"] = t
    st[source] = cur
    write_json(STATUS, st)


def all_meetings(cfg: dict) -> list[date]:
    out = []
    for y, ds in (cfg.get("meetings") or {}).items():
        out += [d(x) for x in (ds or [])]
    return sorted(out)
