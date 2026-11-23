---
name: doc-write
description: 사람이 읽는 글(PR 본문, 이슈 본문, docs, README, 작업 기록)을 다른 모델(Antigravity agy, Gemini)이 쓰게 한다. Claude는 사실 초안을 만들고, 결과물의 사실만 대조하며 문장은 고치지 않는다. 쓸 대상(PR 본문, 이슈 본문, 문서 경로)을 받는다.
argument-hint: "<PR 본문 | 이슈 본문 | 문서 경로 ...>"
---

# /doc-write

대상: $ARGUMENTS

사람이 읽는 글의 문장은 Gemini가 쓴다. Claude는 **사실을 정하고 검증하는 쪽**만 맡는다. 실행 결과와 수치는 Claude가 직접 얻은 값이라 Gemini가 다시 알아낼 수 없고, 글을 쓰면서 숫자나 경로를 바꿀 위험이 있기 때문이다.

대상이 아닌 것: AI가 읽는 지침(`CLAUDE.md`, `.claude/`, `docs/ai-system/playbooks/`, `scripts/ai/prompts/`)은 Claude가 직접 쓴다. 사람이 직접 쓴 글을 다듬을 때는 `/doc-review`를 쓴다.

## 1. 사실 초안

스크래치 파일(`.ai-cache/brief/<이름>.md`)에 **다듬지 않은 목록**으로 쓴다. 문장 품질은 신경 쓰지 않는다.

- 무엇이 바뀌었는지, 왜 필요한지
- 근거: 실행한 명령과 결과 수치(출력 그대로), 파일 경로(백틱), 이슈/PR 링크, 커밋 해시
- 독자가 판단에 필요한 한계, 남은 일, 반영하지 않은 리뷰 지적과 이유
- 결과물에 들어갈 숫자, 경로, 링크는 모두 초안에 있어야 한다. 초안에 없는 사실은 스크립트가 거부한다.
- 분량, 강조할 점, 독자 같은 지시는 `작성 메모:`로 시작하는 줄에 쓴다(본문에 옮겨지지 않는다).
- 기존 문서를 고칠 때는 어느 절을 어떻게 바꿀지와 새 사실만 적는다.

## 2. 실행

```bash
# PR 본문
python3 scripts/ai/doc-write.py --brief .ai-cache/brief/pr.md --template .github/pull_request_template.md --out .ai-cache/pr/<브랜치>.md
# 이슈 본문(스펙은 .github/ISSUE_TEMPLATE/spec.md, 작업 요청은 ai-request.md를 양식으로)
python3 scripts/ai/doc-write.py --brief .ai-cache/brief/issue.md --template .github/ISSUE_TEMPLATE/spec.md --out .ai-cache/issue/<이름>.md
# 기존 문서 고치기(결과를 그 문서에 바로 쓴다)
python3 scripts/ai/doc-write.py --brief .ai-cache/brief/guide.md --target docs/ai-system/guide.md
# 새 문서: 문체와 용어를 맞출 문서를 참고로 넘긴다
python3 scripts/ai/doc-write.py --brief .ai-cache/brief/x.md --out docs/x.md --context docs/ai-system/README.md
```

- 문서 하나에 호출 1회(사실 검사에 걸리면 자동으로 1회 더)다. 호출마다 고정 비용(입력 약 1.1만 토큰, 약 10초)이 들고 한 번에 1분에서 몇 분이 걸리므로 Bash 타임아웃은 600초로 준다. 문서가 여러 개면 백그라운드로 동시에 실행한다.
- 기본 모델은 `gemini-4-neon-medium`이다(`--model`로 바꾼다).
- `CLAUDE.md`의 "문서 작성" 절은 스크립트가 그대로 프롬프트에 넣는다. 규칙을 초안에 다시 적지 않는다.

## 3. 결과 처리

| 종료 코드 | 상태 | 할 일 |
|---|---|---|
| 0 | `ok` | 결과물을 사실 기준으로 대조한다(아래). `missing_facts`에 중요한 사실이 있으면 `작성 메모:`로 지시를 더해 다시 실행한다 |
| 4 | `rejected` | `issues`를 본다. 결과물이 쓴 사실이 맞다면 근거와 함께 초안에 넣고, 아니면 초안을 분명하게 고쳐 다시 실행한다. 같은 이유로 두 번 실패하면 멈추고 보고한다 |
| 3 | `skipped`, `error` | `agy`가 없거나(CI 등) 호출이 실패했다. Claude가 `CLAUDE.md` 규칙대로 직접 쓰고 `--mark-skipped <파일>`로 기록한 뒤, PR 참고사항에 그 사실을 적는다 |

결과물 대조:
- 내용이 초안과 같은지만 본다. **문장은 고치지 않는다.** 표현이 마음에 들지 않으면 `작성 메모:`를 더해 다시 실행한다.
- `--target`으로 기존 문서를 고쳤으면 `git diff`로 초안이 말한 부분 밖이 바뀌지 않았는지 본다. 바뀌었으면 그 부분을 원문으로 되돌린다.
- 사실 하나가 틀린 경우에만 그 값을 직접 고치고 `python3 scripts/ai/doc-review.py --mark <파일>`로 다시 기록한다.

## 4. 기록

- 사실 검사를 통과한 글은 스크립트가 "written"으로 기록한다(`.git/ai-doc-review.json`, 커밋되지 않음). `gh pr create` 때 hook이 이 기록을 확인하므로, PR 본문은 `--body-file`로 결과 파일을 그대로 넘긴다.
- 기록한 뒤 내용을 바꾸면 기록이 무효가 된다. 다시 실행하거나, 사실만 고쳤다면 `--mark`로 다시 기록한다.

## 5. 보고

```
## 문서 작성(<모델>)
| 대상 | 호출 | 소요 | 결과 | 빠진 사실 |
|---|---:|---:|---|---|

다시 실행한 이유: ...
```

작업 상태 파일이 있으면 진행 로그에 한 줄로 남긴다(대상, 모델, 호출 수, 결과).
