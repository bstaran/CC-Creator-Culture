# 그룹 A 파이프라인(리팩토링, 버그 수정)

`/refactor-task`와 `/bugfix`가 공통으로 따르는 절차다. 두 스킬은 **기준을 고정하는 단계(3단계)**만 다르다.
오케스트레이터는 이 절차를 실행하는 메인 세션이다. 구현과 테스트 작성은 서브에이전트에 맡기고, 오케스트레이터는 판단, 커밋, 상태 기록을 맡는다.

## 0. 시작 조건

- 이슈가 있어야 한다(`type: refactor` 또는 `type: bug`). 없으면 `/triage`로 먼저 분류하고 이슈를 등록한다.
- 작업은 사람이 시작한다(스킬 호출 = 시작 승인). 머지는 항상 사람이 한다.
- GitHub 명령에는 항상 `--repo <origin 저장소>`를 붙인다.

## 1. 상태 파일

- `docs/ai-system/tasks/<이슈번호>.md`가 있으면 읽고 이어서 진행한다. 없으면 `_template.md`를 복사해 만든다.
- 단계가 끝날 때마다 진행 로그, 결정 사항, 남은 일을 갱신한다.

## 2. worktree 준비

```bash
git fetch origin
git worktree add --no-track .claude/worktrees/<이슈번호> -b <refactor|fix>/<이슈번호>-<짧은-요약> origin/dev
```

- 이후 모든 쓰기 작업은 이 worktree 안에서 한다. 서브에이전트에게는 worktree의 절대 경로를 넘긴다.
- 상태 파일도 worktree 안의 `docs/ai-system/tasks/<이슈번호>.md`에 쓰고 같은 브랜치에 커밋한다.

## 3. 기준 고정(트랙별)

| 트랙 | 기준 | 확인 |
|---|---|---|
| 리팩토링 | 변경 대상 동작을 덮는 테스트. 기존 테스트로 부족하면 `test-writer`가 특성 테스트를 쓴다(`/characterize` 절차) | 현재 코드에서 **통과** |
| 버그 수정 | `test-writer`가 쓰는 재현 테스트 | 현재 코드에서 **버그 때문에 실패**(실패 메시지를 상태 파일에 기록) |

기준이 고정되면 테스트만 먼저 커밋한다: `test(<scope>): <이슈번호> 특성 테스트` 또는 `test(<scope>): <이슈번호> 재현 테스트`.
이 커밋 이후 기준 테스트 파일은 바꾸지 않는다. 바꿔야 한다면 멈추고 사람에게 이유를 보고한다.

## 4. 구현

`implementer`에게 다음을 넘긴다: worktree 경로, 이슈 요약, 기준 테스트 이름, 대상 모듈, 범위 밖으로 하지 말아야 할 것.

## 5. 검증(오케스트레이터가 직접 실행)

서브에이전트의 보고는 참고 자료다. 통과 여부와 수치는 **오케스트레이터가 직접 실행한 결과**로만 판단하고 상태 파일에 적는다. 보고가 비었거나 근거(수치, 파일)가 없으면 그 사실을 상태 파일 "시스템 검증에서 발견한 점"에 남긴다. 기준 테스트를 커밋하기 전에는 오케스트레이터가 같은 방식으로 직접 실행해 기대한 실패/통과를 확인한다.

```bash
./gradlew :<모듈>:build             # 컴파일, 전체 테스트, ArchUnit
./gradlew :<모듈>:spotlessCheck
```

- `libs/common`을 바꿨다면 의존하는 서비스 모두.
- 리팩토링: 기준 테스트와 기존 테스트가 모두 통과해야 한다. 테스트 수와 건너뜀 수가 줄지 않았는지 확인한다.
- 버그 수정: 3단계에서 실패하던 재현 테스트가 통과하고, 기존 테스트가 모두 통과해야 한다.
- ArchUnit 동결 저장소(`archunit_store`)가 바뀌었다면 위반이 **줄어든** 경우만 허용하고 함께 커밋한다.
- 실패하면 `implementer`에게 실패 내용을 넘겨 다시 맡긴다. 같은 원인으로 2회 실패하면 한 단계 강한 모델로 넘기고(`implementer`를 `model: opus`로 호출), 그래도 실패하면 멈추고 보고한다.

## 6. 리뷰

- 항상 `arch-reviewer`. Kafka 이벤트, outbox, 이벤트 소비자, Redis Lua, `/internal` API가 diff에 걸리면 `event-reviewer`도 함께(병렬).
- 리뷰어에게 넘기는 것: 트랙과 기준(이슈 번호, 기준 테스트 이름), `git diff origin/dev...HEAD` 전체, worktree 경로.
- "차단" 지적이 있으면 4단계로 돌아간다. **수정 요청은 최대 2회**. 3회째에도 차단이 남으면 멈추고 사람에게 보고한다.
- "권고"는 반영 여부를 오케스트레이터가 판단하고, 반영하지 않은 권고는 PR 본문 참고사항에 적는다.

## 7. PR

PR을 만들기 전에 이번 브랜치에서 AI가 쓰거나 고친 문서(`*.md`, 상태 파일 포함)와 PR 본문 파일에 `/doc-review`를 실행해 문장을 다듬는다. `agy`를 쓸 수 없으면 건너뛰고 PR 참고사항에 적는다.

```bash
git push -u origin <브랜치>
gh pr create --repo <origin 저장소> --base dev --title "<type>(<scope>): <요약>" --body-file <본문 파일> --label "<이슈의 트랙 라벨>"
```

- 라벨: 연결된 이슈의 트랙 라벨(`type: bug`, `type: refactor`, `type: feature`, `type: infra`, `type: perf`)을 그대로 붙인다. AI 작업 체계 자체를 바꾸는 PR은 `area: ai-system`.
- 본문은 `.github/pull_request_template.md` 양식. "테스트 결과"에 실제 실행한 명령과 결과(통과 수, 건너뜀 수), 버그 수정이면 수정 전 실패 메시지를 적는다. "관련 이슈"에 `Closes #<번호>`.
- 리뷰 회차별 결과(판정, 차단 지적과 조치)를 참고사항에 요약한다.
- 머지는 하지 않는다. PR 링크를 보고하고 상태 파일을 "PR 열림"으로 갱신한다.

## 8. 정리

- PR 상태를 먼저 확인하고(`gh pr view <번호> --repo <origin 저장소> --json state`), `MERGED`나 `CLOSED`일 때만 `git worktree remove .claude/worktrees/<이슈번호>`. 사람의 "머지했다"는 말만으로 정리하지 않는다.
- 리뷰에서 반복된 지적은 `docs/ai-system/metrics.md`의 피드백 기록에 남기고, 2회 이상 반복되면 `CLAUDE.md`나 에이전트 지침 보강을 제안한다.
