# AI 작업 체계 지표

지표 정의는 [plan.md](plan.md) 11장에 있다. 이 문서에는 측정값을 기록한다. 새 측정값은 위에 추가하고, 이전 값은 지우지 않는다.

## 월간 리뷰

매월 첫 주에 지난달 주간 리포트(`report: weekly` 이슈)를 모아 리뷰한 결과를 위에 추가한다. 절차와 지표 정의는 [playbooks/operations.md](playbooks/operations.md)에 있다.

| 월 | AI PR(무수정 승인) | 변경 줄 중앙값 | 등록한 스캔 후보 | 동결 위반(클래스) | 결정 사항 |
|---|---|---:|---:|---:|---|

## 파이프라인 검증 기록

| 일자 | 이슈 / PR | 트랙 | 결과 | 리뷰 회차 | 사람 수정 | 발견한 시스템 결함 |
|---|---|---|---|---|---|---|
| 2026-11-19 | #5 / #9 | 버그 수정(그룹 A) | 재현 테스트 4/15 실패 → 수정 후 15/15, gateway 67건 통과 | 1(통과, 차단 0, 권고 6) | 머지 대기 | Spotless worktree 미지원(8.10.4로 해결), test-writer 빈 보고와 들여쓰기 불일치, implementer 수치 근거 부족(지침 보강) |

## 문서 교정(`/doc-review`) 측정

| 일자 | 대상 | 방식 | 호출 | 소요 | 입력 토큰 | 생각 토큰 | 결과 |
|---|---|---|---:|---:|---:|---:|---|
| 2026-11-19 | PR #10 문서 16개와 본문 | hydrogen-medium, 문서마다 호출 | 18 | - | - | - | 제안 37건 |
| 2026-11-19 | 같은 문서 | neon-high, 문서마다 호출(4개 병렬) | 18 | 7분 52초 | 약 21만(추정) | 약 11만(추정) | 제안 130건, 반영 123건 |
| 2026-11-19 | 사람이 읽는 문서 8개(바뀐 부분 473줄)와 오류를 심은 문서 | neon-high, 묶음(200줄), 동시 호출 | 3 | 2분 26초 | 4.5만 | 4.0만 | 심은 오류 10/10 검출, 자동으로 걸러진 제안 2건 |
| 2026-11-20 | PR #13 본문(54줄, `--full`) | neon-high, 줄 전체 재작성 허용 전 | 1 | 1분 21초 | 1.3만 | 0.9만 | 제안 2건, 재작성 0건 |
| 2026-11-20 | 같은 본문 | neon-high, 줄 전체 재작성 허용 후 | 1 | 4분 29초 | 1.3만 | 1.6만 | 제안 12건, 재작성 4건(맥락 없는 도입문 포함), 자동으로 걸러진 제안 0건 |
| 2026-11-20 | `docs/ai-system` 문서 전체(11개, 1,253줄, `--full`) | neon-medium, 묶음(200줄), 동시 호출 | 8 | 2분 28초 | 12.2만 | 5.4만 | 제안 40건(반영 39, 보류 1), 자동으로 걸러진 제안 3건 중 1건은 직접 반영 |

관찰:
- 오류 10개를 심은 문서에서는 hydrogen과 neon 모두 10개를 찾았다. 같은 실제 문서에서는 hydrogen이 1건, hydrogen-high가 0건, neon-medium이 5건, neon-high가 8건(서술어 누락, 의미 중복 같은 미묘한 문제)을 제안했다.
- `agy`는 호출마다 입력 약 1.1만 토큰과 약 10초가 고정으로 든다. 문서 1개는 입력을 900 토큰 정도만 늘린다.

## Gemini 코드 리뷰(`/gemini-review`) 측정

| 일자 | 대상 | 모델 | 호출 | 소요 | 입력 토큰 | 생각 토큰 | 결과 |
|---|---|---|---:|---:|---:|---:|---|
| 2026-11-20 | PR #9(파일 4개, diff 127줄) | neon-high, 파일 읽기 제한 없음 | 1 | 7분 29초 | 33만 | 1.8만 | 지적 2건(테스트 보완, 모두 타당) |
| 2026-11-20 | 같은 PR | neon-high, 파일 읽기 최대 5개 | 1 | 6분 37초 | 6.6만 | 1.4만 | 지적 2건(테스트 보완, 모두 타당) |
| 2026-11-20 | 같은 PR | neon-medium | 1 | 47초 | 1.7만 | 0.4만 | 지적 0건 |
| 2026-11-20 | 버그 4개를 심은 브랜치(diff 35줄) | neon-high | 1 | 1분 50초 | 2.3만 | 0.8만 | 4/4 검출(차단 3, 주요 1), 오탐 0 |
| 2026-11-20 | 같은 브랜치 | neon-medium | 1 | 1분 10초 | 2.3만 | 0.3만 | 4/4 검출, 오탐 0 |
| 2026-11-20 | PR #12(Python 스크립트, 워크플로우, diff 555줄) | neon-high | 1 | 3분 56초 | 6.9만 | 2.6만 | 지적 7건(주요 2, 참고 5), 모두 타당해 게시하고 반영 |
| 2026-11-20 | 이 리뷰 스크립트 자체(diff 685줄) | neon-high | 2 | 3분 36초 | 7.5만 | 3.2만 | 지적 7건(주요 4, 참고 3), 모두 타당해 반영 |

심은 버그: 재고 복구를 커밋 전 트랜잭션 안으로 옮김, 실패 시 멱등 기록 누락, 이벤트 상품 ID 자리에 SKU ID 사용, 주문 만료 조건 반전.

관찰:
- 분명한 버그는 두 모델 모두 찾는다. 실제 PR에서 미묘한 지적(테스트가 실제로 검증하지 않는 부분)은 neon-high만 냈다. 문서 교정과 같은 양상이라 기본 모델은 neon-high로 둔다.
- PR #12에서는 infra-reviewer(Claude)가 보지 못한 실제 버그 2건(머지 커밋 파일 누락, 이슈 표 누락)을 찾았다. 다른 모델의 2차 의견이 효과가 있었다.
- 모델이 맥락 파일을 많이 읽으면 입력 토큰이 크게 늘어난다(33만). 프롬프트로 읽을 파일을 5개로 제한하자 6.6만으로 줄었고 지적 품질은 같았다. 소요 시간은 생성량에 좌우되어 크게 줄지 않았다.

## 기준선(2026-11-18, 1단계 안전망 도입 시점)

측정 환경: 로컬 WSL2, JDK 21(Temurin 21.0.13), Docker 사용 가능. 명령은 `./gradlew test --continue`, 커버리지 요약은 `python3 scripts/ai/coverage-summary.py --markdown`.

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

위반 목록은 각 서비스의 `src/test/resources/archunit_store`에 있다. 2026-11-18 결정에 따라 AI 작업 체계가 완성된 뒤 리팩토링 트랙에서 개선한다.

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

라인 수는 JaCoCo가 실행 가능한 줄로 센 값이다(소스 줄 수와 다르다).

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
- **알림(`user-service` `notification`)**: 하위 10개 중 7개가 이 도메인이다. 이 도메인을 리팩토링하거나 고치려면 특성 테스트를 먼저 써야 한다.
- **Kafka 발행 코드**: outbox를 거치지 않는 `product.infrastructure.kafka.publisher`와 `libs/common` 이벤트 레코드의 커버리지가 낮다. 이벤트 관련 작업은 event-reviewer(2단계)와 함께 다룬다.
