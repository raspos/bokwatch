"""AWM 2.0 점별(point-in-time) 자료: 금통위 × 관측 시점(D일 전) 표.

각 칸의 모형별 확률은 그 관측일까지 알 수 있던 자료만으로 계산한다(미래정보 없음).
사용한 상품·입력 공시일·스프레드 출처·누락 사유를 모두 남긴다. 합성 OIS가 없으면 CD91로 채우지 않고 '없음'으로 기록한다.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta

from . import kofr_ois, market, model
from .common import d, load_config
from .fetch_cdcurve import load_curve
from .fetch_rates import series, value_on

HORIZONS = (30, 20, 10, 5, 3, 1)          # 금통위까지 남은 달력일
MAX_GAP = 5                                # 관측일이 목표일보다 이만큼(달력일) 넘게 앞서면 '자료 없음'
SINGLE = ("cd91", "msb91")                 # 단독 상품 모형(CD 91일, 통안증권 91일)


def outcome(move_bp: float) -> str:
    return "hike" if move_bp > 0 else "cut" if move_bp < 0 else "hold"


def meeting_table(cfg: dict) -> list[dict]:
    """정례 회의별 결정과 직전 결정 맥락(직전 변경 방향, 같은 방향 연속 횟수, 경과일). 첫 회의는 직전 금리를 몰라 뺀다."""
    dec = sorted(cfg.get("past_decisions", []), key=lambda x: x["date"])
    out, prev_rate, last_change, streak, last_dir = [], None, None, 0, None
    for x in dec:
        md, rate = d(x["date"]), float(x["rate"])
        if prev_rate is not None:
            mv = round((rate - prev_rate) * 100)
            out.append({"meeting": md, "rate": rate, "prev_rate": prev_rate, "move_bp": mv, "actual": outcome(mv),
                        "last_change_dir": last_dir, "streak": streak,
                        "days_since_change": (md - last_change).days if last_change else None})
            if mv != 0:
                streak = streak + 1 if last_dir == outcome(mv) else 1
                last_dir, last_change = outcome(mv), md
        prev_rate = rate
    return out


def obs_on_or_before(avail: list[date], target: date) -> date | None:
    """목표일 이하 마지막 자료일. MAX_GAP일 넘게 비면 None."""
    i = bisect.bisect_right(avail, target)
    if i == 0 or (target - avail[i - 1]).days > MAX_GAP:
        return None
    return avail[i - 1]


class Inputs:
    """한 번 만들어 계속 쓰는 입력 묶음."""

    def __init__(self, cfg: dict | None = None, ois_policy: str = "flat"):
        self.cfg = cfg or load_config()
        self.ois_policy = ois_policy
        self.rows = market.all_rate_rows()
        self.ser = {i: series(self.rows, i) for i in {r["id"] for r in self.rows}}
        self.avail = sorted(d(k) for k in self.ser["msb91"])
        self.curve = load_curve()
        self.ois = kofr_ois.OIS(self.curve, self.ser["cd91"], self.ser["kofr"]) if self.curve else None
        self.meetings_all = market.meetings_after(self.cfg, date(2000, 1, 1))

    def base(self, day: date):
        return value_on(self.ser["base"], day, 40)[0]

    def bdays_before(self, day: date, n: int) -> date | None:
        i = bisect.bisect_right(self.avail, day) - 1
        return self.avail[i - n] if i - n >= 0 else None


# ---------------------------------------------------------------- 모형별 확률
def _probs(p_hike, p_hold, p_cut) -> dict:
    return {"hike": round(p_hike, 6), "hold": round(p_hold, 6), "cut": round(p_cut, 6)}


def single_model(inp: Inputs, iid: str, obs: date, r0: float, meeting: date) -> dict:
    """단독 상품(CD91·통안증권 91일)의 회의 확률. 정상 스프레드는 당시까지 자료로만 추정한다."""
    v, used = value_on(inp.ser[iid], obs, 7)
    if v is None:
        return {"ok": False, "why": "금리 없음"}
    sp = market.pit_spread(inp.rows, iid, obs)
    how = "당시까지 자료"
    if sp is None:
        sp = float(inp.cfg["model"].get("spread_fallback", {}).get(iid, 0.10))
        how = "기본 가정(이력 부족)"
    tenor = 91
    meetings = [m for m in inp.meetings_all if m > obs]
    res = model.solve(obs, r0, [model.Instrument(iid, v, tenor, sp, "ECOS")], meetings, inp.cfg["model"]["method"])
    m = next((x for x in res.meetings if x.date == meeting and x.in_range), None)
    if not m:
        return {"ok": False, "why": "상품 만기 안에 회의 없음", "input_date": used}
    return {"ok": True, "p": _probs(m.p_hike, m.p_hold, m.p_cut), "expected": round(m.expected, 4),
            "source_type": "single_" + iid, "instrument": iid, "input_date": used, "rate": v,
            "spread": sp, "spread_how": how, "solve": m.method}


def ois_model(inp: Inputs, obs: date, r0: float, meeting: date, policy: str = "flat") -> dict:
    """합성 KOFR OIS 경로에서 그 회의의 확률. 풀리지 않으면 없음으로 기록한다(CD91로 대체하지 않는다).
    policy: flat = 3개월 식으로 앞 회의를 풀 때 뒤 회의는 변화 없음(현재 모형). strict = 뒤 회의가 만기 끝 7일 이내일 때만 풀고 그 밖은 없음(이전 정의)."""
    if inp.ois is None:
        return {"ok": False, "why": "CD 시가평가 곡선 없음"}
    ks = market.kofr_spread(inp.rows, obs, inp.cfg)[0]
    res = kofr_ois.compute(inp.ois, obs, r0, ks, inp.meetings_all, max_stale=3)
    if not res:
        return {"ok": False, "why": "합성 OIS 산출 불가(곡선·스프레드 표본 부족)"}
    x = next((z for z in res["path"] if z["meeting"] == meeting.isoformat()), None)
    if not x:
        why = "1개월물 회의 뒤 구간 부족·3개월 식으로도 풀리지 않음"
        return {"ok": False, "why": why, "input_date": res["curve"].get("m1", res["curve"].get("m3", {})).get("cd_date")}
    src = "ois_1m" if x["source"].startswith("1개월") else "ois_3m"
    if policy == "strict" and src == "ois_3m" and x.get("tail_assumed"):
        m3 = res["curve"]["m3"]
        end = model.settlement_start(d(m3["cd_date"])) + timedelta(days=m3["tenor_days"])
        if any((end - d(t)).days > 7 for t in x["tail_assumed"]):
            return {"ok": False, "why": "뒤 회의 변화 없음 가정이 필요해 제외(strict)", "input_date": m3["cd_date"]}
    return {"ok": True, "p": _probs(x["p_hike"], x["p_hold"], x["p_cut"]), "expected": x["expected"], "delta_bp": x["delta_bp"],
            "source_type": src, "input_date": (res["curve"].get("m1") or res["curve"].get("m3") or {}).get("cd_date"),
            "kofr_base": ks, "n_obs_spread": (res["curve"].get("m1") or res["curve"].get("m3") or {}).get("n_obs")}


# ---------------------------------------------------------------- 전환 신호 변수
def _bp(a, b):
    return None if a is None or b is None else round((a - b) * 100, 2)


def features(inp: Inputs, obs: date, r0: float, meeting: date, ois_now: dict) -> dict:
    """시장지표의 수준보다 변화·전환 신호. 모두 obs 이하 자료만 쓴다."""
    ser = inp.ser

    def val(iid, day):
        return value_on(ser[iid], day, 7)[0] if iid in ser and day else None

    def spread91(day):
        return _bp(val("msb91", day), inp.base(day) if day else None)

    out = {"s91_bp": spread91(obs)}                                     # 통안채 91일 − 기준금리
    for n in (5, 10, 20):
        past = inp.bdays_before(obs, n)
        s_then = spread91(past) if past else None
        out[f"s91_chg{n}_bp"] = None if out["s91_bp"] is None or s_then is None else round(out["s91_bp"] - s_then, 2)
    out["slope_k1y_m91_bp"] = _bp(val("ktb1y", obs), val("msb91", obs))  # 국고채 1년 − 통안채 91일
    out["slope_k3y_k1y_bp"] = _bp(val("ktb3y", obs), val("ktb1y", obs))  # 국고채 3년 − 국고채 1년
    out["cd91_minus_kofr_bp"] = _bp(val("cd91", obs), val("kofr", obs))   # CD91 − KOFR
    out["ois_delta_bp"] = ois_now.get("delta_bp") if ois_now.get("ok") else None  # 합성 OIS 기준금리 변경 기대폭
    for n in (5, 10):
        past = inp.bdays_before(obs, n)
        if out["ois_delta_bp"] is None or past is None:
            out[f"ois_delta_chg{n}_bp"] = None
            continue
        r_then = inp.base(past)
        then = ois_model(inp, past, r_then, meeting, inp.ois_policy) if r_then is not None else {"ok": False}
        out[f"ois_delta_chg{n}_bp"] = round(out["ois_delta_bp"] - then["delta_bp"], 2) if then.get("ok") else None
    return out


# ---------------------------------------------------------------- 표 만들기
def build_panel(inp: Inputs | None = None, start_year: int = 2021, horizons=HORIZONS) -> list[dict]:
    inp = inp or Inputs()
    rows = []
    for mt in meeting_table(inp.cfg):
        md = mt["meeting"]
        if md.year < start_year:
            continue
        for D in horizons:
            target = md - timedelta(days=D)
            obs = obs_on_or_before(inp.avail, target)
            row = {"meeting": md.isoformat(), "horizon": D, "target_date": target.isoformat(), "actual": mt["actual"],
                   "move_bp": mt["move_bp"], "last_change_dir": mt["last_change_dir"], "streak": mt["streak"],
                   "days_since_change": mt["days_since_change"], "obs_date": obs.isoformat() if obs else None, "models": {}}
            if obs is None:
                row["missing"] = "관측일 없음(자료 공백)"
                rows.append(row)
                continue
            r0 = inp.base(obs)
            row["r0"] = r0
            if r0 is None or abs(r0 - mt["prev_rate"]) > 1e-9:
                row["missing"] = "기준금리 불일치(관측일 기준금리가 직전 결정과 다름)"
                rows.append(row)
                continue
            for iid in SINGLE:
                row["models"][iid] = single_model(inp, iid, obs, r0, md)
            row["models"]["ois"] = ois_model(inp, obs, r0, md, inp.ois_policy)
            row["features"] = features(inp, obs, r0, md, row["models"]["ois"])
            rows.append(row)
    return rows
