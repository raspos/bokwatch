"""4차 실행: 제로·AFNS·TP·M8 변형 기반 모형 셀 생성(결합 모형은 combine4.py가 셀에서 만든다)."""
import sys
import time
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine3"))
import wf  # noqa: E402
import wf2  # noqa: E402

OUT = ROOT / "engine3" / "results"


def build_cells(models, yd, yz, base, meet, extra=None, limit=None):
    """wf.build_cells와 같은 규칙 + ctx에 제로 패널 값(yz)을 넣는다."""
    idx = yd.index
    cells, actuals, rng_rows = [], [], []
    for k, m in enumerate(sorted(meet)):
        if limit and m > pd.Timestamp(limit):
            break
        out = wf.outcome(base, m)
        if out is None:
            continue
        act, delta = out
        past = list(actuals)
        for D in wf.HORIZONS:
            cut = m - pd.Timedelta(days=D)
            j = bisect_right(idx, cut) - 1
            if j < 0:
                continue
            obs = idx[j]
            if obs >= m or obs not in yz.index:
                continue
            r0 = float(base.loc[:obs].iloc[-1])
            ctx = {"meeting": m, "obs": obs, "r0": r0, "yields": yd.iloc[j].to_dict(), "yz": yz.loc[obs].to_dict(),
                   "past_actuals": past, "D": D}
            for mdl in models:
                try:
                    res = mdl.predict(ctx)
                except Exception as e:  # noqa: BLE001
                    wf.FAILS[mdl.name] = wf.FAILS.get(mdl.name, 0) + 1
                    wf.FAIL_EX.setdefault(mdl.name, repr(e))
                    res = None
                if res is None:
                    continue
                p, ed = res
                cells.append({"meeting": m.date().isoformat(), "D": D, "actual": act, "delta": delta, "model": mdl.name,
                              "p_hike": p["hike"], "p_hold": p["hold"], "p_cut": p["cut"], "exp_delta": ed,
                              "prior12": float(base.loc[:obs].iloc[-1] - base.loc[:obs - pd.Timedelta(days=365)].iloc[-1])
                              if obs - pd.Timedelta(days=365) >= base.index[0] else np.nan})
            for e in extra or []:
                rr = e["fn"](ctx)
                if rr:
                    rng_rows.append({"meeting": m.date().isoformat(), "D": D, "actual": act, "model": e["name"],
                                     "lo": rr[0], "hi": rr[1], "n_meet": rr[2]})
        for mdl in models:
            if hasattr(mdl, "update"):
                mdl.update(m, act)
        actuals.append(act)
        if k % 10 == 0:
            print("meeting", m.date(), len(cells), time.strftime("%H:%M:%S"), flush=True)
    return pd.DataFrame(cells), pd.DataFrame(rng_rows)


class _ZeroWrap:
    """DnsZero가 ctx['yields']에서 읽으므로 제로 값을 넣어 호출한다."""

    def __init__(self, inner):
        self.inner, self.name = inner, inner.name

    def predict(self, ctx):
        c2 = dict(ctx)
        c2["yields"] = ctx["yz"]
        return self.inner.predict(c2)


def main(limit=None, out_name="cells4.csv"):
    yd, base, meet = wf.load()
    yz = pd.read_csv(ROOT / "research" / "yields_zero.csv", index_col=0, parse_dates=True)
    rows = wf.rows_for_market(yd, base)
    allm = [m.date() for m in meet] + [m.date() for m in pd.to_datetime(["2026-11-26", "2027-01-14"])]
    freq = wf.Frequency()
    acmz = wf2.AcmZero(yz, base)
    fa = wf2.AfnsFit(yz, wf.CURVE, wf2.ZMAT)
    fk = wf2.AfnsFit(yz, ["ktb1y", "ktb3y", "ktb5y", "ktb10y"], np.array([1.0, 3.0, 5.0, 10.0]))
    m8 = {"freq": wf2.MaxEntGen(rows, allm, freq, "M8 사전=과거 빈도(기본)"),
          "uniform": wf2.MaxEntGen(rows, allm, freq, "M8v 사전=균등", prior="uniform"),
          "hold90": wf2.MaxEntGen(rows, allm, freq, "M8v 사전=동결 0.9", prior="hold90"),
          "context": wf2.MaxEntGen(rows, allm, freq, "M8v 사전=직전 결정 맥락", prior="context")}
    m12 = wf2.MaxEntGen(rows, allm, freq, "M12 M8+ACM 기간프리미엄 보정", l_fn=wf2.l_tp(acmz))
    m13 = wf2.MaxEntGen(rows, allm, freq, "M13 AFNS 기대경로+M8", l_fn=wf2.l_afns(fa))
    m13k = wf2.MaxEntGen(rows, allm, freq, "M13k AFNS(국고채만) 기대경로+M8", l_fn=wf2.l_afns(fk))
    models = [_ZeroWrap(wf2.DnsZero(yz, min_weeks=156, refit=13)), acmz, wf2.AfnsDirect(fa), m12, m13, m13k] + list(m8.values())
    extra = [{"name": "M8 식별범위(ε=2bp·T)", "fn": lambda ctx: m8["freq"].ident_range(ctx)}]
    df, rng = build_cells(models, yd, yz, base, meet, extra, limit)
    df.to_csv(OUT / out_name, index=False, encoding="utf-8")
    rng.to_csv(OUT / "ident_range.csv", index=False, encoding="utf-8")
    print("done", len(df), "fails", wf.FAILS, wf.FAIL_EX)
    for f, nm in ((fa, "afns"), (fk, "afns_k")):
        import json
        (OUT / f"{nm}_params.json").write_text(json.dumps({str(f.w.index[k].date()): {"par": [float(v) for v in a.par], **a.conv} for k, a in f.fits.items()}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    lim = sys.argv[1] if len(sys.argv) > 1 else None
    main(lim, "cells4_test.csv" if lim else "cells4.csv")
