#!/usr/bin/env python3
"""리뷰어 에이전트 전용 PreToolUse hook: 읽기 전용 git 명령만 허용한다.

리뷰어(arch, event, schema, infra)는 변경 내용을 직접 보려고 Bash를 쓰지만, 코드를 바꾸거나
다른 명령을 실행하면 안 된다. 에이전트 정의의 `tools`로는 Bash를 특정 명령으로 좁힐 수 없어
이 hook이 명령을 검사한다. 에이전트 frontmatter의 `hooks`로 등록하므로 그 에이전트가 실행 중일 때만 동작한다.

허용: `git [-C <경로>] [--no-pager] <diff|log|show|status|blame|ls-files|merge-base|rev-parse|grep> ...`
차단: 그 밖의 명령, 셸 연결/치환/리다이렉트, 파일을 쓰는 옵션(`--output`), 외부 프로그램을 부르는 옵션.
"""
import json
import shlex
import sys

READ_SUBCOMMANDS = {"diff", "log", "show", "status", "blame", "ls-files", "merge-base", "rev-parse", "grep"}
SHELL_META = (";", "&", "|", ">", "<", "`", "$(", "\n")
FORBIDDEN_ARG_PREFIXES = ("--output", "--ext-diff", "--textconv", "--open-files-in-pager", "-O")


def block(reason: str) -> None:
    print(f"[guard-reviewer] 차단: {reason} 리뷰어는 읽기 전용 git 명령(diff, log, show 등)만 쓴다.", file=sys.stderr)
    sys.exit(2)


def check(command: str) -> None:
    if any(m in command for m in SHELL_META):
        block("셸 연결, 치환, 리다이렉트는 쓸 수 없다. worktree는 `git -C <경로> diff ...`로 지정한다.")
    try:
        argv = shlex.split(command)
    except ValueError:
        block("명령을 해석할 수 없다.")
    if not argv or argv[0] != "git":
        block(f"`{argv[0] if argv else ''}`은 허용되지 않는다.")
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] == "-C" and i + 1 < len(argv):
            i += 2
        elif argv[i] == "--no-pager":
            i += 1
        else:
            block(f"git 전역 옵션 `{argv[i]}`은 허용되지 않는다(`-C`, `--no-pager`만 허용).")
    if i >= len(argv) or argv[i] not in READ_SUBCOMMANDS:
        block(f"`git {argv[i] if i < len(argv) else ''}`은 허용되지 않는다.")
    for arg in argv[i + 1:]:
        if arg.startswith(FORBIDDEN_ARG_PREFIXES):
            block(f"`{arg}` 옵션은 파일을 쓰거나 외부 프로그램을 실행할 수 있다.")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    check(str((payload.get("tool_input") or {}).get("command", "")))
    sys.exit(0)


if __name__ == "__main__":
    main()
