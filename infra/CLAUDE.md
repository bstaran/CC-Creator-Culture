# infra

게이트웨이, 유레카, 컨피그 서버, Terraform. 루트 `CLAUDE.md` 규칙을 먼저 따른다. 이 디렉터리 작업은 대부분 C 트랙(실행 환경에서 확인)이다. **AI는 plan과 검증까지만 하고, 적용과 배포는 사람이 CI에서 한다.**

## gateway

- Spring Cloud Gateway(WebFlux) 기반이며, MVC 기반인 `libs/common`에 의존하지 않는다. 공통 코드를 끌어오지 말고 필요한 값은 게이트웨이 안에 둔다.
- `GatewayAuthenticationFilter` 순서: 클라이언트가 보낸 `X-User-Id`, `X-User-Role`, `X-Token-Id`, `X-Token-Expires-At` 제거 → Bearer 액세스 토큰 검사(HS256, `type: ACCESS`) → Redis `auth:blacklist:access:{jti}` 확인(있으면 401, Redis 실패 시 503) → 네 헤더 기록. 헤더 제거 단계를 빼거나 순서를 바꾸면 헤더 위조가 가능해진다.
- 블랙리스트 키 접두어와 JWT 형식은 `user-service`와 같아야 한다. 한쪽만 바꾸지 않는다.
- 라우트는 코드가 아니라 `config-repo/gateway-{local,dev,prod}.yaml`에 있다. 세 파일을 함께 바꾸고, `/internal/**`는 라우트에 넣지 않는다. 알려진 차이: `/api/v1/images`(local은 `user-service`, dev와 prod는 `product-service`), `PATCH /api/v1/admin/products/{productId}/status` 라우트 누락.
- 테스트: `./gradlew :infra:gateway:test`. 인증 필터, 헤더 정리, 공개 경로 매처 단위 테스트가 있다. 인증 로직을 바꾸면 해당 테스트를 함께 고친다.

## config-server, eureka-server

- 설정 값은 `config-repo/`에 있고, 이미지 빌드 시 복사된다(`docker/Dockerfile.local`). 설정을 바꾼 뒤 로컬 스택에 반영하려면 이미지를 다시 빌드해야 한다.
- 비밀 값은 설정 파일에 넣지 않고 환경 변수 자리표시자(`${...}`)로 둔다.

## terraform

| 디렉터리 | 대상 | 비고 |
|---|---|---|
| `terraform/aws/{bootstrap,persistent,runtime}` | AWS 서울 리전(ECS, RDS, ECR, OIDC 역할) | `aws-deploy.yml`이 plan/deploy/start/stop/destroy-runtime 수행(자세한 내용은 `terraform/aws/README.md` 참고) |
| `terraform/{bootstrap,dev,shared}` | OCI 개발 환경, Cloudflare | `deploy-dev.yml`(OCI)와 연결 |

- 로컬에서 할 수 있는 검증은 CI(`ci-aws.yml`)와 같다: `terraform fmt -check -recursive`, `terraform init -backend=false`, `terraform validate`, runtime 스택은 `terraform test`. 실행 버전은 Terraform 1.12.2 기준이다.
- `terraform plan`(원격 state 필요), `apply`, `destroy`, `import`, `state` 명령은 실행하지 않는다. plan이 필요하면 PR에 변경 의도를 적고 사람이 CI에서 실행한다.
- `backend.hcl`, `terraform.tfvars`, state 파일은 커밋하지 않는다. `*.example`만 고친다.
- 기존 리소스가 교체(replace)되거나 삭제되는 변경(이름이나 식별자 변경, `for_each` 키 변경 등)은 PR 설명에 명시하고 `moved` 블록을 검토한다. `shared/main.tf`의 예약 공인 IP처럼 주석으로 "교체 금지"가 적힌 리소스는 건드리지 않는다.
- IAM/OIDC 신뢰 정책은 권한을 넓히는 변경을 하지 않는다. 필요하면 이슈로 사람의 판단을 받는다.

## 배포 스크립트

- `.github/scripts/`의 스크립트는 대부분 같은 이름의 `_test` 파일이 있다. 스크립트를 바꾸면 테스트를 함께 고치고 실행한다(예: `python3 .github/scripts/aws-power_test.py`, `bash .github/scripts/service-revisions_test.sh`).
- 배포 워크플로우(`deploy-dev.yml`, `aws-deploy.yml`)는 실행하지 않는다. 워크플로우 파일 수정은 PR로만 한다.
