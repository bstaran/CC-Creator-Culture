#!/usr/bin/env bash
# Terraform 변경을 로컬에서 검증한다(CI ci-aws.yml과 같은 단계). 원격 state와 클라우드 자격 증명 없이 도는 것만 한다.
#   fmt -check -recursive → init -backend=false → validate → (테스트 파일이 있으면) test
# plan, apply는 하지 않는다. plan은 사람이 CI(aws-deploy.yml plan)에서 실행한다.
#
# 사용법: scripts/ai/tf-check.sh [스택 디렉터리 ...]
#   인자가 없으면 origin/dev 대비 바뀐 .tf 파일이 있는 디렉터리를 검사한다.
# terraform이 없으면 Docker 이미지(hashicorp/terraform:1.12.2)로 실행한다.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
TF_VERSION=1.12.2

if [[ $# -gt 0 ]]; then
  dirs=("$@")
else
  mapfile -t dirs < <( { git diff --name-only origin/dev...HEAD; git status --porcelain | awk '{print $2}'; } \
    | grep -E '^infra/terraform/.*\.(tf|tftest\.hcl)$' | xargs -r -n1 dirname | sed 's#/tests$##' | sort -u)
fi
if [[ ${#dirs[@]} -eq 0 ]]; then
  echo "[tf-check] 바뀐 Terraform 디렉터리가 없다"
  exit 0
fi

# 저장소를 더럽히지 않는다: 작업 디렉터리(.terraform)는 저장소 밖, 프로바이더는 .ai-cache에 캐시,
# init이 고칠 수 있는 .terraform.lock.hcl은 실행 후 원래대로 복원한다.
data_root="$(mktemp -d)"
plugin_cache="$PWD/.ai-cache/terraform-plugins"
mkdir -p "$plugin_cache"
if command -v terraform >/dev/null 2>&1; then
  tf() { local d="$1"; shift; (cd "$d" && TF_DATA_DIR="$data_root/${d//\//_}" TF_PLUGIN_CACHE_DIR="$plugin_cache" terraform "$@"); }
  runner="terraform $(terraform version -json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null)"
elif docker info >/dev/null 2>&1; then
  tf() {
    local d="$1"; shift
    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/repo -v "$data_root":/tfdata -v "$plugin_cache":/plugins \
      -e TF_DATA_DIR="/tfdata/${d//\//_}" -e TF_PLUGIN_CACHE_DIR=/plugins -e HOME=/tmp \
      -w "/repo/$d" "hashicorp/terraform:${TF_VERSION}" "$@"
  }
  runner="docker hashicorp/terraform:${TF_VERSION}"
else
  echo "[tf-check] 건너뜀: terraform도 Docker도 쓸 수 없다. CI(ci-aws.yml)의 검증 결과를 확인한다." >&2
  exit 3
fi
echo "[tf-check] 실행 도구: $runner"

restore_locks() {
  for d in "${dirs[@]}"; do
    [[ -f "$data_root/lock-backup/$d/.terraform.lock.hcl" ]] && cp "$data_root/lock-backup/$d/.terraform.lock.hcl" "$d/.terraform.lock.hcl"
  done
  rm -rf "$data_root"
}
trap restore_locks EXIT

fail=0
for d in "${dirs[@]}"; do
  echo "== $d"
  if [[ -f "$d/.terraform.lock.hcl" ]]; then
    mkdir -p "$data_root/lock-backup/$d" && cp "$d/.terraform.lock.hcl" "$data_root/lock-backup/$d/"
  fi
  step() { # 이름, 명령...
    local name="$1"; shift
    if out=$(tf "$d" "$@" 2>&1); then echo "  통과  $name"; else echo "  실패  $name"; echo "$out" | tail -n 20 | sed 's/^/        /'; fail=1; fi
  }
  step "fmt"      fmt -check -recursive
  step "init"     init -backend=false -input=false -no-color
  step "validate" validate -no-color
  if compgen -G "$d/tests/*.tftest.hcl" >/dev/null || compgen -G "$d/*.tftest.hcl" >/dev/null; then
    step "test"   test -no-color
  fi
done

[[ "$fail" == 0 ]] && echo "[tf-check] 전체 통과" || echo "[tf-check] 실패 항목이 있다" >&2
exit "$fail"
