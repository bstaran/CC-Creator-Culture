# AI 작업 체계 지표

지표 정의는 [plan.md](plan.md) 11장에 있다. 이 문서는 측정값을 기록한다. 새 측정은 위에 추가하고, 이전 값은 지우지 않는다.

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
| `order-service` `CartConcurrencyTest` 1건 | "비결정적 테스트라 CI 오류로 인한 비활성화". 장바구니 최대 개수 초과가 동시 요청에서 가능함을 보여 주는 테스트 | 버그 수정(동시성 제어 여부 결정 필요) |
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
