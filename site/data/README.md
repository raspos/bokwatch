# BOK워치 데이터 파일 설명

화면의 **대표 확률은 'BOK WATCH 종합 예측'**입니다(2026-10-29~). 합성 KOFR OIS와 통안증권 91일 두 모형의 확률을 50:50으로 섞은 값입니다. 시장 거래 확률이 아니라 통계 추정입니다.

| 파일 | 담긴 확률 | 비고 |
|---|---|---|
| `awm_series.json` | **종합 예측(m5)**, 합성 OIS 단독(ois), 통안채 91일 단독(msb91) | 회의·기준일별. `kind`가 stored면 당시 저장 값, retro면 사후 재계산 |
| `snapshots/*.json`, `history.csv` | **합성 KOFR OIS 단독**(`method: kofr_ois`) | 종합 예측으로 바꾸기 전 구조라 이 파일의 `p_hike`는 대표 확률이 아님 |
| `prob_log.json` | **합성 KOFR OIS 단독**(날짜별 기록) | `p_basis`에 기준을 적었다. 같은 날 종합 예측은 `awm_series.json` |
| `kofr_ois.json` | 합성 KOFR OIS 계산 과정 | 구성 요소 |

- 합성 KOFR OIS는 거래된 OIS 금리가 아니라 CD 시가평가수익률에서 과거 스프레드를 뺀 추정치입니다.
- 인용할 때는 어느 값인지(종합 예측, 합성 OIS 단독, 통안채 단독)와 금리 기준일을 함께 적습니다.
