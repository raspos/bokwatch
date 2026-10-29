"""대표모형 전환용 날짜별 확률 시계열(site/data/awm_series.json).

회의 × 기준일(금리 관측일)마다 합성 KOFR OIS 단독과 M5(OIS 50% + 통안채 91일 50%)의 확률을 나란히 둔다.
- 기존 OIS 단독 기록(data/prob_log.csv, site/data/history.csv)은 건드리지 않는다. 이 파일은 별도 시계열이다.
- 값은 기준일에 알 수 있던 자료만으로 다시 계산한 것이다. 당시 저장된 값(data/awm_log.csv에 그날 기록된 M5)이 있으면
  그 값을 쓰고 kind를 "stored"(당시 저장 예측)로, 없으면 "retro"(사후 재계산)로 표시한다.
- OIS나 통안채 91일 입력이 없는 날은 M5를 만들지 않고 이유를 남긴다(CD91 등으로 채우지 않는다).
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from . import awm_data
from .common import d

W_OIS = 0.5
NAME = "BOK WATCH 종합 예측"
DESC = "합성 KOFR OIS와 통안채 91일물의 예측 확률을 각각 50% 반영한 통계적 결합모형"
KIND_LABEL = {"retro": "사후 재계산", "stored": "당시 저장 예측"}


def blend(ois: dict, msb: dict, w: float = W_OIS) -> dict:
    """세 범주 확률의 가중평균. 합은 1로 맞춘다."""
    p = {k: w * ois[k] + (1 - w) * msb[k] for k in ("hike", "hold", "cut")}
    s = sum(p.values())
    return {k: round(v / s, 4) for k, v in p.items()}


def one_day(inp: awm_data.Inputs, meeting: date, obs: date) -> dict:
    """기준일 obs의 OIS·통안채·M5 확률. 입력이 없으면 m5=None과 이유."""
    r0 = inp.base(obs)
    out = {"ois": None, "msb91": None, "m5": None, "why": None}
    if r0 is None:
        out["why"] = "기준금리 없음"
        return out
    o = awm_data.ois_model(inp, obs, r0, meeting, inp.ois_policy)
    s = awm_data.single_model(inp, "msb91", obs, r0, meeting)
    if o.get("ok"):
        out["ois"] = o["p"]
        out["ois_source"] = o.get("source_type")
    if s.get("ok"):
        out["msb91"] = s["p"]
    if out["ois"] and out["msb91"]:
        out["m5"] = blend(out["ois"], out["msb91"])
    else:
        miss = []
        if not out["ois"]:
            miss.append("합성 OIS 없음(" + str(o.get("why") or "풀리지 않음") + ")")
        if not out["msb91"]:
            miss.append("통안채 91일 없음(" + str(s.get("why") or "자료 없음") + ")")
        out["why"] = " · ".join(miss)
    return out


def _hist_dates(site_data: Path) -> dict[str, dict[str, float]]:
    """history.csv의 기본(스프레드 0) 시나리오: 회의 → {기준일: 사이트 OIS 인상확률}."""
    out: dict[str, dict[str, float]] = {}
    p = site_data / "history.csv"
    if not p.exists():
        return out
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r["scenario"] == "0":
            out.setdefault(r["meeting"], {})[r["date"]] = float(r["p_hike"])
    return out


def _stored(log_path: Path) -> dict[tuple[str, str], dict]:
    """data/awm_log.csv에 그날 저장된 M5: (회의, 금리 기준일) → 확률."""
    if not log_path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(log_path, encoding="utf-8")):
        if r["model"].startswith("M5"):
            out[(r["meeting"], r["obs_date"])] = {"hike": float(r["p_hike"]), "hold": float(r["p_hold"]), "cut": float(r["p_cut"])}
    return out


def target_meetings(inp: awm_data.Inputs, today: date) -> list[date]:
    """대표모형을 쓰는 회의: 마지막으로 끝난 회의와 다음 회의."""
    dec = sorted(d(x["date"]) for x in inp.cfg.get("past_decisions", []))
    last = max((x for x in dec if x <= today), default=None)
    nxt = next((m for m in inp.meetings_all if m > today), None)
    return [m for m in (last, nxt) if m]


def build_series(site_data: Path, log_path: Path, today: date, inp: awm_data.Inputs | None = None) -> dict:
    inp = inp or awm_data.Inputs()
    hist = _hist_dates(site_data)
    stored = _stored(log_path)
    meetings = {}
    for mt in target_meetings(inp, today):
        ms = mt.isoformat()
        days = {}
        for ds, site_p in sorted(hist.get(ms, {}).items()):
            obs = d(ds)
            if obs >= mt:
                continue
            row = one_day(inp, mt, obs)
            row["site_ois_hike"] = site_p                 # 사이트(history.csv)에 있던 OIS 단독 값. 재계산과 맞는지 점검용
            st = stored.get((ms, ds))
            if st and row["m5"]:
                row["m5"], row["kind"] = st, "stored"
            else:
                row["kind"] = "retro"
            days[ds] = row
        meetings[ms] = days
    return {"generated": today.isoformat(), "name": NAME, "desc": DESC, "w_ois": W_OIS, "kind_label": KIND_LABEL,
            "meetings": meetings}


def write_series(site_data: Path, log_path: Path, today: date, representative: str, inp=None) -> dict:
    s = build_series(site_data, log_path, today, inp)
    s["representative"] = representative            # "m5" | "ois"
    (site_data / "awm_series.json").write_text(json.dumps(s, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return s
