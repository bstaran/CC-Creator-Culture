#!/usr/bin/env python3
"""guard_bash.py, guard_files.py 회귀 테스트. hook을 고치면 실행한다.

    python3 .claude/hooks/test_guards.py

기대 종료 코드: 2 = 차단, 0 = 허용.
"""
import json
import os
import subprocess
import sys

HOOKS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HOOKS))

BASH_CASES = [
    # terraform: fmt/init/validate/test만 허용
    ("cd infra/terraform/aws/runtime && terraform apply", 2),
    ("terraform -chdir=x destroy", 2),
    ("terraform plan", 2),
    ("FOO=1 terraform apply -auto-approve", 2),
    ("terraform fmt -check -recursive", 0),
    ("terraform init -backend=false -input=false", 0),
    ("cd infra && terraform validate -no-color", 0),
    # 워크플로우 수동 실행
    ("gh workflow run aws-deploy.yml", 2),
    # push 규칙
    ("git push upstream feature/x", 2),
    ("git push origin dev", 2),
    ("git push origin HEAD:main", 2),
    ("git push --force origin feature/x", 2),
    ("git push --force-with-lease origin feature/x", 2),
    ("git -C /tmp push origin main", 2),
    ("git push origin feature/ai-system", 0),
    ("git push -u origin feature/ai-system", 0),
    # 비밀 값 파일
    ("cat .env", 2),
    ("grep SECRET apps/.env.local", 2),
    ("echo $(cat .env)", 2),
    ("git show HEAD:.env", 2),
    ("cat .env.example", 0),
    ("docker compose --env-file .env -f compose.yaml up -d", 0),
    ("echo $HOME/.envrc-like", 0),
    # 테스트 건너뛰기
    ("./gradlew build -x test", 2),
    ("./gradlew :apps:order-service:test --tests '*OrderTest'", 0),
    # 텍스트(커밋 메시지, heredoc, PR 본문)는 검사하지 않음
    ("git commit -q -F - <<'EOF'\nchore: terraform apply/destroy 차단, .env 접근 차단, git push origin dev 금지\nEOF\ngit push -q origin feature/ai-system", 0),
    ("git commit -m 'gh workflow run 차단 추가'", 0),
    ("gh pr create --title t --body-file body.md", 0),
    ("cat <<EOF > notes.md\nterraform apply\nEOF", 0),
    ("git status", 0),
    # 클라우드 CLI: 조회만 허용
    ("aws ecs update-service --cluster c --service s", 2),
    ("aws s3 rm s3://bucket/key", 2),
    ("oci compute instance terminate --instance-id x", 2),
    ("aws ecs describe-services --cluster c", 0),
    ("aws sts get-caller-identity", 0),
    ("oci os object list --bucket-name b", 0),
    # 이미지 push
    ("docker push ghcr.io/x/y:1", 2),
    ("docker image push x", 2),
    ("docker compose push", 2),
    ("docker buildx build --push -t x .", 2),
    ("docker compose -f load-test/docker-compose.yml run --rm k6 run x.js", 0),
    ("docker run --rm -v $PWD:/repo hashicorp/terraform:1.12.2 validate", 0),
    ("scripts/ai/tf-check.sh infra/terraform/aws/runtime", 0),
]

# 문서 교정 확인(저장소 상태와 무관한 경우만): CC_SKIP_DOC_REVIEW_CHECK 없이 실행
DOC_CHECK_CASES = [
    ("gh pr create --title t --body 'hi'", 2),       # 본문은 --body-file로만
    ("gh pr create --title t --fill", 2),
    ("gh pr create --title t --body-file b.md --head no-such-branch-xyz", 2),   # 브랜치를 못 찾으면 차단
    ("gh pr view 3", 0),
]

FILE_CASES = [
    ("Read", ".env", 2),
    ("Read", "infra/terraform/dev/terraform.tfvars", 2),
    ("Read", "infra/terraform/aws/runtime/backend.hcl", 2),
    ("Read", "infra/terraform/dev/terraform.tfvars.example", 0),
    ("Read", ".env.example", 0),
    ("Edit", "apps/order-service/src/main/resources/db/migration/V1__order_schema.sql", 2),
    ("Write", "apps/order-service/src/main/resources/db/migration/V99__new.sql", 0),
    ("Read", "apps/order-service/src/main/resources/db/migration/V1__order_schema.sql", 0),
]


def run(script: str, payload: dict, skip_doc_check: bool = True) -> int:
    env = dict(os.environ)
    if skip_doc_check:
        env["CC_SKIP_DOC_REVIEW_CHECK"] = "1"   # 일반 케이스는 저장소의 교정 상태와 무관하게 판정
    else:
        env.pop("CC_SKIP_DOC_REVIEW_CHECK", None)
    return subprocess.run([sys.executable, os.path.join(HOOKS, script)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=ROOT, env=env).returncode


def main() -> int:
    fails = 0
    for cmd, expect in BASH_CASES:
        rc = run("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}})
        if rc != expect:
            fails += 1
            print(f"BAD rc={rc} expect={expect} | {cmd!r}")
    for cmd, expect in DOC_CHECK_CASES:
        rc = run("guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": cmd}}, skip_doc_check=False)
        if rc != expect:
            fails += 1
            print(f"BAD rc={rc} expect={expect} | {cmd!r}")
    for tool, path, expect in FILE_CASES:
        rc = run("guard_files.py", {"tool_name": tool, "tool_input": {"file_path": os.path.join(ROOT, path)}})
        if rc != expect:
            fails += 1
            print(f"BAD rc={rc} expect={expect} | {tool} {path}")
    total = len(BASH_CASES) + len(DOC_CHECK_CASES) + len(FILE_CASES)
    print(f"{total - fails}/{total} 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
