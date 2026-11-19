#!/usr/bin/env python3
"""PreToolUse(Bash) 차단 hook.

CLAUDE.md 금지 사항 중 Bash로 우회할 수 있는 것을 막는다. 차단하면 exit 2와 사유(stderr)를 돌려준다.
명령 위치에 온 단어만 판단한다(heredoc 본문, 커밋 메시지 같은 텍스트는 검사하지 않는다).
"""
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED_BRANCHES = {"dev", "main"}
DOC_REVIEW_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "ai", "doc-review.py")
CWD = {"path": os.getcwd()}   # 같은 명령 안의 `cd <경로>`를 따라간다(gh pr create 위치 판단용)
WRAPPERS = {"sudo", "time", "command", "nohup", "env", "exec", "xargs"}
TERRAFORM_ALLOWED = {"fmt", "init", "validate", "test", "version", "providers", "-version", "--version", "-help", "--help"}
TEXT_ONLY_COMMANDS = {"echo", "printf"}


def block(reason: str) -> None:
    print(f"[guard-bash] 차단: {reason}", file=sys.stderr)
    sys.exit(2)


def current_branch() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def upstream_branch() -> str:
    try:
        ref = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""
    return ref.split("/", 1)[1] if "/" in ref else ""


def strip_heredocs(cmd: str) -> str:
    pattern = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?=\n|$)", re.DOTALL)
    return pattern.sub("<<HEREDOC", cmd)


def segments(cmd: str) -> list[str]:
    parts = re.split(r"\n|;|&&|\|\||\||\$\(|`|\(|\)", cmd)
    return [p.strip() for p in parts if p.strip()]


def argv_of(segment: str) -> list[str]:
    try:
        argv = shlex.split(segment, posix=True)
    except ValueError:
        argv = segment.split()
    while argv and (re.match(r"^\w+=", argv[0]) or argv[0] in WRAPPERS or argv[0].startswith("-")):
        argv = argv[1:]
    if argv:
        argv[0] = os.path.basename(argv[0])
    return argv


def first_positional(args: list[str], skip_value_opts: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    i = 0
    while i < len(args):
        a = args[i]
        if a in skip_value_opts:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return "", []


def check_terraform(argv: list[str]) -> None:
    sub, _ = first_positional(argv[1:])
    if sub and sub not in TERRAFORM_ALLOWED:
        block(f"`terraform {sub}`은 AI가 실행하지 않는다. 로컬에서는 fmt, init -backend=false, validate, test까지만 한다(infra/CLAUDE.md).")


def option_value(argv: list[str], *names: str) -> str | None:
    for i, a in enumerate(argv):
        for n in names:
            if a == n and i + 1 < len(argv):
                return argv[i + 1]
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
    return None


def check_pr_doc_review(argv: list[str]) -> None:
    """PR을 만들기 전에 바뀐 문서와 PR 본문이 /doc-review를 거쳤는지 확인한다."""
    if os.environ.get("CC_SKIP_DOC_REVIEW_CHECK") == "1" or not os.path.exists(DOC_REVIEW_SCRIPT):
        return
    if option_value(argv, "--body", "-b") is not None or "--fill" in argv or "-f" in argv:
        block("PR 본문은 `--body-file <파일>`로 넘긴다. 본문 파일도 `/doc-review`로 교정한 뒤 PR을 만든다.")
    body_file = option_value(argv, "--body-file", "-F")
    cmd = [sys.executable, DOC_REVIEW_SCRIPT, "--check-pr",
           "--base", option_value(argv, "--base", "-B") or "dev",
           "--head", option_value(argv, "--head", "-H") or "HEAD"]
    if body_file:
        cmd += ["--body-file", body_file]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=CWD["path"])
    except Exception:
        return
    if result.returncode == 1:
        block("문서 교정(/doc-review)을 거치지 않은 문서가 있다.\n" + result.stdout.strip())


def check_gh(argv: list[str]) -> None:
    if argv[1:3] == ["pr", "create"]:
        check_pr_doc_review(argv)
    if argv[1:3] == ["workflow", "run"]:
        block("GitHub 워크플로우 수동 실행(배포 포함)은 사람이 한다.")
    if len(argv) > 1 and argv[1] == "api" and any("/dispatches" in a for a in argv[2:]):
        block("GitHub 워크플로우 수동 실행(배포 포함)은 사람이 한다.")


def check_git_push(args: list[str]) -> None:
    if any(a in ("-f", "--force") or a.startswith("--force") for a in args):
        block("force push는 하지 않는다(--force-with-lease 포함, 필요하면 사람이 한다).")
    positional = [a for a in args if not a.startswith("-")]
    if positional and positional[0] != "origin":
        block(f"`origin` 외 원격(`{positional[0]}`)에는 push하지 않는다.")
    refspecs = positional[1:]
    branch = current_branch()
    if not refspecs:
        if branch in PROTECTED_BRANCHES:
            block(f"`{branch}` 브랜치에서 직접 push하지 않는다. 작업 브랜치를 만든다.")
        upstream = upstream_branch()
        if upstream in PROTECTED_BRANCHES:
            block(f"현재 브랜치의 upstream이 `{upstream}`이라 인자 없는 push가 `{upstream}`로 갈 수 있다. `git push -u origin <브랜치>`로 명시한다.")
        return
    for ref in refspecs:
        target = ref.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
        if target in PROTECTED_BRANCHES or (target == "HEAD" and branch in PROTECTED_BRANCHES):
            block(f"`{target}`에 직접 push하지 않는다. PR로 머지한다.")


def check_env_access(segment: str) -> None:
    # docker compose --env-file .env 처럼 파일을 다른 프로그램에 넘기기만 하는 경우는 허용한다.
    stripped = re.sub(r"--env-file(?:=|\s+)\S+", " ", segment)
    for m in re.finditer(r"(?<![\w.-])(?:[\w./-]*/)?\.env(?:\.[\w-]+)?(?![\w-])", stripped):
        if m.group(0).endswith(".env.example"):
            continue
        block(f"`{m.group(0)}`(비밀 값 파일)에 접근하지 않는다. 예시는 `.env.example`을 본다.")


CLOUD_READ_PREFIXES = ("describe", "get", "list", "ls", "show", "help")


def is_image_push(argv: list[str]) -> bool:
    sub = argv[1:3]
    return (sub[:1] == ["push"] or sub in (["image", "push"], ["compose", "push"])
            or ("buildx" in argv and "--push" in argv))


def check_cloud_cli(argv: list[str]) -> None:
    """클라우드 CLI는 조회만 허용한다(aws: describe-/get-/list-, oci: get/list). 쓰기는 사람이 CI에서 한다."""
    positional = []   # 첫 옵션이 나오기 전까지의 단어(서비스, 리소스, 동작)
    for a in argv[1:]:
        if a.startswith("-"):
            break
        positional.append(a)
    if argv[0] == "aws" and positional[:2] == ["sts", "get-caller-identity"]:
        return
    action = positional[1] if argv[0] == "aws" and len(positional) > 1 else (positional[-1] if positional else "")
    if not action.startswith(CLOUD_READ_PREFIXES):
        block(f"`{argv[0]} {' '.join(positional[:3])}`: 클라우드 리소스를 바꾸는 명령은 AI가 실행하지 않는다(조회만 허용). 적용은 사람이 CI에서 한다.")


def check_segment(segment: str) -> None:
    argv = argv_of(segment)
    if not argv:
        return
    cmd = argv[0]
    is_text = cmd in TEXT_ONLY_COMMANDS

    if cmd == "cd" and len(argv) > 1:
        CWD["path"] = os.path.normpath(os.path.join(CWD["path"], os.path.expanduser(argv[1])))

    if cmd == "terraform":
        check_terraform(argv)
    elif cmd == "gh":
        check_gh(argv)
        if len(argv) > 2 and argv[1] in ("pr", "issue") and argv[2] in ("create", "edit", "comment", "review"):
            is_text = True
    elif cmd == "git":
        sub, rest = first_positional(argv[1:], ("-C", "-c"))
        if sub == "push":
            check_git_push(rest)
        if sub in ("commit", "tag"):
            is_text = True
    elif cmd in ("aws", "oci"):
        check_cloud_cli(argv)
    elif cmd == "docker" and is_image_push(argv):
        block("이미지 push는 AI가 하지 않는다. 이미지는 CI가 빌드하고 게시한다.")
    elif "gradlew" in cmd:
        if re.search(r"(?:^|\s)(?:-x|--exclude-task)(?:=|\s+)\S*test\b", segment, re.IGNORECASE):
            block("테스트 단계를 건너뛰지 않는다(`-x test` 금지).")

    if not is_text:
        check_env_access(segment)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cmd = (payload.get("tool_input") or {}).get("command") or ""
    for segment in segments(strip_heredocs(cmd)):
        check_segment(segment)
    sys.exit(0)


if __name__ == "__main__":
    main()
