# 연구 메모 · 참고문헌

## 참고문헌
- Kim, Hyerim & Kang, Kyu Ho (2022). The Bank of Korea Watch. *Journal of International Money and Finance*, 126, 102668. DOI: 10.1016/j.jimonfin.2022.102668
- Raftery, A. E., Kárný, M. & Ettler, P. (2010). Online prediction under model uncertainty via dynamic model averaging: Application to a cold rolling mill. *Technometrics*, 52(1), 52–66. DOI: 10.1198/TECH.2009.08104
- Kuttner, K. N. (2001). Monetary policy surprises and interest rates: Evidence from the Fed funds futures market. *Journal of Monetary Economics*, 47(3), 523–544.
- Adrian, T., Crump, R. K. & Moench, E. (2013). Pricing the term structure with linear regressions. *Journal of Financial Economics*, 110(1), 110–138. DOI: 10.1016/j.jfineco.2013.04.009

(Kim & Kang 2022의 서지는 사용자가 제공한 값이다. 이 저장소에서 원문을 열어 확인하지 않았다.)

## 이후 검증할 후보 변수 (이번에는 구현하지 않음)
Kim & Kang (2022)가 다룬 변수를 AWM 가중치·확률 모형의 추가 변수로 검증한다. 구현 전에 원문에서 정의와 자료 출처를 확인한다.
- 한국의 단기금리(예: CD 91일, 통안증권 91일 외 단기물)
- 미국 연방기금금리(정책금리 방향)
- 기대인플레이션

검증 원칙은 AWM과 같다: 금통위 순서의 확장 창, 관측일에 알 수 있던 값만 사용, 금통위 단위 군집 부트스트랩, 변경 회의가 6번뿐인 표본의 한계 표기.

## 대표모형 전환
- 설정: `data/config.yaml`의 `awm.representative` (`m5` | `ois`).
- 화면 확인: 주소 끝에 `?model=ois` 또는 `?model=m5`.
- 시계열: `site/data/awm_series.json`(회의·기준일별 OIS 단독, 통안채 91일, M5). `kind`가 `retro`(사후 재계산)인지 `stored`(당시 저장 예측, `data/awm_log.csv`에 그날 기록된 값)인지 구분한다.
- 기존 기록(`data/prob_log.csv`, `site/data/history.csv`, `data/awm_log.csv`)은 고치지 않는다.

## 2026-11-12 ACM 기간프리미엄 모형 백테스트 (연구용, 공식 확률 미반영)

- 설계(사전 등록, 결과를 보고 바꾸지 않음): `research/acm_backtest.py`. 자료는 ECOS 통안채 91일, 국고채 1·3·5·10년, 통안채 2년, 기준금리(2006-09~). 금요일 주간, 요인 3개, 확장 창 13주마다 재추정(최소 156주). 정책금리를 단기금리로 둔다. `research/fetch_long_yields.py`가 자료를 받는다(`yields_long.csv`는 저장소에 올리지 않음).
- 평가: 2021-01 이후 금통위 46회(인상 12회). 3분류 Brier(낮을수록 좋음).
- 다음 회의(10·20·30영업일 전): ACM 0.79 · 합성 OIS 0.43~0.78 · 통안채 91일 0.41~0.46 · 50:50 결합 0.31~0.40 · 항상 동결 0.63. ACM이 가장 나쁘다. 통계적으로 예측한 정책금리는 시장 91일 금리보다 정보가 적다.
- 그다음 회의(회의 45~90일 전): ACM 0.42 · 기간프리미엄을 빼지 않은 선도금리 0.29 · 항상 동결 0.70. 기간 구분은 2021~22 인상기 ACM 0.73·선도 0.32, 2023~26 ACM 0.27·선도 0.27. 기간프리미엄 보정이 선도금리보다 낫지 않았다.
- 판단: ACM은 채택 근거가 없다. 기간프리미엄(3년물 최신 +0.73%p) 추정이 정책금리 한 번(0.25%p)보다 큰 오차를 낳는다. 오히려 곡선에서 바로 뽑은 선도금리가 그다음 회의 예측에서 단순하면서 낫다. 다음 후보는 선도금리 기반 뒤 회의 추정을 OIS·통안채와 같은 기준으로 비교하는 것이다.
- 한계: AFNS(칼만필터 최대우도)는 구현하지 않았다. 5·10년 포함 6개 만기 곡선으로는 K=3 요인 추정이 약하고, 표본에서 인상 회의가 12회뿐이다. 선도금리 결과는 같은 표본에서 처음 본 것이라 새 회의의 3영업일 전 기록으로 다시 평가하기 전까지 채택하지 않는다.
