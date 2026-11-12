"""ACM/AFNS 연구용: ECOS 일별 국채·통안채 수익률과 기준금리를 2005년부터 받아 research/yields_long.csv로 저장한다.
키는 .env(ECOS_API_KEY)에서 읽고 출력하지 않는다. 연구 전용이며 공식 확률에는 쓰지 않는다."""
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bokwatch.common import load_config  # noqa: E402
from bokwatch.fetch_rates import ecos_get  # noqa: E402

env = ROOT / ".env"
if env.exists():
    for ln in env.read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
cfg = load_config()
ITEMS = {"msb91": "010400000", "msb1y": "010400001", "msb2y": "010400002", "ktb1y": "010190000", "ktb3y": "010200000", "cd91": "010502000"}
ITEMS.update({"ktb5y": "010200001", "ktb10y": "010210000"})
out = {}
for k, code in ITEMS.items():
    for r in ecos_get(cfg, "StatisticSearch", ["817Y002", "D", "20050101", "20261231", code]):
        if r.get("DATA_VALUE"):
            out.setdefault(r["TIME"], {})[k] = float(r["DATA_VALUE"])
for r in ecos_get(cfg, "StatisticSearch", ["722Y001", "D", "20050101", "20261231", "0101000"]):
    if r.get("DATA_VALUE"):
        out.setdefault(r["TIME"], {})["base"] = float(r["DATA_VALUE"])
cols = ["base", "cd91", "msb91", "msb1y", "msb2y", "ktb1y", "ktb3y", "ktb5y", "ktb10y"]
p = ROOT / "research" / "yields_long.csv"
with p.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["date"] + cols)
    for t in sorted(out):
        w.writerow([f"{t[:4]}-{t[4:6]}-{t[6:]}"] + [out[t].get(c, "") for c in cols])
print("rows", len(out), "cols with data:", {c: sum(1 for t in out if c in out[t]) for c in cols})
