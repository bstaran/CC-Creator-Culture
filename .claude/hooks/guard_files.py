#!/usr/bin/env python3
"""PreToolUse(Read, Edit, Write, NotebookEdit, Grep) 차단 hook.

- 비밀 값 파일(.env, *.tfvars, backend.hcl, *.tfstate) 읽기와 수정을 막는다. *.example은 허용한다.
- 이미 있는 Flyway 마이그레이션 파일의 수정을 막는다(새 버전 파일 추가는 허용).
"""
import json
import os
import re
import sys


def block(reason: str) -> None:
    print(f"[guard-files] 차단: {reason}", file=sys.stderr)
    sys.exit(2)


def is_secret(path: str) -> bool:
    name = os.path.basename(path.rstrip("/"))
    if name.endswith(".example"):
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name.endswith(".tfvars") or name == "backend.hcl":
        return True
    if ".tfstate" in name:
        return True
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
    if not path:
        sys.exit(0)

    if is_secret(path):
        block(f"`{path}`는 비밀 값 파일이라 읽거나 고치지 않는다. 필요한 키 이름은 `.env.example`이나 `*.example`에서 확인한다.")

    if tool in ("Edit", "Write") and re.search(r"/db/migration/V[^/]*\.sql$", path) and os.path.exists(path):
        block(f"이미 있는 Flyway 마이그레이션(`{os.path.basename(path)}`)은 수정하지 않는다. 새 버전 파일을 추가한다.")

    sys.exit(0)


if __name__ == "__main__":
    main()
