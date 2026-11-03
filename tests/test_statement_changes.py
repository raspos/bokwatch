"""통방문 범주별 핵심 변화(규칙 기반)."""
from bokwatch import statement_changes as SC

PREV = ("금융통화위원회는 기준금리를 현재의 2.75% 수준에서 3.00%로 상향 조정하여 통화정책을 운용하기로 하였다. "
        "이러한 상황에서는 선제적 대응을 통해 물가 오름세의 확산을 방지하는 것이 중요하다. 소비는 완만하게 회복되었다.")
CUR = ("금융통화위원회는 기준금리를 현재의 3.00% 수준에서 유지하여 통화정책을 운용하기로 하였다. "
       "물가가 높은 오름세를 이어가고 있다. 소비는 완만하게 회복되었다.")


def by_cat(rows):
    return {r["category"]: r for r in rows}


def test_each_clause_goes_to_one_category_and_decision_clause_is_policy_stance():
    assert SC.best_category("기준금리를 현재의 3.00% 수준에서 유지하여") == "향후 통화정책 운용 방향"
    assert SC.best_category("수도권 주택가격은 높은 오름세를 지속하였으며") == "가계부채"
    assert SC.best_category("아무 관련 없는 문장입니다 가나다라") is None


def test_changed_category_has_terms_and_read_unchanged_category_has_none():
    rows = by_cat(SC.compare(PREV, CUR))
    pol = rows["향후 통화정책 운용 방향"]
    assert pol["change"] == "표현 변경" and "상향" in pol["gone_terms"] and "유지" in pol["new_terms"]
    assert any("상향 조정" in r for r in pol["reads"])            # 해석은 규칙표에 걸린 경우에만
    assert rows["소비"]["change"] == "변화 없음" and rows["소비"]["reads"] == [] and rows["소비"]["importance"] == 0


def test_scope_limits_interpretation_and_unknown_is_withheld():
    # '선제'가 빠진 해석은 물가·정책 범주에서만. 규칙표에 없는 변화는 해석 보류
    rows = by_cat(SC.compare("가계대출은 증가하였다.", "가계대출은 감소하였다."))
    assert rows["가계부채"]["reads"] == ["해석 보류(규칙표에 해당 없음)"]


def test_new_and_dropped_category():
    rows = by_cat(SC.compare("소비는 회복되었다.", "고용은 개선되었다."))
    assert rows["소비"]["change"] == "삭제" and rows["고용"]["change"] == "신설"
