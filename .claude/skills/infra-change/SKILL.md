---
name: infra-change
description: 인프라/배포 변경(Terraform, GitHub Actions, 배포 스크립트, compose, 운영 설정) 1건을 그룹 C 절차로 처리한다. 변경 초안, 예상 plan 요약, 로컬 검증(tf-check, 스크립트 테스트, actionlint), infra-reviewer 리뷰까지 하고 PR을 연다. plan, apply, 배포는 사람이 CI에서 한다. plan 결과가 나오면 "plan-check"로 예상과 대조한다.
argument-hint: "#<이슈번호> [plan-check]"
---

# /infra-change

입력: $ARGUMENTS

`docs/ai-system/playbooks/group-a.md`(공통)와 `docs/ai-system/playbooks/group-c.md`(인프라 추가 절차)를 읽고 따른다. `infra/CLAUDE.md`의 금지 사항을 먼저 확인한다.

## 모드 1: 변경(`/infra-change #번호`)

1. **시작 확인**: 이슈 라벨 `type: infra`. 변경 대상(스택, 워크플로우, 스크립트)과 의도를 상태 파일에 적는다.
2. **현황 조사**: 대상 리소스와 의존 관계를 `explorer`로 조사한다(어떤 모듈, 변수, output, 다른 스택이 참조하는지).
3. **예상 plan 요약(기준)**: 변경 전에 먼저 쓴다.
   | 리소스 주소 | 동작(create/update/replace/destroy) | 이유 |
   |---|---|---|
   replace, destroy가 있으면 데이터 영향과 대책(`moved`, 스냅샷, 단계 배포)을 함께 적는다. 이 표를 상태 파일 "기준"에 넣는다.
4. **구현**: `implementer`에게 의도, 예상 plan 요약, 금지 사항(infra/CLAUDE.md)을 넘긴다.
5. **검증(직접 실행)**: `scripts/ai/tf-check.sh`, 바뀐 `.github/scripts/*`의 `_test`, 워크플로우를 바꿨으면 actionlint. 결과 수치를 상태 파일에 적는다.
6. **리뷰**: `infra-reviewer`에게 의도, 예상 plan 요약, diff, 검증 결과를 넘긴다. 권한, 네트워크, 비밀 값이 걸리면 `/security-review`도 실행한다.
7. **PR**: 본문에 예상 plan 요약, 사람이 plan에서 확인할 항목(infra-reviewer 정리), 적용 순서와 롤백 방법을 넣는다. 라벨 `type: infra`. PR 전에 `/doc-review`로 본문을 다듬는다.
8. 사람에게 CI에서 plan을 돌려 결과를 PR 코멘트로 남겨 달라고 요청한다.

## 모드 2: plan 대조(`/infra-change #번호 plan-check`)

1. PR 코멘트나 사용자가 준 plan 출력을 읽는다(`gh pr view <PR> --repo <origin 저장소> --comments`).
2. 리소스 주소별로 예상 요약과 실제 plan을 대조한다.
   | 리소스 주소 | 예상 | 실제 | 일치 |
3. 예상에 없는 변경, 특히 replace/destroy가 있으면 **불일치**로 보고하고 원인을 조사한다. 적용 여부는 사람이 정한다.

## 하지 않는 것

- `terraform plan/apply/destroy/import/state`, 클라우드 CLI 쓰기, 이미지 push, 배포 워크플로우 실행(hooks가 차단한다).
- `backend.hcl`, `terraform.tfvars`, state 파일 읽기와 수정.
