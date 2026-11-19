# product-service

상품(`product`), 카테고리/해시태그(`category`), 리더보드(`leaderboard`), 위시리스트(`wishlist`), 리뷰(`review`). 루트 `CLAUDE.md` 규칙을 먼저 따른다.

## 테스트

- 실행: `./gradlew :apps:product-service:test` (**Docker 필요**)
- 통합 테스트(`support/AbstractIntegrationTest`)는 Testcontainers로 PostgreSQL(`pgvector`)과 Redis를 띄우고, `ddl-auto: validate`와 Flyway로 실제 스키마를 검증한다. Kafka 테스트는 `@EmbeddedKafka`를 사용한다.
- 엔티티 필드를 바꾸면 Flyway 마이그레이션도 함께 추가해야 `validate`가 통과한다.

## 이벤트와 멱등성

이 서비스는 Kafka 소비자가 가장 많다(`order.paid`, `order.canceled`, `category.created`, `hashtag.created`, `product.created`, 조회수 동기화, 이미지 업로드, 재고 복구, 상품/SKU 삭제).

- 생산자는 재발행할 수 있다(at-least-once). 소비자를 추가하거나 바꿀 때 중복 수신에도 결과가 같아야 한다.
- 리더보드 점수는 `increment_score_if_not_processed.lua`가 `leaderboard:processed:order:{paid|canceled}:{orderId}`(TTL 1일)로 중복을 막는다. 점수 반영을 이 스크립트 밖에서 하지 않는다.
- 카테고리/해시태그 이벤트는 `p_category_outbox_events` outbox를 거친다. `product.created`, `product.deleted`, `sku.deleted`는 커밋 후 `KafkaTemplate`으로 직접 발행한다(현재 구조). 새 이벤트는 outbox 방식으로 만든다.
- 알려진 문제(`docs/architecture.md` "결제에서 리더보드까지"): 카테고리 outbox 릴레이는 `SKIP LOCKED`가 없어 다중 인스턴스에서 중복 발행할 수 있고, `PROCESSING` 상태로 남은 행을 `PENDING`으로 되돌리는 코드가 없다. 또한 `order.paid`가 해시태그 연결보다 먼저 오면 점수가 누락되고, 그 주문이 취소되면 더한 적 없는 점수를 빼게 된다. 이 동작을 바꾸는 작업은 버그 트랙 이슈로 다룬다.

## Redis

- 리더보드: `leaderboard:current:{category|hashtag}` ZSET. 분 단위 스케줄러가 `snapshot_and_clear.lua`로 읽고 비운 뒤 DB에 스냅샷을 저장한다.
- 조회수: `product:view:counts`, `product:viewer:{productId}:{viewerId}`(`view_count.lua`). 조회 경로에서 Redis 오류는 로그만 남기고 삼킨다(상품 조회는 실패하지 않아야 한다).
- Redis는 서비스들이 DB 0을 공유한다. 새 키는 도메인 접두어를 붙인다.

## 인가

- 역할 인가는 `libs/common`의 역할 어노테이션(`@Creator`, `@Customer`, `@Manager`, `@Master`)과 `@PreAuthorize`, `SecurityConfig`를 함께 쓴다. 같은 도메인의 기존 컨트롤러 방식을 따른다.

## 외부 의존

- Feign: `user-service`(`POST /internal/v1/creators/names`), `order-service`(`GET /internal/v1/orders/purchase-status`), `embedding-service`(`POST /embed`). `user-service`와 `order-service` 어댑터(`ProductUserFeignAdapter`, `OrderFeignAdapter`)는 서킷 브레이커 폴백(빈 값)을 써서 조회가 막히지 않게 한다. 조회 경로에 새 호출을 넣으면 같은 방식을 따른다.
- 이 서비스가 제공하는 내부 API: `/internal/v1/stocks`(재고 차감/복구, `order-service`가 호출), `/internal/v1/skus`(`order-service`가 SKU 조회에 호출).
- 이미지는 S3 Presigned URL로 업로드하고 CloudFront 공개 URL로 응답한다. 테스트는 가짜 버킷 설정(`test-bucket`)을 쓴다.

