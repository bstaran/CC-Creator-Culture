# AI 개발 하네스 지표

지표 정의는 [plan.md](plan.md) 11장에 있습니다. 측정값은 이 문서에 누적 기록하며, 새 기록은 위에 추가하고 이전 기록은 지우지 않습니다. 주요 요약은 [README.md](README.md)의 "검증 결과"에 있습니다.

## 월간 리뷰

매월 첫 주에 지난달 주간 리포트(`report: weekly` 이슈)를 모아 리뷰한 결과를 아래 표에 추가합니다. 절차와 지표 정의는 [playbooks/operations.md](playbooks/operations.md)에 있습니다.

| 월 | AI PR(무수정 승인) | 변경 줄 중앙값 | 등록한 스캔 후보 | 동결 위반(클래스) | 결정 사항 |
|---|---|---:|---:|---:|---|

## 파이프라인 검증 기록

| 일자 | 이슈 / PR | 트랙 | 결과 | 리뷰 회차 | 수동 수정 | 발견한 시스템 결함 |
|---|---|---|---|---|---|---|
| 2026-11-20 | [#7](https://github.com/bstaran/CC-Creator-Culture/issues/7) / [PR #15](https://github.com/bstaran/CC-Creator-Culture/pull/15) | 리팩토링(그룹 A) | 특성 테스트 5개 선행 커밋, 리팩토링 전후 786개 통과(건너뜀 1), 테스트 파일과 동결 목록 변경 없음 | 1(구조, 이벤트, Gemini 모두 통과, 차단 0) | 머지 대기 | 리뷰어에게 diff 내용 대신 diff 명령만 전달(리뷰어는 git을 실행할 수 없음), implementer가 빌드 종료 코드를 확인하지 못함 |
| 2026-11-19 | [#5](https://github.com/bstaran/CC-Creator-Culture/issues/5) / [PR #9](https://github.com/bstaran/CC-Creator-Culture/pull/9) | 버그 수정(그룹 A) | 재현 테스트 4/15 실패 → 수정 후 15/15, gateway 67건 통과 | 1(통과, 차단 0, 권고 6) | 없음(PR 생성 후 커밋 없이 머지) | Spotless worktree 미지원(8.10.4로 해결), test-writer 빈 보고와 들여쓰기 불일치, implementer 수치 근거 부족(지침 보강) |

## 문서 교정(`/doc-review`) 측정

모델 표기: `hydrogen`은 경량 Gemini 모델, `neon`은 고성능 모델이며, 이름 끝의 `medium`과 `high`는 추론 강도(reasoning effort)를 뜻합니다. 호출에는 Antigravity CLI(`agy`)를 사용합니다.

| 일자 | 대상 | 방식 | 호출 | 소요 | 입력 토큰 | 추론 토큰 | 결과 |
|---|---|---|---:|---:|---:|---:|---|
| 2026-11-19 | [PR #10](https://github.com/bstaran/CC-Creator-Culture/pull/10) 그룹 B, C 도입 문서 16개와 PR 본문 | hydrogen-medium, 문서마다 호출 | 18 | - | - | - | 제안 37건 |
| 2026-11-19 | PR #10 문서(위와 동일) | neon-high, 문서마다 호출(4개 병렬) | 18 | 7분 52초 | 약 21만(추정) | 약 11만(추정) | 제안 130건, 반영 123건 |
| 2026-11-19 | [PR #11](https://github.com/bstaran/CC-Creator-Culture/pull/11) 배치 재설계 검증(변경 문서 8개 473줄 + 오류 10건 주입 로컬 샘플) | neon-high, 묶음(200줄), 동시 호출 | 3 | 2분 26초 | 4.5만 | 4.0만 | 심은 오류 10/10 검출, 자동으로 걸러진 제안 2건 |
| 2026-11-20 | [PR #13](https://github.com/bstaran/CC-Creator-Culture/pull/13) PR 본문(54줄, `--full`) | neon-high, 줄 전체 재작성 허용 전 | 1 | 1분 21초 | 1.3만 | 0.9만 | 제안 2건, 재작성 0건 |
| 2026-11-20 | PR #13 본문(위와 동일) | neon-high, 줄 전체 재작성 허용 후 | 1 | 4분 29초 | 1.3만 | 1.6만 | 제안 12건, 재작성 4건(맥락 없는 도입문 포함), 자동으로 걸러진 제안 0건 |
| 2026-11-20 | [PR #16](https://github.com/bstaran/CC-Creator-Culture/pull/16) `docs/ai-system` 전체(11개, 1,253줄, `--full`, 반영 [`29436e4`](https://github.com/bstaran/CC-Creator-Culture/commit/29436e4)) | neon-medium, 묶음(200줄), 동시 호출 | 8 | 2분 28초 | 12.2만 | 5.4만 | 제안 40건(반영 39, 보류 1), 자동으로 걸러진 제안 3건 중 1건은 직접 반영 |

관찰:
- 오류 10개를 심은 문서에서는 `hydrogen`과 `neon` 모두 10개를 찾았습니다. 같은 실제 문서에서는 `hydrogen`이 1건, `hydrogen-high`가 0건, `neon-medium`이 5건, `neon-high`가 8건(서술어 누락, 의미 중복 같은 미묘한 문제)을 제안했습니다.
- `agy`는 호출마다 입력 약 1.1만 토큰과 약 10초가 고정으로 듭니다. 반면 문서 1개를 추가할 때 늘어나는 입력은 900 토큰 수준에 불과합니다.

## 문서 작성(`/doc-write`) 측정

| 일자 | 대상 | 모델 | 호출 | 소요 | 입력 토큰 | 출력 토큰 | 추론 토큰 | 결과 |
|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-11-23 | `docs/ai-system/guide.md` 두 절 수정(사실 초안 17줄) | `gemini-4-neon-medium` | 1 | 43초 | 13874 | 4859 | 2650 | 사실 검사 1회 통과, 다시 쓰기 없음 |
| 2026-11-23 | `docs/ai-system/README.md` 표 한 행 수정(초안 3줄) | `gemini-4-neon-medium` | 1 | 33초 | 13932 | 3626 | 1201 | 사실 검사 1회 통과, 다시 쓰기 없음 |
| 2026-11-23 | `docs/ai-system/decisions.md` 절 하나 추가(초안 6줄) | `gemini-4-neon-medium` | 1 | 51초 | 15144 | 5919 | 2237 | 사실 검사 1회 통과, 다시 쓰기 없음 |
| 2026-11-23 | `docs/ai-system/README.md` 표 한 행 수정(초안 3줄) | `gemini-4-neon-medium` | 1 | 26초 | 6726 | 2926 | 499 | 사실 검사 1회 통과, 다시 쓰기 없음 |
| 2026-11-23 | `README.md` 한 줄 수정(초안 3줄) | `gemini-4-neon-medium` | 1 | 24초 | 5951 | 2404 | 714 | 사실 검사 1회 통과, 다시 쓰기 없음 |
| 2026-11-23 | `docs/ai-system/metrics.md` 절 하나 추가(초안 15줄) | `gemini-4-neon-medium` | 2 | 130초 | 16909 | 15070 | 6455 | 1회차 거부, 2회차 통과 |

관찰:
- 5건 모두 지정한 절만 바뀌었고, 지정하지 않은 부분은 그대로였습니다(`git diff`로 확인).
- 기존 문서를 고칠 때도 문서 전체를 다시 출력하므로 출력 토큰은 고친 양이 아니라 문서 길이에 비례합니다.
- 사실 초안에 바꾸기 전 값(스킬 11개)을 적으면 빠진 사실 경고에 나옵니다. 바뀐 값을 쓴 결과이므로 무시했습니다.
- 위 `metrics.md` 1회차는 사실 초안의 작성 메모에만 적은 `/doc-write`를 결과물이 제목에 쓰자 새 사실로 거부됐고, 2회차는 통과했지만 제목에서 `/doc-write`가 빠졌습니다. 작성 메모에 적은 식별자도 결과물에 쓸 수 있게 `scripts/ai/doc-write.py`를 고치고 회귀 테스트를 추가했습니다.

## Gemini 코드 리뷰(`/gemini-review`) 측정

| 일자 | 대상 | 모델 | 호출 | 소요 | 입력 토큰 | 추론 토큰 | 결과 |
|---|---|---|---:|---:|---:|---:|---|
| 2026-11-20 | [PR #9](https://github.com/bstaran/CC-Creator-Culture/pull/9) 게이트웨이 라우트 수정(코드/설정 4개, 127줄) | neon-high, 파일 읽기 제한 없음 | 1 | 7분 29초 | 33만 | 1.8만 | 지적 2건(테스트 보완, 모두 타당) |
| 2026-11-20 | PR #9(위와 동일) | neon-high, 파일 읽기 최대 5개 | 1 | 6분 37초 | 6.6만 | 1.4만 | 지적 2건(테스트 보완, 모두 타당) |
| 2026-11-20 | PR #9(위와 동일) | neon-medium | 1 | 47초 | 1.7만 | 0.4만 | 지적 0건 |
| 2026-11-20 | 결함 주입 실험(주문 도메인 버그 4건, 로컬 임시 브랜치, 35줄, PR 없음) | neon-high | 1 | 1분 50초 | 2.3만 | 0.8만 | 4/4 검출(차단 3, 주요 1), 오탐 0 |
| 2026-11-20 | 결함 주입 실험(위와 동일) | neon-medium | 1 | 1분 10초 | 2.3만 | 0.3만 | 4/4 검출, 오탐 0 |
| 2026-11-20 | [PR #12](https://github.com/bstaran/CC-Creator-Culture/pull/12) 주간 리포트 자동화(555줄, 반영 [`905b9da`](https://github.com/bstaran/CC-Creator-Culture/commit/905b9da)) | neon-high | 1 | 3분 56초 | 6.9만 | 2.6만 | 지적 7건(주요 2, 참고 5), 모두 타당해 게시하고 반영 |
| 2026-11-20 | [PR #13](https://github.com/bstaran/CC-Creator-Culture/pull/13) `code-review.py` 자체 리뷰(685줄, 반영 [`e229532`](https://github.com/bstaran/CC-Creator-Culture/commit/e229532)) | neon-high | 2 | 3분 36초 | 7.5만 | 3.2만 | 지적 7건(주요 4, 참고 3), 모두 타당해 반영 |

결함 주입 실험(로컬 임시 브랜치, 검출률 확인 후 폐기): 주문 도메인 코드에 의도적으로 주입한 버그 4건(재고 복구를 커밋 전 트랜잭션 안으로 이동, 실패 시 멱등 기록 누락, 이벤트 상품 ID 자리에 SKU ID 사용, 주문 만료 조건 반전)을 대상으로 테스트했습니다.

관찰:
- 분명한 버그는 두 모델 모두 잘 찾지만, 실제 PR에서 미묘한 지적(테스트가 실제로 검증하지 않는 빈틈)은 `neon-high`만 짚어냈습니다. 문서 교정과 같은 경향이라 코드 리뷰 기본 모델은 `neon-high`로 정했습니다.
- PR #12에서는 `infra-reviewer`(Claude)가 놓친 실제 버그 2건(머지 커밋 파일 누락, 이슈 표 누락)을 찾아 이종 모델의 2차 리뷰 효과를 확인했습니다.
- 모델이 맥락 파일을 제한 없이 읽으면 입력 토큰이 33만까지 급증했습니다. 프롬프트로 읽을 파일을 5개로 제한하자 입력은 6.6만으로 줄었고 지적 품질은 그대로 유지됐습니다. 소요 시간은 생성량에 좌우되어 크게 줄지 않았습니다.

## 기준선(2026-11-18, 1단계 안전망 도입 시점)

측정 환경: 로컬 WSL2, JDK 21(Temurin 21.0.13), Docker 사용 가능. 명령은 `./gradlew test --continue`, 커버리지 요약은 `python3 scripts/ai/coverage-summary.py --markdown`으로 수집했습니다.

### 테스트

| 모듈 | 테스트 | 실패 | 건너뜀 |
|---|---:|---:|---:|
| `apps/order-service` | 781 | 0 | 1 |
| `apps/product-service` | 390 | 0 | 1 |
| `apps/user-service` | 279 | 0 | 1 |
| `infra/gateway` | 52 | 0 | 0 |
| `libs/common` | 40 | 0 | 0 |
| `infra/config-server` | 2 | 0 | 0 |
| `infra/eureka-server` | 1 | 0 | 0 |
| **합계** | **1545** | **0** | **3** |

건너뛴 테스트(모두 `@Disabled`, 이후 정리 후보):

| 테스트 | 사유(코드 주석) | 후보 트랙 |
|---|---|---|
| `order-service` `CartConcurrencyTest` 1건 | "비결정적 테스트라 CI 오류로 인한 비활성화". 동시 요청 시 장바구니 최대 개수를 초과할 수 있음을 보여 주는 테스트 | 버그 수정(동시성 제어 여부 결정 필요) |
| `product-service` `ProductCreatedKafkaPublisherIntegrationTest` | 사유 없음 | 조사(비활성화 이유 확인) |
| `user-service` `UserServiceApplicationTests` | "PostgreSQL 통합 테스트에서 애플리케이션 컨텍스트를 검증한다" | 없음(다른 테스트가 대체) |

### 계층 규칙(ArchUnit, 동결된 기존 위반)

| 서비스 | domain → 바깥 계층 | application → infrastructure/presentation |
|---|---:|---|
| `user-service` | 0 | 10개 클래스(의존 79건) |
| `product-service` | 0 | 11개 클래스(의존 44건) |
| `order-service` | 0 | 13개 클래스(의존 53건) |
| **합계** | **0** | **34개 클래스(의존 176건)** |

위반 목록은 각 서비스의 `src/test/resources/archunit_store`에 있습니다. 2026-11-18 결정에 따라 하네스가 완성된 뒤 리팩토링 트랙에서 점진적으로 개선합니다.

### 커버리지(JaCoCo)

| 모듈 | 라인 | 분기 | 라인 수 |
|---|---:|---:|---:|
| `apps/order-service` | 97.3% | 84.3% | 1978 |
| `apps/product-service` | 86.1% | 77.7% | 2704 |
| `apps/user-service` | 67.7% | 50.0% | 1438 |
| `infra/gateway` | 96.7% | 91.7% | 150 |
| `libs/common` | 66.5% | 20.0% | 164 |
| `infra/config-server` | 33.3% | - | 3 |
| `infra/eureka-server` | 33.3% | - | 3 |

라인 수는 JaCoCo가 실행 가능한 줄을 기준으로 집계한 값입니다(소스 전체 줄 수와는 다릅니다).

### 커버리지가 낮은 영역(라인 30줄 이상 패키지, 하위 10개)

| 라인 | 모듈 | 패키지 | 라인 수 | 분기 |
|---:|---|---|---:|---:|
| 0.0% | `user-service` | `notification.domain.entity` | 46 | - |
| 1.2% | `user-service` | `notification.application.service` | 81 | 0.0% |
| 1.7% | `user-service` | `notification.infrastructure.messaging.kafka` | 58 | 0.0% |
| 11.1% | `user-service` | `notification.domain.service` | 63 | 0.0% |
| 13.2% | `user-service` | `notification.infrastructure.persistence.adapter` | 38 | 0.0% |
| 20.0% | `libs/common` | `kafka.event` | 35 | 0.0% |
| 24.2% | `user-service` | `notification.infrastructure.external.slack` | 66 | 16.7% |
| 31.9% | `product-service` | `product.infrastructure.kafka.publisher` | 69 | 30.0% |
| 33.3% | `user-service` | `notification.domain.model` | 81 | 0.0% |
| 41.2% | `product-service` | `leaderboard.domain.entity` | 34 | - |

관찰:
- **알림(`user-service` `notification`)**: 하위 10개 중 7개가 이 도메인에 몰려 있습니다. 이 영역을 리팩토링하거나 수정하려면 특성 테스트를 먼저 작성해야 합니다.
- **Kafka 발행 코드**: outbox를 거치지 않는 `product.infrastructure.kafka.publisher`와 `libs/common` 이벤트 레코드의 커버리지가 낮습니다. 이벤트 관련 작업은 `event-reviewer`와 함께 검증합니다.
