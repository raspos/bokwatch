"""뉴스 화이트리스트(38개 언론사) 검사: 설정, 별칭, 도메인 판정, 포털 링크, 제외 기사가 점수에 안 들어감."""
from datetime import datetime, timedelta

from bokwatch import ai_judge, press

NOW = datetime.fromisoformat("2026-11-03T09:00+09:00")


def idx():
    return press.PressIndex()


def test_exactly_38_outlets_and_config_is_consistent():
    outlets = press.load_outlets(raw=True)
    assert len(outlets) == 38
    assert press.validate_config(outlets) == []
    # 유형별 개수: 종합일간지7 지상파3 경제지10 종편3 통신·정보5 IT3 방송보도3 경제전문3 인터넷1
    from collections import Counter
    c = Counter(o["type"] for o in outlets)
    assert c["종합일간지"] == 7 and c["지상파방송"] == 3 and c["경제지"] == 10 and c["종합편성채널"] == 3
    assert c["통신사"] + c["경제정보"] == 5 and c["IT산업전문"] == 3 and c["보도채널"] == 3 and c["경제전문"] == 3 and c["종합인터넷"] == 1


def test_every_outlet_has_a_verified_domain():
    """도메인은 추측이 아니라 press_verify가 실제 페이지에서 확인한 것만 쓴다."""
    for o in press.load_outlets():
        assert o["domains"], f"검증된 도메인 없음: {o['name']}"


def test_aliases_resolve_to_same_outlet():
    i = idx()
    for label in ("ZDNet Korea", "ZD넷", "지디넷코리아", "ZD넷코리아"):
        assert i.by_label(label) == "zdnet", label
    for label in ("SBS Biz", "SBS비즈", "SBS 비즈"):
        assert i.by_label(label) == "sbsbiz", label
    assert i.by_label("CBS노컷뉴스") == "nocutnews" and i.by_label("Yonhap News") == "yna"


def test_host_matching_is_most_specific():
    i = idx()
    assert i.match_host("biz.chosun.com") == "chosunbiz" and i.match_host("chosun.com") == "chosun"
    assert i.match_host("biz.sbs.co.kr") == "sbsbiz" and i.match_host("news.sbs.co.kr") == "sbs"
    assert i.match_host("marketin.edaily.co.kr") == "edaily"          # 서브도메인
    assert i.match_host("coinreaders.com") is None and i.match_host("wowtv.co.kr") is None     # 한국경제TV는 38곳에 없다


def test_identify_allows_excludes_and_flags_portal():
    i = idx()
    ok = i.identify({"link": "https://www.hankyung.com/article/2026110301"})
    assert ok["status"] == "allowed" and ok["outlet"] == "hankyung"
    out = i.identify({"link": "https://www.coinreaders.com/1"})
    assert out["status"] == "excluded" and out["outlet"] is None
    portal = i.identify({"link": "https://n.news.naver.com/mnews/article/001/0001"})
    assert portal["status"] == "review" and portal["outlet"] is None        # 원출처 불명은 점수에서 빼고 검토 대상으로
    # 이름만 같은 다른 도메인은 허용하지 않는다
    assert i.identify({"link": "https://fake-hankyung.example/a", "press_label": "한국경제"})["status"] != "allowed"


def _art(i, link, status):
    return {"id": f"a{i}", "title": f"t{i}", "summary": "", "press": "x", "link": link, "press_status": status,
            "published": (NOW - timedelta(hours=i)).isoformat(timespec="minutes")}


def test_excluded_articles_do_not_enter_score():
    arts = [_art(0, "L0", "allowed"), _art(1, "L1", "excluded"), _art(2, "L2", "review")]
    assert [a["id"] for a in ai_judge.official_only(arts)] == ["a0"]
    tags = {a["id"]: {"relevant": True, "direction": "인상 압력", "strength": 3, "factor": "물가", "model": "m", "tagged": "t"} for a in arts}
    official = ai_judge.official_only(arts)
    assert ai_judge.pressure_index(official, tags, NOW - timedelta(hours=72))["n_articles"] == 1
    # 제외 기사는 새로 태깅하지 않는다(토큰 절감)
    class FC:
        calls = []
    only_a0 = {"a0": tags["a0"]}          # 허용 기사는 이미 태깅됨 → 남은 건 제외·검토 기사뿐이므로 모델을 부르지 않는다
    n, errs = ai_judge.classify(FC(), {"max_new_per_run": 10, "batch_size": 5, "factors": ["물가"], "model": "m"}, arts, only_a0)
    assert n == 0 and errs == []


def test_source_mix_counts_old_tags_as_unclassified():
    arts = [_art(0, "L0", "allowed"), _art(1, "L1", "allowed")]
    tags = {"a0": {"relevant": True, "direction": "인상 압력", "source_type": "직접발언"},
            "a1": {"relevant": True, "direction": "중립"}}
    m = ai_judge.source_mix(arts, tags, NOW - timedelta(hours=72))
    assert m["직접발언"]["n"] == 1 and m["직접발언"]["인상 압력"] == 1 and m["미분류"]["n"] == 1
