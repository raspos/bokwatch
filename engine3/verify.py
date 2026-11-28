"""지시 1: 2차·3차 결과 차이 재검증. 같은 cells.csv에서 표본별 칸·회의 수, 재현율 분모, Brier 정의 차이를 표로 낸다."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine3"))
import evaluate as ev  # noqa: E402

RES = ROOT / "engine3" / "results"
M0B, M1, M2, M3, M8 = ev.BASE, "M1 합성 OIS 단독", "M2 통안채 91일 단독", "M3 운영 50:50(OIS+통안채)", "M8 회의일 기반 풀이(최대 엔트로피)"
M11 = "M11 동적 앙상블(빈도·통안채·DNS·M8)"
HZ = [60, 30, 14, 7, 1]


def main():
    df = ev.prep(pd.read_csv(RES / "cells.csv"))
    fin = df[df["period"] == "최종(2023~)"]
    out = {}
    # 표본 정의
    need = [M1, M2, M3, M0B]
    cnt = fin[fin["model"].isin(need)].groupby(["meeting", "D"])["model"].nunique()
    keys = set(cnt[cnt == 4].index)
    g1 = fin[[(m, d) in keys for m, d in zip(fin["meeting"], fin["D"])]]
    all_cells = fin[fin["model"] == M0B][["meeting", "D", "actual"]].drop_duplicates()
    g1c = g1[g1["model"] == M0B][["meeting", "D", "actual"]].drop_duplicates()
    miss = all_cells.merge(g1c, on=["meeting", "D"], how="left", indicator=True)
    miss = miss[miss["_merge"] == "left_only"]
    out["sample"] = {
        "final_all": {"meetings": int(all_cells["meeting"].nunique()), "cells": int(len(all_cells)),
                      "change_meetings": int(all_cells[all_cells["actual"] != "hold"]["meeting"].nunique()),
                      "change_cells": int((all_cells["actual"] != "hold").sum())},
        "G1_common_OIS": {"meetings": int(g1c["meeting"].nunique()), "cells": int(len(g1c)),
                          "change_meetings": int(g1c[g1c["actual"] != "hold"]["meeting"].nunique()),
                          "change_cells": int((g1c["actual"] != "hold").sum())},
        "in_final_not_in_G1": miss[["meeting", "D", "actual_x"]].rename(columns={"actual_x": "actual"}).to_dict("records"),
    }
    # 표본별 Brier(정규화 전/후)
    rows = []
    for name, d in (("최종 최대 가용", fin), ("G1 공통 격자", g1)):
        for m in (M0B, M2, M3, M8, M11):
            g = d[d["model"] == m]
            if not len(g):
                continue
            ch = g[g["changed"]]
            alert = g["pchg"] >= 0.5
            rows.append({"sample": name, "model": m, "meetings": int(g["meeting"].nunique()), "cells": int(len(g)),
                         "brier": float(g["brier"].mean()), "brier_over_2": float(g["brier"].mean() / 2),
                         "change_cells": int(len(ch)), "alert_on_change_cells": int(alert[g["changed"]].sum()),
                         "recall": float(alert[g["changed"]].mean()) if len(ch) else None,
                         "alert_cells": int(alert.sum()), "precision": float(g["changed"][alert].mean()) if alert.sum() else None})
    out["by_sample"] = rows
    # M11을 G1에서: M11은 2023-01 회의를 포함(OIS 불필요). 같은 칸에서만 비교
    keys2 = set(zip(g1c["meeting"], g1c["D"]))
    m11g = fin[(fin["model"] == M11)]
    m11g1 = m11g[[(m, d) in keys2 for m, d in zip(m11g["meeting"], m11g["D"])]]
    out["M11_on_G1"] = {"cells": int(len(m11g1)), "brier": float(m11g1["brier"].mean()), "M11_final_all_cells": int(len(m11g)),
                        "M11_final_all_brier": float(m11g["brier"].mean())}
    # 시계 차이의 불확실성(회의 단위 부트스트랩): 최종 구간, vs M0b / G1에서 M11 vs M3
    hb = {}
    for m in (M2, M3, M8, M11):
        for D in HZ:
            r = ev.boot_diff(fin, m, M0B, fin["D"] == D)
            if r:
                hb[f"{m}|D={D}|vs M0b|최종"] = r
    for D in HZ:
        r = ev.boot_diff(g1.assign(), M3, M0B, g1["D"] == D)
        if r:
            hb[f"{M3}|D={D}|vs M0b|G1"] = r
    out["horizon_boot"] = hb
    # D 사이 차이 자체(예: M3의 D=60 − D=1 칸 Brier) 부트스트랩
    diffs = {}
    for m in (M3, M8, M11, M2):
        g = fin[fin["model"] == m].pivot_table(index="meeting", columns="D", values="brier")
        for a, b in ((60, 1), (30, 1), (7, 1)):
            if a in g and b in g:
                d = (g[a] - g[b]).dropna().values
                if len(d) >= 5:
                    rng = np.random.default_rng(3)
                    bs = np.array([rng.choice(d, len(d)).mean() for _ in range(10000)])
                    diffs[f"{m}|D={a} − D={b}"] = {"n": len(d), "mean": float(d.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5))}
    out["horizon_difference"] = diffs
    (RES / "verify.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["sample"], ensure_ascii=False, indent=1))
    print(pd.DataFrame(out["by_sample"]).to_string())
    print(out["M11_on_G1"])


if __name__ == "__main__":
    main()
