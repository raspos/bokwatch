"""시장금리 → 모델 투입 → 확률 결과 (스냅샷·추이·백테스트)."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from . import cd_short, futures_model, model
from .common import d
from .fetch_rates import load_rates, manual_rows, series, value_on


def all_rate_rows() -> list[dict]:
    """ECOS 값 우선, 같은 날짜·id에 ECOS가 없을 때만 수동 입력."""
    rows = load_rates()
    have = {(r["date"], r["id"]) for r in rows}
    return rows + [r for r in manual_rows() if (r["date"], r["id"]) not in have]


def item_defs(cfg) -> dict:
    out = {}
    for it in cfg["ecos"]["market"]["items"]:
        out[it["id"]] = {"label": it["label"], "tenor_days": it["tenor_days"], "kind": "market"}
    for it in cfg["ecos"]["ois"]["items"]:
        out[it["id"]] = {"label": it["label"], "tenor_days": it["tenor_days"], "kind": "ois"}
    return out


def base_rate_on(rows, day: date, cfg):
    v, k = value_on(series(rows, "base"), day, max_back=40)
    if v is not None:
        return v, f"ECOS/수동 base ({k})"
    # 기준금리 시계열이 없으면 결정 기록에서
    past = [x for x in cfg.get("past_decisions", []) if d(x["date"]) <= day]
    if past:
        x = max(past, key=lambda x: x["date"])
        return float(x["rate"]), f"결정 기록 {x['date']}"
    return None, None


def estimate_spreads(rows, cfg) -> dict:
    """장기 동결 국면 y - r0 중앙값. override > 추정 > fallback."""
    mc = cfg["model"]
    base = series(rows, "base")
    out = {}
    for iid in item_defs(cfg):
        if iid in (mc.get("spread_override") or {}):
            out[iid] = {"value": float(mc["spread_override"][iid]), "how": "config 지정"}
            continue
        ser = series(rows, iid)
        obs = []
        for a, b in mc.get("hold_windows", []):
            for day, y in ser.items():
                if a <= day <= b:
                    r0, _ = value_on(base, d(day), 40)
                    if r0 is not None:
                        obs.append((y - r0) * 100)
        if len(obs) >= 20:
            out[iid] = {"value": round(model.normal_spread(obs), 4),
                        "how": f"동결 국면 중앙값({len(obs)}일)"}
        elif iid in (mc.get("spread_fallback") or {}):
            out[iid] = {"value": float(mc["spread_fallback"][iid]), "how": "기본 가정(이력 부족)"}
    return out


def pit_spread(rows, iid: str, day: date, lookback_days: int = 730, settle_days: int = 120):
    """당시(day 전날까지) 알 수 있던 자료만으로 정상 스프레드를 추정한다(백테스트용, 미래정보 제거).
    기준금리가 직전 settle_days일 동안 바뀌지 않은 날만 골라 (y − 기준금리) 중앙값을 낸다. 관측 20일 미만이면 None."""
    base, ser = series(rows, "base"), series(rows, iid)
    changes = sorted(d(k) for k, (a, b) in zip(sorted(base)[1:], zip([base[x] for x in sorted(base)][:-1],
                                                                       [base[x] for x in sorted(base)][1:])) if a != b)
    lo, obs = day - timedelta(days=lookback_days), []
    for k, y in ser.items():
        dk = d(k)
        if not (lo <= dk < day):
            continue
        last = max((c for c in changes if c <= dk), default=None)
        if last is not None and (dk - last).days < settle_days:
            continue
        r0, _ = value_on(base, dk, 40)
        if r0 is not None:
            obs.append(y - r0)
    return round(statistics.median(obs), 4) if len(obs) >= 20 else None


def meetings_after(cfg, day: date) -> list[date]:
    ms = {d(x) for ys in cfg["meetings"].values() for x in (ys or [])}
    ms |= {d(x["date"]) for x in cfg.get("past_decisions", [])}
    ms |= assumed_meetings(cfg)
    return sorted(m for m in ms if m > day)


def assumed_meetings(cfg) -> set[date]:
    """공지 전 다음 해 회의 가정(계산 전용). 해당 연도 일정이 입력되면 쓰지 않는다."""
    known_years = {y for y, ys in cfg["meetings"].items() if ys}
    return {d(x) for x in (cfg.get("assumed_meetings") or []) if str(d(x).year) not in known_years}


def known_through(cfg) -> date:
    k = d(cfg["schedule_known_through"])
    if assumed_meetings(cfg) and cfg.get("assumed_known_through"):
        k = max(k, d(cfg["assumed_known_through"]))
    return k


def instruments_on(rows, cfg, day: date, spreads: dict):
    """그날 투입할 상품. OIS가 있으면 OIS 우선. (instruments, input_table, warnings)"""
    defs = item_defs(cfg)
    known = known_through(cfg)
    start = model.settlement_start(day)
    table, warns = [], []
    ois_ids = [i for i, x in defs.items() if x["kind"] == "ois" and day.isoformat() in series(rows, i)]
    use = ois_ids or list(cfg["model"]["use"])
    insts = []
    for iid, df in defs.items():
        ser = series(rows, iid)
        v, used_day = value_on(ser, day, 7)
        if v is None:
            continue
        prev_v, prev_day = value_on(ser, d(used_day) - timedelta(days=1), 10)
        sp = spreads.get(iid, {"value": 0.0, "how": "없음"})
        mat = start + timedelta(days=df["tenor_days"])
        in_sched = mat <= known
        used = iid in use and in_sched
        if iid in use and not in_sched:
            warns.append(f"{df['label']} 만기({mat})가 확정 일정({known}) 밖 — 계산 제외")
        src = next((r["source"] for r in rows if r["id"] == iid and r["date"] == used_day), "")
        table.append({"id": iid, "label": df["label"], "rate": v, "date": used_day,
                      "tenor_days": df["tenor_days"], "spread": sp["value"], "spread_how": sp["how"],
                      "chg_bp": round((v - prev_v) * 100, 1) if prev_v is not None else None,
                      "prev_date": prev_day, "source": src, "used": used, "kind": df["kind"]})
        if used:
            insts.append(model.Instrument(iid, v, df["tenor_days"], sp["value"], src))
    return insts, table, warns


def kofr_spread(rows, day: date, cfg) -> tuple[float, str]:
    """KOFR − 기준금리 정상 차이: 기준일 앞 N일 중앙값(%p)."""
    fc = cfg["model"].get("futures", {})
    n = fc.get("spread_lookback_days", 60)
    base, kofr = series(rows, "base"), series(rows, "kofr")
    lo = (day - timedelta(days=n)).isoformat()
    obs = []
    for k, y in kofr.items():
        if lo <= k <= day.isoformat():
            b0 = value_on(base, d(k), 40)[0]
            if b0 is not None:
                obs.append(y - b0)
    if len(obs) >= 10:
        return round(statistics.median(obs), 4), f"KOFR−기준금리 {n}일 중앙값({len(obs)}일)"
    return float(fc.get("spread_fallback", 0.04)), "기본 가정(관측 부족)"


def futures_on(fut_by_date: dict, day: date, max_stale: int = 5):
    """기준일 이하 가장 가까운 날의 KOFR 선물 정산가격(오래되면 None)."""
    ks = [k for k in fut_by_date if k <= day.isoformat()]
    if not ks:
        return None, None
    k = max(ks)
    if (day - d(k)).days > max_stale:
        return None, None
    return k, [futures_model.Contract(r["month"], float(r["settle"]), int(r["volume"]), int(r["oi"]))
               for r in fut_by_date[k]]


def blend_meetings(cd, kf, w_kofr: float) -> list[dict]:
    """회의별 확률 가중평균. 한쪽만 있으면 그쪽을 그대로 쓴다(source에 표시)."""
    cdm = {m["date"]: m for m in (cd or []) if m.get("in_range")}
    kfm = {m["date"]: m for m in (kf or []) if m.get("in_range")}
    w = w_kofr

    def mix(x, y):
        return round((1 - w) * x + w * y, 4)

    def mixd(x, y):
        return {k: mix(x.get(k, 0.0), y.get(k, 0.0)) for k in sorted(set(x) | set(y))}

    out = []
    for dt in sorted(set(cdm) | set(kfm)):
        a, b = cdm.get(dt), kfm.get(dt)
        if a and b:
            m = {"date": dt, "expected": mix(a["expected"], b["expected"]),
                 "delta_bp": mix(a["delta_bp"], b["delta_bp"]),
                 "p_hike": mix(a["p_hike"], b["p_hike"]), "p_hold": mix(a["p_hold"], b["p_hold"]),
                 "p_cut": mix(a["p_cut"], b["p_cut"]), "moves": mixd(a["moves"], b["moves"]),
                 "levels": mixd(a["levels"], b["levels"]), "method": "blend", "in_range": True,
                 "source": "CD·KOFR 선물 혼합"}
        else:
            m = dict(a or b, source="CD 91일만" if a else "KOFR 선물만")
        out.append(m)
    done = {m["date"] for m in out}
    for x in (cd or []):
        if not x.get("in_range") and x["date"] not in done:
            out.append(dict(x))
    return sorted(out, key=lambda m: m["date"])


def run_day(rows, cfg, day: date, spreads: dict, shifts=(-5, 0, 5), fut_by_date=None, curve=None):
    r0, r0_src = base_rate_on(rows, day, cfg)
    insts, table, warns = instruments_on(rows, cfg, day, spreads)
    for t in table:
        t["vs_base_bp"] = round((t["rate"] - r0) * 100, 1) if r0 is not None else None
    if r0 is None:
        return None
    ms = meetings_after(cfg, day)
    cd = None
    if insts:
        sens = model.sensitivity(day, r0, insts, ms, cfg["model"]["method"], shifts)
        cd = {str(k): model.result_to_dict(v) for k, v in sens.items()}
        # 같은 금리와 양립하는 회의별 확률 범위(동결·한 방향 25bp만 허용). 기본 표시값은 '늦은 회의 배정' 경로다.
        base_inst = insts[0]
        for k in cd:
            shifted = model.Instrument(base_inst.name, base_inst.rate, base_inst.tenor_days,
                                       round(base_inst.spread + int(k) / 100.0, 6), base_inst.source)
            pr = model.path_ranges(day, r0, shifted, ms)
            cd[k]["path_range"] = pr
            for m in cd[k]["meetings"]:
                rg = pr["meetings"].get(m["date"])
                if rg and m["in_range"]:
                    m["range"] = {"direction": pr["direction"], **{x: rg[x] for x in ("min", "max", "early", "late", "max_expected", "max_levels")},
                                  "feasible": pr["feasible"]}
    kf = None
    if fut_by_date:
        fut_day, cs = futures_on(fut_by_date, day, cfg["model"].get("futures", {}).get("max_stale_days", 5))
        if cs:
            s, s_how = kofr_spread(rows, day, cfg)
            fix = {k: v for k, v in series(rows, "kofr").items() if k <= day.isoformat()}
            kf = futures_model.solve(day, r0, cs, fix, ms, s, d(cfg["schedule_known_through"]))
            kf["spread_how"], kf["price_date"] = s_how, fut_day
            if not kf["meetings"]:
                kf = None
    # 가정 회의는 계산에만 쓰고 회의 목록(화면·기록)에서는 뺀다
    asm = {x.isoformat() for x in assumed_meetings(cfg)}
    used_asm = sorted(x for x in asm if x > day.isoformat()
                      and any(m["date"] == x for k in (cd or {}) for m in cd[k]["meetings"]))
    if cd and used_asm:
        for k in cd:
            cd[k]["meetings"] = [m for m in cd[k]["meetings"] if m["date"] not in asm]
    if not cd and not kf:
        return None
    cs_ = cd_short.compute(curve, series(rows, "base"), meetings_after(cfg, date(2000, 1, 1)), day, r0) if curve else None
    # 기본값 = CD 모형 추정치. KOFR 선물·혼합은 실험값(components)으로만 둔다.
    w = float(cfg["model"].get("blend", {}).get("experimental_kofr_weight", 0.5))
    scen = {}
    for k in [str(x) for x in shifts]:
        ms_cd = [dict(m, source="CD 91일 모형") for m in cd[k]["meetings"]] if cd else []
        scen[k] = {"meetings": ms_cd, "method": cd[k]["method"] if cd else "none", "notes": cd[k]["notes"] if cd else []}
    exp_blend = None
    if cd and kf:
        exp_blend = {"weight_kofr": w, "meetings": [m for m in blend_meetings(cd["0"]["meetings"], kf["meetings"], w)
                                                     if m.get("source") == "CD·KOFR 선물 혼합"]}
    if not cd:
        warns.append("CD 91일 만기가 확정 일정 밖 — 기본 추정치 산출 중단(KOFR 선물 실험값만 표시)")
    if not kf:
        warns.append("KOFR 선물 가격 없음 — 실험값 없음")
    return {
        "asof": day.isoformat(), "r0": r0, "r0_source": r0_src, "default_ok": bool(cd), "assumed_meetings": used_asm,
        "inputs": table, "warnings": warns, "scenarios": scen,
        "components": {"cd": cd, "kofr_futures": kf, "blend_experimental": exp_blend, "cd_short": cs_},
    }


def data_dates(rows, cfg, fut_by_date=None) -> list[date]:
    ids = set(cfg["model"]["use"]) | {i["id"] for i in cfg["ecos"]["ois"]["items"]}
    return sorted({d(r["date"]) for r in rows if r["id"] in ids} | {d(k) for k in (fut_by_date or {})})


# ---------------------------------------------------------------- 백테스트
def business_days_before(day: date, n: int, available: list[date]) -> date | None:
    prior = [x for x in available if x < day]
    return prior[-n] if len(prior) >= n else None


def _score(p: dict, actual: str) -> tuple[str, float]:
    """예측 = 가장 높은 확률의 결과. 최고 확률이 둘 이상 같으면 '동률'로 두고 적중으로 치지 않는다."""
    top = max(p.values())
    best = [k for k in p if abs(p[k] - top) < 1e-9]
    pred = best[0] if len(best) == 1 else "tie"
    return pred, sum((p[k] - (1.0 if k == actual else 0.0)) ** 2 for k in p)


def walk_forward(rows: list[dict], start: int = 12, grid=None) -> dict:
    """순차 검증: 회의 i 이전 회의만으로 Brier가 가장 낮은 KOFR 비율 w를 고르고, 회의 i를 그 비율로 예측한다."""
    grid = grid or [i / 10 for i in range(11)]
    keys = ("hike", "hold", "cut")

    def p_of(r, w):
        return {k: w * r["kofr"][f"p_{k}"] + (1 - w) * r[f"p_{k}"] for k in keys}
    preds = []
    for i in range(start, len(rows)):
        past = rows[:i]
        w = min(grid, key=lambda w: statistics.mean(_score(p_of(r, w), r["actual"])[1] for r in past))
        r = rows[i]
        pr, br = _score(p_of(r, w), r["actual"])
        cpr, cbr = _score(p_of(r, 0.0), r["actual"])
        preds.append({"meeting": r["meeting"], "w": w, "hit": pr == r["actual"], "brier": round(br, 4),
                      "cd_hit": cpr == r["actual"], "cd_brier": round(cbr, 4), "actual": r["actual"]})
    if not preds:
        return {}
    n = len(preds)
    return {"start_after": start, "n": n,
            "mix": {"hits": sum(p["hit"] for p in preds), "brier": round(statistics.mean(p["brier"] for p in preds), 4)},
            "cd": {"hits": sum(p["cd_hit"] for p in preds), "brier": round(statistics.mean(p["cd_brier"] for p in preds), 4)},
            "always_hold": {"hits": sum(p["actual"] == "hold" for p in preds)},
            "rows": preds}


def backtest(rows, cfg, spreads, start_year=2021, n_before=3, fut_by_date=None) -> dict:
    """회의 n영업일 전 종가로 낸 확률과 실제 결정 비교. 기본(혼합)·CD·KOFR 선물을 같은 회의에서 함께 잰다."""
    avail = data_dates(rows, cfg)
    decisions = sorted(cfg.get("past_decisions", []), key=lambda x: x["date"])
    out, prev_rate, excluded = [], None, []
    prior_outcomes = []  # 백테스트 시작 전 결정(빈도 기준용)
    for x in decisions:
        md = d(x["date"])
        actual_prev = prev_rate
        prev_rate = float(x["rate"])
        if actual_prev is not None and md.year < start_year:
            mv = round((float(x["rate"]) - actual_prev) * 100)
            prior_outcomes.append("hike" if mv > 0 else "cut" if mv < 0 else "hold")
        if md.year < start_year or actual_prev is None:
            continue
        obs = business_days_before(md, n_before, avail)
        if obs is None or (md - obs).days > 10:
            excluded.append({"meeting": md.isoformat(), "why": "회의 직전 시장금리 없음"})
            continue
        sp_obs = dict(spreads)
        sp_how = "현재 추정치 그대로"
        for iid in cfg["model"]["use"]:
            v = pit_spread(rows, iid, obs)
            if v is None:
                v = float(cfg["model"].get("spread_fallback", {}).get(iid, 0.10))
                sp_how = "당시 자료 부족 → 기본 가정"
            else:
                sp_how = "당시까지 자료"
            sp_obs[iid] = {"value": v, "how": sp_how}
        res = run_day(rows, cfg, obs, sp_obs, shifts=(0,), fut_by_date=fut_by_date)
        if not res:
            excluded.append({"meeting": md.isoformat(), "why": "산출 불가"})
            continue
        m = next((m for m in res["scenarios"]["0"]["meetings"] if m["date"] == md.isoformat() and m["in_range"]), None)
        if not m:
            excluded.append({"meeting": md.isoformat(), "why": "기본(CD) 추정치 없음"})
            continue
        move = round((float(x["rate"]) - actual_prev) * 100)
        actual = "hike" if move > 0 else "cut" if move < 0 else "hold"
        p = {"hike": m["p_hike"], "hold": m["p_hold"], "cut": m["p_cut"]}
        pred, brier = _score(p, actual)
        row = {"meeting": md.isoformat(), "obs_date": obs.isoformat(), **{f"p_{k}": v for k, v in p.items()},
               "pred": pred, "actual": actual, "move_bp": move, "hit": pred == actual,
               "brier": round(brier, 4), "source": m.get("source", ""),
               "spread_bp": round(sp_obs[cfg["model"]["use"][0]]["value"] * 100, 1), "spread_how": sp_how}
        # 비교 기준: 그 회의 이전 결정들의 빈도(라플라스 보정)
        prior = [z["actual"] for z in out] + list(prior_outcomes)
        freq = {k: (prior.count(k) + 1) / (len(prior) + 3) for k in ("hike", "hold", "cut")}
        bpred, bbr = _score(freq, actual)
        row["base_rate"] = {**{f"p_{k}": round(v, 4) for k, v in freq.items()}, "hit": bpred == actual, "brier": round(bbr, 4)}
        comp = res.get("components", {})
        for name, c in (("kofr", comp.get("kofr_futures")), ("blend", comp.get("blend_experimental"))):
            cm = next((z for z in (c or {}).get("meetings", []) if z["date"] == md.isoformat() and z["in_range"]), None)
            if cm:
                q = {"hike": cm["p_hike"], "hold": cm["p_hold"], "cut": cm["p_cut"]}
                pr, br = _score(q, actual)
                row[name] = {"p_hike": q["hike"], "p_hold": q["hold"], "p_cut": q["cut"],
                             "hit": pr == actual, "brier": round(br, 4)}
        out.append(row)
    n = len(out)
    both = [r for r in out if "kofr" in r and "blend" in r]
    compare = None
    if both:
        compare = {"n": len(both), "first": both[0]["meeting"],
                   "excluded_before": [r["meeting"] for r in out if r not in both]}
        hold = {"hike": 0.0, "hold": 1.0, "cut": 0.0}
        getters = (("cd", lambda r: (r["hit"], r["brier"])), ("kofr", lambda r: (r["kofr"]["hit"], r["kofr"]["brier"])),
                   ("blend", lambda r: (r["blend"]["hit"], r["blend"]["brier"])),
                   ("base_rate", lambda r: (r["base_rate"]["hit"], r["base_rate"]["brier"])),
                   ("always_hold", lambda r: (r["actual"] == "hold", _score(hold, r["actual"])[1])))
        for name, get in getters:
            vals = [get(r) for r in both]
            compare[name] = {"hit_rate": round(sum(v[0] for v in vals) / len(vals), 4),
                             "brier": round(statistics.mean(v[1] for v in vals), 4)}
        compare["walk_forward"] = walk_forward(both)
        # 결과별: 금리가 바뀐 회의 / 동결 회의에서 각 방식이 실제 결과에 준 확률 평균
        def avg_actual(rs, get):
            return round(statistics.mean(get(r)[f"p_{r['actual']}"] for r in rs), 4) if rs else None
        chg = [r for r in both if r["actual"] != "hold"]
        hold_rs = [r for r in both if r["actual"] == "hold"]
        compare["hits_by_actual"] = {
            act: {"n": sum(r["actual"] == act for r in both),
                  **{name: sum(get(r)[0] for r in both if r["actual"] == act) for name, get in getters}}
            for act in ("hold", "hike", "cut")}
        compare["by_outcome"] = {
            "n_change": len(chg), "n_hold": len(hold_rs),
            "cd": {"change": avg_actual(chg, lambda r: r), "hold": avg_actual(hold_rs, lambda r: r)},
            "kofr": {"change": avg_actual(chg, lambda r: r["kofr"]), "hold": avg_actual(hold_rs, lambda r: r["kofr"])},
            "blend": {"change": avg_actual(chg, lambda r: r["blend"]), "hold": avg_actual(hold_rs, lambda r: r["blend"])},
        }
    w = cfg["model"].get("blend", {}).get("experimental_kofr_weight", 0.5)
    return {
        "n": n, "rule": f"회의 {n_before}영업일 전 종가, 기본 스프레드. 기본값 CD 91일 모형, 실험값 KOFR 선물·혼합(KOFR {w:.0%})",
        "excluded": excluded,
        "hit_rate": round(sum(r["hit"] for r in out) / n, 4) if n else None,
        "brier": round(statistics.mean(r["brier"] for r in out), 4) if n else None,
        "compare": compare, "rows": out,
        "note": None if n else "과거 시장금리 이력이 없어 산출하지 못함 (ECOS --full 수집 후 자동 산출)",
    }
