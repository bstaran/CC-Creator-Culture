#!/usr/bin/env bash
# 로컬 전체 스택(compose.yaml + compose.apps.yaml)을 띄우고, 모든 서비스가 healthy가 될 때까지 기다린다.
# 결과를 통과/실패로 출력한다. 실패하면 unhealthy 서비스의 상태와 마지막 로그 일부를 보여 준다.
#
# 사용법: scripts/ai/stack-up.sh [--no-build] [--timeout 초]
# 전제: 레포 루트의 .env(비밀 값)는 사람이 미리 만들어 둔다. 이 스크립트는 파일 내용을 읽거나 출력하지 않는다.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
build="--build"
timeout=300
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build) build=""; shift ;;
    --timeout) timeout="$2"; shift 2 ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f .env ]]; then
  echo "[stack-up] 실패: 레포 루트에 .env가 없다. .env.example을 참고해 사람이 만든 뒤 다시 실행한다." >&2
  exit 2
fi

compose=(docker compose --env-file .env -f compose.yaml -f compose.apps.yaml)
echo "[stack-up] 기동 중(최대 ${timeout}초)..."
if "${compose[@]}" up -d $build --wait --wait-timeout "$timeout" >/tmp/stack-up.$$.log 2>&1; then
  echo "[stack-up] 통과: 모든 서비스 healthy"
  "${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
  rm -f /tmp/stack-up.$$.log
  exit 0
fi

echo "[stack-up] 실패: 제한 시간 안에 healthy가 되지 않은 서비스가 있다" >&2
tail -n 20 /tmp/stack-up.$$.log >&2
rm -f /tmp/stack-up.$$.log
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}' >&2
for svc in $("${compose[@]}" ps --format '{{.Service}} {{.Health}}' | awk '$2 != "healthy" && $2 != "" {print $1}'); do
  echo "----- $svc 마지막 로그 40줄 -----" >&2
  "${compose[@]}" logs --no-color --tail 40 "$svc" >&2
done
exit 1
