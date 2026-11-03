# BOK WATCH 3.0 개발 기록 (브랜치 `bokwatch-3.0`, 미배포)

## 구현됨
- 뉴스 화이트리스트 38곳: `data/press.yaml`, 도메인 검증 `python -m bokwatch.press_verify` → `data/press_verified.json`, 판정 `bokwatch/press.py`
- 공식 정성평가는 허용 언론사 기사 중 중복을 뺀 것만 사용(`ai_judge.analysis_only`). 태깅도 같은 대상만(토큰 절감). 제외 기사의 기존 태그는 보존
- 기사 중복 판정 `bokwatch/dedupe.py`: 재수집·통신사 전재·제목 변경·수정은 가장 먼저 나온 기사만, 같은 사건·독립 보도는 보존
- 기사 근거 유형(직접발언·전문가해석·기자분석·사실전달): 새로 태깅한 기사부터 `source_type`
- 뉴스 지표 4종 `bokwatch/news_metrics.py`: 관심도·방향성·논조 변화·정책 신호 강도, 주요 매파·비둘기파 신호
- AI 탭 "분석 대상 언론사" 블록: 수집·제외 사유·매체 유형별 방향·화이트리스트 전후 비교
- 한국은행 발언 통합 `bokwatch/speech_events.py` → `site/data/speech_events.json`, 가이던스 탭 "행사별 요약"
- 메인 탭 확률 변화 그래프(7·30·90일·전체, 툴팁, 이벤트 표시, 과거 날짜 조회 보존)

## 구현하지 않음
- 본문 기반 평가: 저장소 원칙("기사는 제목·요약·링크만 저장")과 충돌해 제목·요약 기반(저신뢰)으로 유지
- 이벤트 상세 분석 화면, 확률 변화가 큰 날 자동 탐지
- 통방문 핵심 변화 요약(PART 4) 개편, 기관 전망 적중률(PART 5), ACM·AFNS(PART 6-2), BOK INTELLIGENCE·BOK LAB 3분할(PART 7)
- 규칙 기반 발언·표현 분석은 사전에 있는 표현만 본다(문장 의미 비교 아님)

## 확률 계산
공식 확률 산출 로직은 변경하지 않았다(AI 뉴스 압력만 화이트리스트·중복 제거 영향).
