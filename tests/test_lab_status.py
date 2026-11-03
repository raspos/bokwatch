"""BOK LAB 현황: 수집하지 않는 데이터는 '미수집'으로 남기고 값을 만들지 않는다. ACM·AFNS는 한 것만 완료로 적는다."""
from bokwatch import lab_status as L


def test_uncollected_items_have_no_numbers_and_synthetic_ois_is_labeled_estimate():
    r = L.build()
    by = {x["name"]: x for x in r["data"]}
    for k in ("국고채 5년물", "국고채 10년물", "KOFR 기반 기간금리", "실제 거래 기반 KOFR-OIS"):
        assert by[k]["status"] == "미수집" and by[k]["n"] is None
    assert by["합성 KOFR OIS"]["status"] == "추정치(자체 산출)"
    assert by["CD 91일물"]["status"] == "수집 중" and by["CD 91일물"]["n"] > 1000


def test_acm_afns_status_is_honest_and_changelog_sorted():
    r = L.build()
    done = [a for a in r["acm_afns"] if a["status"] == "완료"]
    assert done == []                                   # 완료로 적을 단계는 아직 없다
    assert r["acm_afns"][0]["status"] == "부분 완료" and len(r["acm_afns"]) == 7
    dates = [c["date"] for c in r["changelog"]]
    assert dates == sorted(dates, reverse=True) and any("종합 예측" in c["change"] for c in r["changelog"])
