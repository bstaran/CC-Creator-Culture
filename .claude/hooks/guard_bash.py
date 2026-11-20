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


APPROVED_LABEL = "spec: approved"


def label_values(argv: list[str]) -> list[str]:
    values = []
    for i, a in enumerate(argv):
        for n in ("--add-label", "--label", "-l"):
            if a == n and i + 1 < len(argv):
                values += argv[i + 1].split(",")
            elif a.startswith(n + "="):
                values += a.split("=", 1)[1].split(",")
            elif n == "-l" and a.startswith("-l") and not a.startswith("--") and len(a) > 2:
                values += a[2:].lstrip("=").split(",")   # -l'spec: approved'처럼 붙여 쓴 형태
    return [norm_label(v) for v in values]


def norm_label(value: str) -> str:
    """GitHub 라벨 이름은 대소문자를 구분하지 않으므로 비교용으로 정규화한다."""
    return " ".join(value.split()).casefold()


def api_method(argv: list[str]) -> str:
    method = option_value(argv, "--method", "-X")
    if method:
        return method.upper()
    has_body = any(a in ("-f", "-F", "--field", "--raw-field", "--input") or a.startswith(("--field=", "--raw-field=", "--input="))
                   for a in argv)
    return "POST" if has_body else "GET"


def without_repo_flag(argv: list[str]) -> list[str]:
    """`gh pr -R o/r merge`처럼 하위 명령 앞에 온 저장소 옵션을 빼서 명령 위치를 고정한다."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ("-R", "--repo"):
            skip = True
            continue
        if a.startswith("--repo=") or (a.startswith("-R") and len(a) > 2 and not a.startswith("--")):
            continue
        out.append(a)
    return out


def approves(args: list[str]) -> bool:
    for a in args:
        if a == "--approve" or a.startswith("--approve="):
            return True
        if a.startswith("-") and not a.startswith("--") and "a" in a[1:2]:
            return True   # -a, -ab 'LGTM'
    return False


def check_gh(argv: list[str]) -> None:
    argv = without_repo_flag(argv)
    if argv[1:3] == ["pr", "create"]:
        check_pr_doc_review(argv)
    if argv[1:3] == ["pr", "merge"]:
        block("PR 머지는 사람이 한다.")
    if argv[1:3] == ["pr", "review"] and approves(argv[3:]):
        block("PR 승인은 사람이 한다. 리뷰 의견은 `--comment`로 남긴다.")
    if len(argv) > 2 and argv[1] in ("issue", "pr") and argv[2] in ("create", "edit") \
            and norm_label(APPROVED_LABEL) in label_values(argv):
        block(f"`{APPROVED_LABEL}` 라벨은 사람만 붙인다(스펙 승인).")
    if len(argv) > 1 and argv[1] == "api":
        args = argv[2:]
        writing = api_method(argv) != "GET"
        if writing and any("/labels" in a for a in args) and any(norm_label(APPROVED_LABEL) in norm_label(a) for a in args):
            block(f"`{APPROVED_LABEL}` 라벨은 사람만 붙인다(스펙 승인).")
        if writing and any(re.search(r"/(pulls/\d+/merge|merges)/?(\?.*)?$", a) for a in args):
            block("PR과 브랜치 머지는 사람이 한다.")
        if writing and any(re.search(r"/pulls/\d+/reviews", a) for a in args) and any("approve" in a.casefold() for a in args):
            block("PR 승인은 사람이 한다.")
        if any("mergepullrequest" in a.casefold() or "enablepullrequestautomerge" in a.casefold() for a in args):
            block("PR 머지는 사람이 한다.")
    if argv[1:3] == ["workflow", "run"]:
        block("GitHub 워크플로우 수동 실행(배포 포함)은 사람이 한다.")
    if len(argv) > 1 and argv[1] == "api" and any("/dispatches" in a for a in argv[2:]):
        block("GitHub 워크플로우 수동 실행(배포 포함)은 사람이 한다.")


RISKY_GIT_CONFIG = ("alias.", "url.", "remote.", "credential.", "include.", "includeif.", "http.", "core.sshcommand",
                    "core.pager", "core.editor", "core.hookspath", "core.fsmonitor", "sequence.editor", "diff.external",
                    "gpg.program", "pager.")


def risky_config_key(key: str) -> bool:
    return key.split("=", 1)[0].strip().lower().startswith(RISKY_GIT_CONFIG)


def check_git_options(argv: list[str]) -> None:
    """`git -c alias.x='!cmd'` 같은 설정으로 임의 명령을 실행하거나 원격을 바꾸는 것을 막는다."""
    for i, a in enumerate(argv):
        if a == "-c" and i + 1 < len(argv) and risky_config_key(argv[i + 1]):
            block(f"`git -c {argv[i + 1].split('=', 1)[0]}`는 쓰지 않는다(명령 실행, 원격, 자격 증명 설정).")
        if a.startswith("--config-env"):
            block("`git --config-env`는 쓰지 않는다.")


def check_git_config(rest: list[str]) -> None:
    if any(a in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin") for a in rest):
        return
    key = next((a for a in rest if not a.startswith("-")), "")
    if risky_config_key(key):
        block(f"`git config {key}`는 바꾸지 않는다(명령 실행, 원격, 자격 증명 설정).")


def check_git_remote(rest: list[str]) -> None:
    sub = next((a for a in rest if not a.startswith("-")), "")
    if sub in ("add", "set-url", "rename", "remove", "rm", "set-head", "set-branches"):
        block(f"`git remote {sub}`는 하지 않는다. push 대상은 `origin`으로 고정한다.")


def check_git_push(args: list[str]) -> None:
    short_flags = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
    if any(a in ("--force",) or a.startswith("--force") for a in args) or "f" in short_flags \
            or any(not a.startswith("-") and a.startswith("+") for a in args):
        block("force push는 하지 않는다(--force-with-lease, -uf, +refspec 포함, 필요하면 사람이 한다).")
    if any(a in ("--mirror", "--all", "--delete", "--prune") or a.startswith(("--repo", "--mirror", "--all")) for a in args) \
            or "d" in short_flags:
        block("`--mirror`, `--all`, `--delete`, `--prune`, `--repo` push는 하지 않는다. 작업 브랜치 하나만 push한다.")
    if any(not a.startswith("-") and a.startswith(":") for a in args):
        block("원격 브랜치 삭제(`:브랜치`)는 하지 않는다.")
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
        check_git_options(argv)
        sub, rest = first_positional(argv[1:], ("-C", "-c"))
        if sub == "push":
            check_git_push(rest)
        elif sub == "config":
            check_git_config(rest)
        elif sub == "remote":
            check_git_remote(rest)
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
