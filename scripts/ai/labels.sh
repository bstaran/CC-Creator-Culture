#!/usr/bin/env bash
# AI 작업 체계에서 쓰는 GitHub 라벨을 만든다. 이미 있으면 색과 설명만 갱신한다(--force).
# 사용법: scripts/ai/labels.sh [owner/repo]   (생략하면 origin 원격의 저장소)
set -euo pipefail

repo="${1:-}"
if [[ -z "$repo" ]]; then
  url="$(git remote get-url origin)"
  repo="$(sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##' <<<"$url")"
fi
echo "대상 저장소: $repo"

create() {
  gh label create "$1" --repo "$repo" --color "$2" --description "$3" --force >/dev/null
  echo "  $1"
}

# 트랙(type)
create "type: bug"      "d73a4a" "A 그룹: 버그 수정"
create "type: refactor" "0e8a16" "A 그룹: 리팩토링(동작 변경 없음)"
create "type: feature"  "1d76db" "B 그룹: 기능 개발(스펙 승인 필요)"
create "type: research" "5319e7" "B 그룹: 조사/문서"
create "type: infra"    "fbca04" "C 그룹: 인프라/배포(AI는 plan까지)"
create "type: perf"     "f9a03f" "C 그룹: 성능(k6 기준선 비교)"

# 유입 경로(source)
create "source: ad-hoc" "c5def5" "개인 요청(로컬 세션, AI 작업 요청 이슈)"
create "source: scan"   "bfdadc" "정기 스캔에서 발견"

# 진행 상태
create "spec: approved" "0e8a16" "B 트랙 스펙 승인 완료, 구현 시작 가능"
