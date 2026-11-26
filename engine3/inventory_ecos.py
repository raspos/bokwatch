"""3.0 PHASE 2: ECOS 금리·환율·주가 계열의 실제 확보 기간을 항목 목록(StatisticItemList)으로 조사한다. 키는 .env에서 읽고 출력하지 않는다."""
import os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for ln in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.lstrip().startswith("#"):
        k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from bokwatch.common import load_config
from bokwatch.fetch_rates import ecos_get
cfg = load_config()
STATS = {"817Y002": "시장금리(일별)", "722Y001": "한국은행 기준금리", "731Y001": "주요국 통화의 대원화 환율", "802Y001": "주식시장 KOSPI 등", "721Y001": "시장금리(월별)"}
out = {}
for st, name in STATS.items():
    try:
        rows = ecos_get(cfg, "StatisticItemList", [st])
    except Exception as e:  # noqa: BLE001
        out[st] = {"name": name, "error": f"{type(e).__name__}"}
        continue
    out[st] = {"name": name, "items": [{"cycle": r.get("CYCLE"), "code": r.get("ITEM_CODE"), "name": r.get("ITEM_NAME"), "start": r.get("START_TIME"), "end": r.get("END_TIME"), "n": r.get("DATA_CNT")} for r in rows]}
(ROOT / "engine3" / "ecos_inventory.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for st, v in out.items():
    print(st, v["name"], len(v.get("items", [])), v.get("error", ""))
