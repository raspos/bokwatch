import yaml

from bokwatch.common import DATA
from bokwatch.guidance import allowed_speeches
from bokwatch.press import default_index


def test_speech_without_allowed_link_is_dropped():
    ok, out = allowed_speeches([
        {"date": "2026-10-12", "link": "https://www.news1.kr/economy/trend/6317332"},
        {"date": "2026-10-12", "link": None},
        {"date": "2026-10-13", "link": "http://www.newsroad.co.kr/news/articleView.html?idxno=65788"},
    ])
    assert [s["link"] for s in ok] == ["https://www.news1.kr/economy/trend/6317332"]
    assert len(out) == 2


def test_all_recorded_speeches_use_allowed_outlets():
    g = yaml.safe_load((DATA / "guidance.yaml").read_text(encoding="utf-8"))
    idx = default_index()
    bad = [(s["date"], s.get("link")) for s in g["speeches"] if idx.identify({"link": s.get("link") or ""})["status"] != "allowed"]
    assert bad == []
