"""예측 저장소(단일 진실 원천). 추가만 되는 JSONL.

- kind="live": 그때 실제로 낸 예측. 한번 쓰면 고치지 않는다(같은 (회의, 기준일, 모형버전) 중복은 거부).
- kind="backtest": 사후 재계산. live와 파일을 분리해 섞이지 않게 한다.
- 대표 확률과 구성 모형 확률을 모두 저장한다(components). 나중에 가중을 바꿔도 원자료로 다시 계산할 수 있다.
- 당일 아침(MEETING_DAY_PRE_DECISION) 예측은 slot="morning_of"로 영구 저장한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REQUIRED = ("meeting", "asof", "made_at", "model_version", "state", "slot", "representative", "components")


class DuplicateForecast(Exception):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str) -> Path:
        if kind not in ("live", "backtest"):
            raise ValueError(kind)
        return self.root / f"forecasts_{kind}.jsonl"

    def read(self, kind: str = "live") -> list[dict]:
        p = self._path(kind)
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    def append(self, rec: dict, kind: str = "live") -> None:
        miss = [k for k in REQUIRED if k not in rec]
        if miss:
            raise ValueError(f"필수 필드 없음: {miss}")
        rep = rec["representative"]
        if abs(sum(rep.get(k, 0.0) for k in ("hike", "hold", "cut")) - 1.0) > 1e-6:
            raise ValueError("대표 확률 합이 1이 아님")
        for name, p in rec["components"].items():
            if abs(sum(p.get(k, 0.0) for k in ("hike", "hold", "cut")) - 1.0) > 1e-6:
                raise ValueError(f"구성 모형 확률 합이 1이 아님: {name}")
        key = (rec["meeting"], rec["asof"], rec["model_version"], rec["slot"])
        for old in self.read(kind):
            if (old["meeting"], old["asof"], old["model_version"], old["slot"]) == key:
                raise DuplicateForecast(key)
        rec = {**rec, "kind": kind, "stored_at": datetime.now().isoformat(timespec="seconds")}
        with open(self._path(kind), "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def morning_of(self, meeting: str) -> dict | None:
        for r in self.read("live"):
            if r["meeting"] == meeting and r["slot"] == "morning_of":
                return r
        return None

    def series(self, meeting: str, model_version: str | None = None) -> list[dict]:
        rows = [r for r in self.read("live") if r["meeting"] == meeting and (model_version is None or r["model_version"] == model_version)]
        return sorted(rows, key=lambda r: r["asof"])
