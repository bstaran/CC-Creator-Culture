# CLAUDE.md

크리에이터 커머스 MSA(`cc-service`). Java 21, Spring Boot 4.1.1, Spring Cloud 2025.1.2, Gradle 멀티모듈 프로젝트다.
전체 구조와 요청 흐름은 `docs/architecture.md`, AI 작업 체계는 `docs/ai-system/plan.md`를 참고한다.

## 모듈

| 모듈 | 역할 |
|---|---|
| `apps/user-service` | 인증(JWT), 사용자, 크리에이터 승인, 팔로우, 알림 |
| `apps/product-service` | 상품, 카테고리/해시태그, 리더보드(Redis ZSET), 위시리스트, 리뷰 |
| `apps/order-service` | 장바구니, 주문, 결제, 쿠폰(Redis Lua) |
| `apps/embedding-service` | Python 임베딩 서비스(Gradle 모듈 아님) |
| `libs/common` | 공통 응답, 예외, Kafka 이벤트, 보안 어노테이션, 식별자 |
| `infra/gateway`, `infra/eureka-server`, `infra/config-server` | 게이트웨이(JWT 필터), 서비스 탐색, 중앙 설정 |
| `infra/terraform` | AWS(ECS 등) 및 OCI 인프라 코드 |
| `config-repo/` | 서비스별, 프로필별 설정(`<서비스>-<local\|dev\|prod>.yaml`) |
| `load-test/` | k6 부하 테스트 |

## 명령

`java`가 PATH에 없으면 `JAVA_HOME`을 JDK 21로 지정한 뒤 실행한다.

```bash
./gradlew :apps:order-service:test                                            # 모듈 테스트
./gradlew :apps:order-service:test --tests '*OrderCancellationServiceTest'    # 단일 테스트
./gradlew :apps:order-service:build                                           # CI와 같은 검증(컴파일 + 테스트)
./gradlew build                                                               # 전체 빌드 및 테스트
./gradlew :apps:order-service:spotlessCheck                                   # 포맷 검사(origin/dev 대비 바뀐 파일만)
./gradlew :apps:order-service:spotlessApply                                   # 포맷 자동 수정
scripts/ai/stack-up.sh && scripts/ai/smoke-gateway.sh; scripts/ai/stack-down.sh   # 로컬 전체 스택 기동, 게이트웨이 스모크, 종료(Docker, .env 필요)
```

- 포맷은 기본 규칙(미사용 import 제거, 줄 끝 공백 제거, 파일 끝 개행)만 검사한다. 들여쓰기와 import 순서는 강제하지 않으므로, 파일을 고칠 때 그 파일의 기존 스타일을 따른다. `build`에는 포함되지 않고 모듈 CI가 따로 실행한다.
- 모듈 경로는 `:apps:<서비스>`, `:infra:<모듈>`, `:libs:common`이다. 변경한 모듈을 검증하고, `libs/common`을 수정했다면 이에 의존하는 서비스도 모두 검증한다.
- 테스트 로그가 길다(`show-sql`). 실행 결과는 종료 코드와 `<모듈>/build/reports/tests/test/index.html`로 확인한다.
- 테스트 프로필과 DB 구성은 서비스마다 다르다(서비스별 `CLAUDE.md` 참고). Docker가 없으면 `product-service` 통합 테스트는 실패하고, `disabledWithoutDocker = true`가 붙은 테스트는 실패가 아니라 건너뛴다. 통합 테스트 통과를 근거로 삼을 때는 건너뛰지 않았는지 `build/test-results`에서 확인한다.
- 로컬 전체 스택은 README의 `docker compose ... up` 명령으로 실행한다. 도메인 서비스(`user-service`, `product-service`, `order-service`)는 직접 포트를 노출하지 않으며 게이트웨이(`127.0.0.1:8080`)를 통해서만 접근한다.

## 코드 구조 규칙

서비스 코드는 `com.sub9.<서비스>.<도메인>.{domain,application,infrastructure,presentation}` 구조다.

- `domain`: 모델, 도메인 예외. JPA 어노테이션은 현재 허용한다(엔티티가 도메인 모델을 겸함). `application`, `infrastructure`, `presentation`을 import하지 않는다.
- `application`: `service`, `dto`, 포트. 외부 의존은 아웃바운드 포트 인터페이스로 두고 `infrastructure`가 구현한다. 포트 패키지 이름은 도메인마다 다르다(대부분 `port/in`, `port/out`이며, `order`와 `auth`는 `port/input`, `port/output`). 새 코드는 해당 도메인의 기존 이름을 따른다.
- `infrastructure`: 영속성(JPA, QueryDSL), 외부 클라이언트(Feign), Kafka, outbox, 스케줄링.
- `presentation`: 컨트롤러, 요청/응답 DTO.

알려진 위반: `application`이 `presentation` DTO(일부는 `infrastructure`)에 의존하는 클래스가 34개 있다. **새 위반을 만들지 않는다.** 기존 위반은 리팩토링 이슈로만 고친다.

- 각 서비스의 `architecture/LayerArchitectureTest`(ArchUnit)가 위 규칙을 검사한다. 기존 위반은 `src/test/resources/archunit_store`에 동결되어 있어 통과하고, 새 위반은 테스트 실패로 드러난다.
- 동결 저장소에 위반을 직접 추가하거나 `allowStoreCreation`을 켜서 실패를 덮지 않는다. 기존 위반을 고치면 저장소에서 자동으로 빠지므로 그 변경은 함께 커밋한다.
- 커버리지: 테스트 후 `<모듈>/build/reports/jacoco/test/`에 리포트가 생긴다. 요약은 `python3 scripts/ai/coverage-summary.py`.

## 테스트 작성

- 테스트 메서드 이름은 영어 camelCase로 쓰고, 한국어 설명은 `@DisplayName("한국어 문장")`으로 붙인다(예: `void cancelOrderRestoresCoupon()` + `@DisplayName("주문을 취소하면 쿠폰이 복구된다")`). 클래스와 `@Nested` 그룹도 같은 방식이다.
- 기존 테스트의 한국어 메서드 이름은 그대로 두고, 새로 쓰거나 고치는 테스트부터 이 규칙을 따른다.
- ArchUnit `@ArchTest`는 필드 대신 메서드로 쓴다(`@DisplayName`은 필드에 붙일 수 없다). ArchUnit 엔진은 리포트에 `@DisplayName`을 표시하지 않고 메서드 이름을 쓴다.

## 변경 시 주의

- **DB 스키마**: Flyway 마이그레이션 경로는 `apps/<서비스>/src/main/resources/db/migration/V<n>__<설명>.sql`이다. 이미 있는 마이그레이션 파일은 수정하지 않고 새 버전을 추가한다.
- **Kafka 이벤트**: 이벤트 클래스는 `libs/common`의 `kafka` 패키지에 있고 여러 서비스가 소비한다. 필드 변경 시 하위 호환을 유지하고, 생산자와 소비자를 함께 확인한다. 주문, 결제, 카테고리/해시태그 이벤트는 outbox를 거쳐 발행한다(직접 `KafkaTemplate` 발행을 추가하지 않는다). 이벤트 구조는 `EventSchemaSnapshotTest`가 스냅샷(`libs/common/src/test/resources/schema/events/`)으로 고정한다. 구조를 바꾸면 이 테스트가 실패하며, 의도한 변경일 때만 `SCHEMA_SNAPSHOT_UPDATE=true`로 스냅샷을 갱신해 함께 커밋한다.
- **게이트웨이 라우트**: `config-repo/gateway-local.yaml`, `gateway-dev.yaml`, `gateway-prod.yaml` 세 파일을 함께 수정한다. 새 API를 추가하면 라우트가 누락되지 않았는지 확인한다.
- **서비스 간 동기 호출**: OpenFeign을 사용한다. 내부 API 경로와 인증 헤더 처리 규칙은 기존 클라이언트를 확인해 따른다.

## 작업 방식

- 작업은 트랙으로 분류해서 진행한다. 기준은 `docs/ai-system/plan.md` 3장이다.
  - **A(성공 기준이 레포 안에 있음)**: 리팩토링, 버그 수정. 리팩토링은 동작을 바꾸지 않으며 기존 테스트가 기준이다. 테스트가 부족하면 특성 테스트를 먼저 작성한다. 버그 수정은 실패하는 재현 테스트를 먼저 작성한다.
  - **B(기준을 만들어야 함)**: 기능 개발, 조사/문서. 기능 개발은 승인된 스펙과 요구사항 테스트 없이 구현을 시작하지 않는다.
  - **C(실행 환경에서 확인)**: 인프라/배포, 성능. plan 생성과 측정까지만 수행한다.
- 진행 상태(확인한 내용과 남은 작업)는 `docs/ai-system/tasks/<이슈번호>.md`에 기록한다.
- 같은 방법으로 2회 실패하면 멈추고 상황을 보고한다.

## Git

- 브랜치: `feature/`, `fix/`, `refactor/`, `chore/`, `docs/` 접두사. PR 대상은 `dev`다.
- 커밋: `type(scope): 한국어 요약` 형식이다(예: `fix(order): 내부 API 인증 헤더 검사 제외`). scope는 모듈이나 도메인(`order`, `product`, `user`, `common`, `infra`, `ci`, `config`)을 쓴다.
- PR 본문은 `.github/pull_request_template.md` 양식을 채운다. 테스트 항목에는 실제 실행한 명령과 결과를 적는다.

## 금지

- `.env`와 비밀 값 읽기, 출력, 커밋(예시는 `.env.example`만 참고)
- `terraform apply`/`destroy`, 배포 워크플로우(`deploy-dev`, `aws-deploy`) 실행, AWS 리소스 변경
- `origin` 외 원격에 push, 다른 레포에 PR 생성, `dev`/`main`에 직접 push
- 테스트 통과를 위한 테스트 삭제 또는 `@Disabled` 처리, 검증 단계 건너뛰기(`-x test` 등)

## 자동 검사(hooks)

`.claude/settings.json`의 hooks가 위 규칙 일부를 강제한다(스크립트: `.claude/hooks/`, python3 필요).

- `guard_bash.py`: terraform plan/apply/destroy/state 등, 워크플로우 수동 실행, `origin` 외 push, `dev`/`main` push, force push, `.env` 접근, `-x test`를 차단한다.
- `guard_files.py`: 비밀 값 파일(`.env`, `*.tfvars`, `backend.hcl`, `*.tfstate`) 읽기와 수정, 기존 Flyway 마이그레이션 수정을 차단한다.
- `verify_compile.py`(Stop): 커밋되지 않은 Java/Gradle 변경이 있으면 해당 모듈의 포맷 검사(`spotlessCheck`)와 컴파일을 실행하고, 실패하면 작업을 끝내지 못하게 한다. 같은 내용은 다시 돌리지 않는다. `CC_SKIP_VERIFY=1`로 끌 수 있다.

차단되면 우회하지 말고 사유를 사용자에게 보고한다.
