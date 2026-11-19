---
name: perf-check
description: 성능 회귀 확인이나 성능 개선 1건을 그룹 C 절차로 처리한다. 측정 계획을 확인받은 뒤 로컬 스택에서 k6 시나리오를 여러 번 실행해 기준선과 비교(중앙값, p95 허용 오차)하고 결과를 보고한다. 공유 환경(dev, prod)에는 부하를 주지 않는다.
argument-hint: "#<이슈번호> | <시나리오 경로> [--runs 3] [--tolerance 10]"
---

# /perf-check

입력: $ARGUMENTS

`docs/ai-system/playbooks/group-c.md`의 "성능" 절을 따른다.

## 1. 측정 계획(먼저 확인받는다)

다음을 정리해 사용자에게 확인받는다. **확인 전에 측정을 시작하지 않는다.**
- 목적: 회귀 확인(변경 전후 비교) / 개선(목표 수치)
- 시나리오: `load-test/scenarios/...`(없으면 기존 시나리오를 참고해 새로 만드는 것도 계획에 포함)
- 반복 횟수(기본 3), 허용 오차(기본 p95 +10%, 실패율 +1%p)
- 환경: 로컬 스택(`scripts/ai/stack-up.sh` 또는 MASTER 계정 시드가 필요하면 `load-test/scripts/up.sh`)
- 비교 대상: 기준선 커밋(보통 `origin/dev`)과 변경 커밋

## 2. 기준선

- 기준선 커밋의 코드로 스택을 띄운다(worktree를 쓰면 그 worktree에서 `stack-up.sh`).
- `python3 scripts/ai/perf-compare.py baseline <시나리오> --runs <N>`
- 같은 기준선이 이미 있으면(`perf-compare.py show`) 커밋과 측정 시각을 확인하고 재사용 여부를 정한다.

## 3. 변경과 비교

- 성능 개선 작업이면 변경은 그룹 A 절차(기존 테스트 통과, 범위 최소, arch-reviewer)를 함께 따른다.
- 변경 후 코드로 스택을 다시 띄우고(`stack-up.sh`, 이미지 재빌드) 비교한다.
  ```bash
  python3 scripts/ai/perf-compare.py compare <시나리오> --runs <N> --tolerance <T>
  ```
- 측정이 끝나면 `scripts/ai/stack-down.sh`.

## 4. 보고

- `perf-compare.py`가 출력한 표(중앙값, 개별 실행 p95)를 그대로 붙인다.
- 개별 실행 값의 편차가 크면(예: 최대/최소가 20% 이상 차이) 판정을 신뢰하기 어렵다고 적고 반복 횟수를 늘려 다시 잰다.
- 개선 작업이면 원인 근거(쿼리 수, 로그, Grafana 지표)를 함께 적는다.
- 상태 파일과 PR 본문(라벨 `type: perf`)에 결과를 남긴다.

## 하지 않는 것

- dev, prod 등 공유 환경 대상 부하 테스트(`run-dev.sh`, `run-aws.sh`). 필요하면 사람에게 요청한다.
- 측정 환경이 다른 기준선과 결과를 비교해 결론 내리기.
