#!/usr/bin/env bash
# 실행 중인 로컬 스택에서 게이트웨이를 거쳐 라우트 등록, 인증 필터, 서비스 응답을 확인한다.
# stack-up.sh 이후에 쓴다. 결과를 항목별 통과/실패로 출력하고, 하나라도 실패하면 종료 코드 1.
#
# 사용법: scripts/ai/smoke-gateway.sh [게이트웨이 주소(기본 http://127.0.0.1:8080)] [라우트 파일(기본 config-repo/gateway-dev.yaml)]
#
# 판정 기준
# - 라우트: 라우트 파일의 모든 Path 접두어로 인증 없이 GET 요청. 404인데 응답에 errorCode가 없으면
#   게이트웨이에 라우트가 없는 것(실패). 502/503/504는 서비스 미등록이나 장애(실패). 그 밖의 코드는
#   서비스까지 도달한 것(통과: 401, 403, 405, 400, 200 등).
# - 인증 필터: 잘못된 Bearer 토큰으로 보호 경로 요청 시 401.
# - 공개 조회: GET /api/v1/products 가 200.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
base="${1:-http://127.0.0.1:8080}"
routes_file="${2:-config-repo/gateway-dev.yaml}"
fail=0

check() { # 이름, 결과(0/1), 상세
  if [[ "$2" == 0 ]]; then printf '통과  %-45s %s\n' "$1" "$3"; else printf '실패  %-45s %s\n' "$1" "$3"; fail=1; fi
}

request() { # method, path, [추가 curl 인자...] → "상태코드 본문"
  local method="$1" path="$2"; shift 2
  # 연결 실패 시 curl은 000을 출력하고 0이 아닌 코드로 끝난다(출력은 그대로 쓴다)
  curl -sS -o /tmp/smoke.$$.body -w '%{http_code}' -X "$method" "$@" "$base$path" 2>/dev/null || true
}

code=$(request GET /actuator/health)
check "게이트웨이 health" $([[ "$code" == 200 ]] && echo 0 || echo 1) "HTTP $code"
if [[ "$code" == 000 ]]; then
  echo "[smoke] 게이트웨이($base)에 연결할 수 없다. stack-up.sh로 스택을 먼저 띄운다." >&2
  rm -f /tmp/smoke.$$.body
  exit 1
fi

# 라우트 파일의 Path 접두어(** 제거)
mapfile -t prefixes < <(grep -oE 'Path=[^[:space:]]+' "$routes_file" | sed 's/^Path=//' | tr ',' '\n' | sed 's#/\*\*$##' | sort -u)
for prefix in "${prefixes[@]}"; do
  code=$(request GET "$prefix")
  body=$(cat /tmp/smoke.$$.body 2>/dev/null)
  if [[ "$code" == 404 && "$body" != *errorCode* ]]; then
    check "라우트 $prefix" 1 "HTTP 404(게이트웨이 라우트 없음)"
  elif [[ "$code" =~ ^50[234]$ || "$code" == 000 ]]; then
    check "라우트 $prefix" 1 "HTTP $code(서비스 미등록 또는 장애)"
  elif [[ ! "$code" =~ ^[1-5][0-9][0-9]$ ]]; then
    check "라우트 $prefix" 1 "응답 없음($code)"
  else
    check "라우트 $prefix" 0 "HTTP $code"
  fi
done

code=$(request GET /api/v1/orders -H 'Authorization: Bearer invalid.token.value')
check "인증 필터(잘못된 토큰 → 401)" $([[ "$code" == 401 ]] && echo 0 || echo 1) "HTTP $code"

code=$(request GET /api/v1/products)
check "공개 조회 GET /api/v1/products" $([[ "$code" == 200 ]] && echo 0 || echo 1) "HTTP $code"

rm -f /tmp/smoke.$$.body
if [[ "$fail" == 0 ]]; then echo "[smoke] 전체 통과"; else echo "[smoke] 실패 항목이 있다" >&2; fi
exit "$fail"
