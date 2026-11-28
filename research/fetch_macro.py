"""M10용 거시 자료(소비자물가 총지수·농산물및석유류제외 지수, 월별) 수집. 키는 환경변수/.env에서 읽고 파일에 쓰지 않는다."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bokwatch.common import load_config  # noqa: E402
from bokwatch.fetch_rates import ecos_get  # noqa: E402

for envp in (ROOT / ".env", ROOT.parent / "joongang-bokwatch" / ".env"):
    if envp.exists():
        for ln in envp.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
cfg = load_config()
import csv
out = {}
for k, code in (("cpi", "0"), ("core", "QB")):
    rows = ecos_get(cfg, "StatisticSearch", ["901Y009", "M", "200601", "202610", code])
    print(k, len(rows), rows[:1] and (rows[0].get("ITEM_NAME1"), rows[0].get("TIME"), rows[0].get("DATA_VALUE")))
    for r in rows:
        if r.get("DATA_VALUE"):
            out.setdefault(r["TIME"], {})[k] = float(r["DATA_VALUE"])
with open(ROOT / "research" / "macro_cpi.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["month", "cpi", "core"])
    for m in sorted(out):
        w.writerow([m, out[m].get("cpi", ""), out[m].get("core", "")])
print("months", len(out))
