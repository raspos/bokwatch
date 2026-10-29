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
