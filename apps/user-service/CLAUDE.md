# user-service

인증(`auth`), 사용자(`user`), 크리에이터 가입/승인(`creator`), 팔로우(`follow`), 알림(`notification`). 루트 `CLAUDE.md` 규칙을 먼저 따른다.

## 테스트

- 실행: `./gradlew :apps:user-service:test`
- `LoginIntegrationTest`, `SignupIntegrationTest`, `TokenReissueIntegrationTest` 등 통합 테스트는 `@Testcontainers(disabledWithoutDocker = true)`를 사용하므로 Docker가 없으면 건너뛴다. 인증이나 영속성 흐름을 수정했다면 Docker 환경에서 실제로 실행됐는지 확인한다.

## 인증과 토큰

- 액세스 토큰 검사는 게이트웨이가, 역할 인가는 이 서비스가 맡는다. 게이트웨이와 이 서비스는 같은 JWT 비밀 키(HS256)와 클레임(`type: ACCESS`)을 전제로 한다. 토큰 형식(`JwtTokenProvider`)을 바꾸면 `infra/gateway`도 함께 수정해야 한다.
- Redis 키: `auth:refresh:{userId}`, `auth:blacklist:access:{tokenId}`(`AuthenticationTokenRedisKey`). 블랙리스트 접두어는 게이트웨이에도 별도 문자열로 정의되어 있으므로 변경 시 두 곳을 함께 수정한다.
- 로그아웃은 `logout.lua`가 리프레시 토큰 삭제와 블랙리스트 기록을 원자적으로 처리한다.
- 비밀번호, 토큰, 비밀 키를 로그나 응답에 남기지 않는다.

## 인가

- `SecurityConfig`의 경로별 규칙(`hasRole("CREATOR")`, `hasRole("MASTER")` 등)으로 인가한다. 새 API를 추가하면 이 규칙에 경로를 넣고, 공개 경로(`PUBLIC_AUTH_PATHS`)를 임의로 넓히지 않는다.
- `/internal/**` 경로는 게이트웨이 헤더 검사에서 제외된다. 제공하는 내부 API는 `POST /internal/v1/creators/names`(`product-service`와 `order-service`가 크리에이터 이름 조회에 사용)다.

## 이벤트와 알림

- `KafkaNotificationEventConsumer`가 `order.notification`을 소비해 알림을 만든다. 생산자(`order-service` outbox)가 재발행할 수 있어서 `NotificationEventCoordinator`가 `eventId`로 중복을 거른다. 소비 경로를 바꿀 때 이 검사를 유지한다.
- Slack 발송은 `SlackDeliveryWorker`(스케줄러)가 `SlackWebhookClient`로 처리한다. 테스트에서 실제 웹훅을 호출하지 않는다.
- `user.deleted`는 커밋 후 `KafkaTemplate`으로 발행하지만 현재 구독자가 없다.
- `notification` 컨트롤러는 `notification/infrastructure/presentation`에 있다(다른 도메인과 다른 위치). 옮기려면 별도 리팩토링 이슈로 분리한다.
