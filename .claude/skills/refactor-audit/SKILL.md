---
name: refactor-audit
description: 서비스별 리팩토링, 버그 후보를 팬아웃 방식으로 진단하고 중복을 정리해 이슈 후보 목록을 만든다. 승인을 받은 항목만 이슈로 등록한다. 서비스 이름을 주면 그 서비스만, 비우면 전체를 진단한다.
argument-hint: "[user-service|product-service|order-service|common|gateway]"
---

# /refactor-audit

범위: $ARGUMENTS (비어 있으면 전체)

코드는 고치지 않는다. 결과물은 **근거가 붙은 이슈 후보 목록**이다.

## 1. 입력 자료 모으기(오케스트레이터)

- 열린 이슈: `gh issue list --repo <origin 저장소> --state open --label "type: refactor" --limit 100` (`type: bug`도 같이)
- 기준선: `docs/ai-system/metrics.md`(커버리지 낮은 영역, 건너뛴 테스트, 동결된 계층 위반)
- 동결 위반 목록: `apps/<서비스>/src/test/resources/archunit_store/`
- 알려진 문제: 각 서비스 `CLAUDE.md`, `docs/architecture.md`

## 2. 팬아웃 진단(병렬)

서비스마다 `explorer`를 하나씩 띄운다(범위가 한 서비스면 그 하나만). 각 explorer에게 같은 점검표를 준다.

- 큰 클래스와 메서드: 200줄 이상 클래스, 50줄 이상 메서드, 의존성이 7개 이상인 서비스 클래스
- 중복: 같은 도메인 안에서 비슷한 조회, 검증, 변환 로직이 반복되는 곳
- 계층 위반: 동결 목록 중 같은 원인(예: application이 presentation 응답 DTO를 직접 만든다)으로 묶을 수 있는 묶음
- 트랜잭션 경계: `@Transactional` 안의 Feign 호출, 이벤트 직접 발행
- 예외 처리: 삼키는 예외, 일관되지 않은 에러 코드
- 테스트 공백: 커버리지가 낮은데 변경이 잦을 만한 영역(`git log --since=3.months --name-only`로 변경 빈도 확인은 오케스트레이터가 한다)

서비스 간 인터페이스(Kafka 이벤트, outbox, `/internal` API, Redis 키)는 `event-reviewer`에게 "현재 코드 전체에 대한 진단"으로 따로 맡긴다(diff 대신 대상 범위를 준다).

## 3. 통합과 정리(오케스트레이터)

- 같은 원인은 하나로 합치고, 열린 이슈와 겹치는 항목은 빼거나 "기존 이슈 #N에 추가"로 표시한다.
- 동작이 바뀌어야 하는 항목은 리팩토링이 아니라 `type: bug` 후보로 분리한다.
- 항목마다 다음을 채운다.

| 항목 | 내용 |
|---|---|
| 제목 | `refactor(<scope>): ...` 또는 `fix(<scope>): ...` |
| 트랙 | 리팩토링 / 버그 수정 |
| 근거 | `경로:줄` 2개 이상 |
| 효과 | 무엇이 좋아지는가(위반 N건 해소, 중복 제거, 테스트 가능성 등) |
| 위험 | 상(서비스 간 영향, 동시성, 이벤트) / 중 / 하 |
| 기준 준비 | 기존 테스트로 충분 / 특성 테스트 필요 / 재현 테스트 필요 |
| 크기 | 작음(파일 1~3개) / 중간 / 큼(나눠야 함) |

- 우선순위: 위험 하, 크기 작음, 기준 준비가 쉬운 것부터. 큰 항목은 나누는 방법을 제안한다.
- 2026-11-18 결정: 동결된 계층 위반 정리는 AI 작업 체계가 완성된 뒤로 미룬다. 목록에는 넣되 "보류(체계 완성 후)"로 표시한다.

## 4. 보고와 등록

- 표 형태로 보고하고, 등록할 항목을 사용자가 고르게 한다. **승인 없이 이슈를 만들지 않는다.**
- 승인된 항목만 등록한다. 라벨: 트랙 라벨(`type: refactor` 또는 `type: bug`)과 `source: scan`.
  ```bash
  gh issue create --repo <origin 저장소> --title "..." --label "type: refactor" --label "source: scan" --body-file <파일>
  ```
- 본문: 배경, 근거(`경로:줄`), 효과, 위험, 기준 준비 방법, 제안하는 작업 순서.
- 진단 결과 전체는 `docs/ai-system/audits/YYYY-MM-DD-<범위>.md`로 저장해 다음 진단 때 비교한다.
