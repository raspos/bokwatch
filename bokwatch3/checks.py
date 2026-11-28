"""배포 전 검사와 화면·보고서·차트 일관성 검사. 실패하면 배포를 막는 용도(오류 목록을 돌려준다)."""
from __future__ import annotations

import json
from pathlib import Path

REQUIRED_DATA = ("meta.json", "history.csv", "prob_log.json", "awm_series.json", "prob_events.json", "guidance.json", "review.json", "memo.json")


def predeploy(site_data: Path) -> list[str]:
    """필수 파일 존재·JSON 유효성·스냅샷 목록 일치. (과거에 스냅샷 한 개 누락으로 화면이 비었던 사고의 재발 방지)"""
    errs = []
    for f in REQUIRED_DATA:
        p = site_data / f
        if not p.exists() or p.stat().st_size == 0:
            errs.append(f"파일 없음/빈 파일: {f}")
            continue
        if f.endswith(".json"):
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                errs.append(f"JSON 형식 오류: {f}")
    meta_p = site_data / "meta.json"
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            for s in meta.get("snapshots", []):
                if not (site_data / "snapshots" / f"{s}.json").exists():
                    errs.append(f"스냅샷 누락: {s}")
            lat = meta.get("latest")
            if lat and not (site_data / "snapshots" / f"{lat}.json").exists():
                errs.append(f"최신 스냅샷 누락: {lat}")
        except ValueError:
            pass
    return errs


def consistency(rep: dict, chart_last: dict, table_last: dict, tol: float = 5e-4) -> list[str]:
    """같은 회의·기준일의 대표 확률이 화면 박스·차트 끝점·기록표에서 같아야 한다. 각 인자는 {'hike': p, ...}."""
    errs = []
    for name, other in (("차트", chart_last), ("기록표", table_last)):
        for k in ("hike", "hold", "cut"):
            if abs(rep.get(k, 0.0) - other.get(k, 0.0)) > tol:
                errs.append(f"{name} {k} 불일치: 박스 {rep.get(k):.4f} vs {other.get(k):.4f}")
    return errs


def probability_range(history: list[float]) -> tuple[float, float]:
    """기간 내 최저·최고(자동 확률 범위)."""
    return (min(history), max(history)) if history else (float("nan"), float("nan"))


def turning_points(dates: list[str], p: list[float], threshold: float = 0.05) -> list[dict]:
    """전일 대비 변화폭이 threshold 이상인 날(자동 전환점)."""
    out = []
    for i in range(1, len(p)):
        d = p[i] - p[i - 1]
        if abs(d) >= threshold:
            out.append({"date": dates[i], "delta": d})
    return out
