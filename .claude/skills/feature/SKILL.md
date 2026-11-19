---
name: feature
description: 승인된 스펙(spec: approved 라벨) 1건을 그룹 B 파이프라인으로 구현한다. 완료 조건마다 요구사항 테스트를 먼저 고정하고, worktree에서 구현, 검증(스키마 스냅샷, 라우트, 스모크), 리뷰(arch, schema)를 거쳐 PR을 연다. 머지는 사람이 한다.
argument-hint: "#<이슈번호>"
---

# /feature

이슈: $ARGUMENTS

`docs/ai-system/playbooks/group-a.md`(공통 절차)와 `docs/ai-system/playbooks/group-b.md`(기능 개발 추가 절차)를 읽고 따른다.

## 시작 전 확인

- 이슈에 `type: feature`와 **`spec: approved`** 라벨이 모두 있어야 한다. 없으면 멈추고 `/spec`이나 담당자 승인을 요청한다.
  ```bash
  gh issue view <번호> --repo <origin 저장소> --json labels,body,comments
  ```
- 승인 이후 스펙을 바꾸는 코멘트가 있으면 재승인 여부를 확인한다.
- 스펙의 완료 조건(AC 목록), API/이벤트/DB 변경 표를 상태 파일 "기준"에 옮겨 적는다.

## 기준 고정

1. `test-writer`에게 **요구사항 테스트**를 맡긴다. 넘길 것: worktree 경로, AC 목록, API/이벤트/DB 표, 테스트 위치 관례.
   - AC마다 테스트 1개 이상, `@DisplayName`에 AC 번호.
   - 새 API: 컨트롤러 테스트(요청 검증, 응답 형식, 권한). 새 동작: 서비스 테스트. 서비스 간 흐름: 통합 테스트.
2. 이벤트 변경이 있으면 `EventSchemaSnapshotTest.samples()`와 스냅샷을 스펙대로 먼저 갱신한다(`SCHEMA_SNAPSHOT_UPDATE=true`).
3. 새 외부 경로가 있으면 `GatewayRouteConfigTest`에 케이스를 추가한다.
4. 오케스트레이터가 직접 실행해 상태(실패 또는 컴파일 오류)를 확인하고 기록한 뒤 `test(<scope>): #<번호> 요구사항 테스트`로 커밋한다.

## 구현, 검증, 리뷰

- 구현은 서비스별로 나눠 `implementer`에게 맡긴다(생산자 → 소비자 순서).
- 검증은 group-b.md 4장(스냅샷, 라우트, 필요 시 스택 스모크)까지 오케스트레이터가 직접 실행한다.
- 리뷰는 `arch-reviewer`와 `schema-reviewer`를 병렬로 실행하고, 이벤트/outbox/Lua/`/internal`이 관련되면 `event-reviewer`도 함께 실행한다. 스펙(이슈 본문)을 함께 넘긴다.

## PR

- 제목 `feat(<scope>): <요약>`. 본문에 AC 대응표, 배포 순서(마이그레이션, 이벤트 생산자/소비자), 반영하지 않은 권고를 적는다.
- PR을 열기 전에 `/doc-review`로 PR 본문과 바뀐 문서를 다듬는다.
- 머지하지 않는다. PR 링크를 보고하고 상태 파일을 갱신한다.
