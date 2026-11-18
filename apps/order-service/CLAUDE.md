# order-service

장바구니(`cart`), 주문(`order`), 결제(`payment`), 쿠폰(`coupon`). 루트 `CLAUDE.md` 규칙을 먼저 따른다.

## 테스트

- 실행: `./gradlew :apps:order-service:test`
- 통합 테스트와 영속성 테스트는 Testcontainers PostgreSQL(`ddl-auto: create-drop`)을 사용한다(`AbstractIntegrationTest` 상속 테스트는 `application-test.yml` 사용). `disabledWithoutDocker = true`가 없는 테스트도 있어 로컬 전체 실행에는 Docker가 필요하다. CI는 PostgreSQL 서비스 컨테이너를 함께 사용한다.
- `src/test/resources/application.properties`에서 `order.expiration.enabled`와 `order.event-outbox.enabled`가 기본 비활성화되어 있으므로, 해당 스케줄러나 릴레이를 검증하는 테스트는 속성을 켜고 확인한다.
- 테스트 설정이 `ddl-auto: create-drop`을 사용하므로 잠금(`FOR UPDATE SKIP LOCKED`), 네이티브 쿼리, Flyway 마이그레이션을 바꿨다면 단위/로컬 통과만으로 판단하지 않고 PostgreSQL 기반 통합 테스트와 CI 결과까지 확인한다.

## 주문 흐름에서 지킬 것

- **멱등성**: 주문 명령은 `IdempotencyKey`와 요청 해시로 중복을 막는다(`OrderCommandIdempotencyService`, `p_order_command_requests`). 주문 생성과 취소 경로를 바꿀 때 이 검사를 우회하지 않는다.
- **트랜잭션 경계**: `OrderCreationService`는 외부 호출(재고 Feign)을 조율하고, DB 변경은 `*TransactionService`가 맡는다. Feign 호출을 DB 트랜잭션 안으로 옮기지 않는다. `MockPaymentService.process`는 `Propagation.NEVER`다.
- **재고**: `product-service`의 `POST /internal/v1/stocks/deduct`, `/restore`를 Feign(`ProductStockClient`)으로 호출한다. 차감 후 실패하면 복구 경로가 실행되는지 확인한다.
- **이벤트 발행**: `order.paid`, `order.canceled`, `order.notification`은 같은 트랜잭션에서 `p_order_event_outbox`에 행을 쓰고 `OrderEventOutboxRelay`가 발행한다. `KafkaTemplate`을 직접 호출하지 않는다. 릴레이는 재발행이 가능하므로(at-least-once) 소비자 쪽 멱등성을 전제로 한다.
- **만료**: `OrderExpirationScheduler`가 미결제 주문을 만료시킨다. 만료는 `order.notification`만 쓰고 `order.canceled`는 쓰지 않는다(리더보드 점수에 영향 없음). 의도된 동작이므로 바꾸려면 이슈로 확인한다.

## 쿠폰

- 선착순 발급은 Redis Lua(`coupon-reserve.lua`, `coupon-release.lua`)로 선점하고 DB에 영속화한다. 키: `coupon:{couponId}:remaining`, `coupon:{couponId}:issued:{userId}`.
- Redis 선점과 DB 기록 사이 실패 시 `release`로 되돌리는 경로를 유지한다. Redis 선점 로직을 바꾸면 `coupon/infrastructure/redis`의 통합 테스트(Testcontainers)를 Docker 환경에서 돌려 확인한다.

## 내부 API와 보안

- 제공하는 내부 API는 `GET /internal/v1/orders/purchase-status`(`product-service`가 호출)다. `/internal/**` 경로는 `SecurityConfig`와 `GatewayHeaderAuthenticationFilter`에서 게이트웨이 헤더 검사를 제외한다. 게이트웨이 라우트에는 `/internal`이 없다.
- 사용자 식별은 게이트웨이가 넣는 `X-User-Id`, `X-User-Role` 헤더로 한다. 역할 인가는 `SecurityConfig`의 경로별 `hasRole` 규칙으로 한다. 새 API를 추가하면 이 규칙에 경로를 넣는다.
