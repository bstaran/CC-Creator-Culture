#!/usr/bin/env bash
# 로컬 전체 스택을 내린다. 기본은 데이터(볼륨)를 남긴다.
# 사용법: scripts/ai/stack-down.sh [--volumes]   (--volumes: DB, Kafka 데이터까지 삭제)
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
extra=()
[[ "${1:-}" == "--volumes" ]] && extra=(--volumes)

env_args=()
[[ -f .env ]] && env_args=(--env-file .env)
docker compose "${env_args[@]}" -f compose.yaml -f compose.apps.yaml down "${extra[@]}"
echo "[stack-down] 완료${extra:+ (볼륨 삭제)}"
