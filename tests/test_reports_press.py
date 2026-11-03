"""보고서 출처 제한: 허용 38개 매체 기사 링크만 표·집계에 쓴다. 링크가 없거나 밖이면 제외."""
from datetime import date

from bokwatch import reports as R


def rep(inst, link, pub="2026-11-03", call="인상"):
    return {"institution": inst, "published": pub, "link": link, "calls": {"2026-11-26": {"call": call}}, "terminal": 3.5}


def test_annotate_allowed_excluded_and_no_link():
    rs = R.annotate_press([rep("A", "https://www.hankyung.com/article/1"), rep("B", "https://news.jkn.co.kr/post/1"), rep("C", None)])
    st = {r["institution"]: r["press_status"] for r in rs}
    assert st == {"A": "allowed", "B": "excluded", "C": "excluded"}
    assert rs[0]["press_name"] == "한국경제" and rs[2]["press_reason"].startswith("링크 없음")


def test_consensus_counts_only_allowed_sources(monkeypatch):
    rs = [rep("A", "https://www.hankyung.com/a"), rep("B", "https://news.jkn.co.kr/b", call="동결"), rep("C", None, call="동결")]
    monkeypatch.setattr(R, "load_reports", lambda: {"reports": rs, "kofia_survey": [], "asof": "2026-11-03"})
    out = R.build_reports(["2026-11-26"], date(2026, 11, 3))
    assert [x["institution"] for x in out["reports"]] == ["A"] and out["press_excluded"] == 2
    assert out["consensus"]["by_meeting"]["2026-11-26"]["counts"] == {"인상": 1}      # 밖 출처의 동결 전망은 집계에 없다
