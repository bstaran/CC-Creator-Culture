# 그룹 C 파이프라인(인프라/배포, 성능)

`/infra-change`와 `/perf-check`가 따르는 절차다. 그룹 C는 기준이 분명하지만 **실행 환경에서만 확인할 수 있고, 실행하면 외부에 영향이 생긴다.** 그래서 AI는 변경 초안, 로컬 검증, 측정까지만 하고, plan 확인과 적용은 사람이 CI에서 한다.
worktree, 상태 파일, 리뷰 횟수, PR 규칙은 [group-a.md](group-a.md)를 따르고, 아래는 다른 부분만 적는다.

## AI가 하는 일과 하지 않는 일

| AI가 한다 | AI가 하지 않는다(hooks로 차단) |
|---|---|
| Terraform, 워크플로우, 스크립트, compose 변경 초안 | `terraform plan/apply/destroy/import/state` |
| `scripts/ai/tf-check.sh`(fmt, init -backend=false, validate, test) | 클라우드 CLI 쓰기 명령(`aws`, `oci`의 조회 외 명령) |
| `.github/scripts/*_test`, actionlint | 이미지 push, 배포 워크플로우 실행(`gh workflow run`) |
| 예상 plan 요약 작성, 사람이 돌린 plan 결과와 대조 | 클라우드 자격 증명 사용 |
| 로컬 스택에서 k6 측정, 기준선 비교 | 공유 환경(dev, prod) 대상 부하 테스트 |

## 인프라/배포(`/infra-change`)

### 기준
- **변경 의도와 예상 plan 요약**: 어떤 리소스가 create/update/replace/destroy 될지(리소스 주소 단위). replace와 destroy는 이유와 대책을 함께 적는다.
- 기준은 PR 본문에 적고, 사람이 CI에서 plan을 돌려 이 요약과 대조한다.

### 검증(오케스트레이터가 직접)
```bash
scripts/ai/tf-check.sh                    # 바뀐 스택(fmt, init -backend=false, validate, test)
python3 .github/scripts/<바뀐 스크립트>_test.py   # 또는 bash ..._test.sh
docker run --rm -v "$PWD":/repo -w /repo rhysd/actionlint:1.7.7 -color   # 워크플로우를 바꾼 경우
```
- terraform도 Docker도 없으면 `tf-check.sh`는 건너뛰고(종료 코드 3), PR에서 CI(`ci-aws.yml`) 결과를 확인한다.

### 리뷰
- `infra-reviewer`(필수). 보안 관련 변경(권한, 네트워크, 비밀 값)은 `/security-review`도 실행한다.
- infra-reviewer가 정리한 "사람이 plan에서 꼭 확인할 항목"을 PR 본문에 옮긴다.

### PR 이후(사람)
1. CI에서 plan 실행(`aws-deploy.yml`의 plan 등) → 결과를 PR 코멘트로 남김
2. AI가 요청받으면 plan 결과와 예상 요약을 대조해 차이를 보고(`/infra-change #번호 plan-check`)
3. 머지 후 적용과 배포는 사람이 environment 승인을 거쳐 실행

## 성능(`/perf-check`)

### 기준
- 대상 시나리오(`load-test/scenarios/...`)와 목표: 기존 대비 악화 없음(회귀 확인) 또는 개선 목표 수치.
- 측정 계획(시나리오, 반복 횟수, 허용 오차)을 먼저 사용자에게 확인받는다.

### 측정(로컬 스택에서만)
```bash
scripts/ai/stack-up.sh                    # 또는 load-test/scripts/up.sh(MASTER 계정 시드 포함)
python3 scripts/ai/perf-compare.py baseline <시나리오>   # 변경 전 코드에서
python3 scripts/ai/perf-compare.py compare  <시나리오>   # 변경 후 코드에서(기본 3회 중앙값, p95 +10%, 실패율 +1%p)
scripts/ai/stack-down.sh
```
- 기준선과 비교는 **같은 PC, 같은 스택 구성**에서 잰다. 기준선은 `.ai-cache/perf/`에 저장되고 커밋하지 않는다.
- 측정 결과 표를 상태 파일과 PR 본문에 그대로 붙인다.
- 개선 작업이라면 원인 분석 근거(쿼리 수, 로그, 지표)를 함께 남긴다. 코드 변경은 그룹 A 절차(기존 테스트 통과, arch-reviewer)를 함께 따른다.

### 리뷰
- 코드 변경이 있으면 `arch-reviewer`, 이벤트/Redis가 걸리면 `event-reviewer`. 측정 방법(시나리오, 반복, 환경)이 공정한지도 리뷰 요청에 포함한다.
