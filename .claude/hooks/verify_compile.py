#!/usr/bin/env python3
"""Stop 검증 hook: 커밋되지 않은 Java/Gradle 변경이 있으면 해당 모듈의 포맷 검사와 컴파일을 실행한다.

- 변경 파일을 Gradle 모듈로 묶어 `spotlessCheck compileJava compileTestJava`만 실행한다(테스트는 작업 스킬에서 돌린다).
- 세션 작업 디렉터리의 체크아웃만 본다. worktree(`.claude/worktrees/<n>`)의 변경은 작업 스킬이 직접 빌드해 확인한다.
- 같은 변경 내용으로 이미 통과했다면 다시 돌리지 않는다(.git 안에 해시 저장).
- 컴파일 실패 시 exit 2로 종료를 막고 오류를 Claude에게 돌려준다. 고친 뒤에도 실패하면 한 번만 더 막고, 그다음은 경고만 남긴다.
- JDK가 없거나 CC_SKIP_VERIFY=1이면 건너뛴다.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

APP_MODULES = [":apps:user-service", ":apps:product-service", ":apps:order-service"]
MODULE_DIRS = {
    "apps/user-service/": ":apps:user-service",
    "apps/product-service/": ":apps:product-service",
    "apps/order-service/": ":apps:order-service",
    "infra/gateway/": ":infra:gateway",
    "infra/eureka-server/": ":infra:eureka-server",
    "infra/config-server/": ":infra:config-server",
    "libs/common/": ":libs:common",
}
ROOT_BUILD_FILES = {"build.gradle", "settings.gradle", "gradle/wrapper/gradle-wrapper.properties"}


def notice(msg: str) -> None:
    print(json.dumps({"systemMessage": f"[verify-compile] {msg}"}, ensure_ascii=False))
    sys.exit(0)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=30).stdout


def changed_files() -> list[str]:
    files = []
    for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].split(" -> ")[-1].strip('"')
        if line[:2].strip() == "D":
            continue
        files.append(path)
    return files


def modules_for(files: list[str]) -> list[str]:
    mods: set[str] = set()
    for f in files:
        if f in ROOT_BUILD_FILES:
            return sorted(set(MODULE_DIRS.values()))
        if not (f.endswith(".java") or f.endswith(".gradle")):
            continue
        for prefix, mod in MODULE_DIRS.items():
            if f.startswith(prefix):
                mods.add(mod)
                if mod == ":libs:common":
                    mods.update(APP_MODULES)
    return sorted(mods)


def fingerprint(files: list[str]) -> str:
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(f.encode())
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest()


def java_available() -> bool:
    home = os.environ.get("JAVA_HOME")
    if home and os.path.exists(os.path.join(home, "bin", "java")):
        return True
    return shutil.which("java") is not None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if os.environ.get("CC_SKIP_VERIFY") == "1":
        sys.exit(0)

    root = git("rev-parse", "--show-toplevel").strip()
    if not root:
        sys.exit(0)
    os.chdir(root)

    files = [f for f in changed_files() if f.endswith(".java") or f.endswith(".gradle") or f in ROOT_BUILD_FILES]
    mods = modules_for(files)
    if not mods:
        sys.exit(0)

    state_file = os.path.join(git("rev-parse", "--git-dir").strip(), "claude-verify-compile")
    fp = fingerprint(files)
    try:
        with open(state_file) as fh:
            if fh.read().strip() == fp:
                sys.exit(0)
    except OSError:
        pass

    if not java_available():
        notice("JDK 21을 찾지 못해 컴파일 검증을 건너뛰었다. JAVA_HOME을 설정하면 다음부터 실행된다.")

    tasks = [t for m in mods for t in (f"{m}:spotlessCheck", f"{m}:compileJava", f"{m}:compileTestJava")]
    try:
        result = subprocess.run(
            ["./gradlew", *tasks, "-q", "--console=plain"],
            capture_output=True, text=True, timeout=540,
        )
    except subprocess.TimeoutExpired:
        notice(f"컴파일 검증이 시간 안에 끝나지 않았다({', '.join(mods)}). 직접 확인이 필요하다.")

    if result.returncode == 0:
        with open(state_file, "w") as fh:
            fh.write(fp)
        sys.exit(0)

    output = (result.stdout + result.stderr).strip()
    tail = "\n".join(output.splitlines()[-40:])
    if "spotlessJavaCheck" in output and "format violations" in output:
        kind = "포맷 위반"
        hint = "`./gradlew " + " ".join(f"{m}:spotlessApply" for m in mods) + "`로 고친 뒤 마무리한다."
    else:
        kind = "컴파일 실패"
        hint = "고친 뒤 마무리한다."
    if payload.get("stop_hook_active"):
        notice(f"{kind}가 남아 있다({', '.join(mods)}). 사용자에게 상황을 보고할 것.\n{tail}")
    print(f"[verify-compile] {kind}({', '.join(mods)}). {hint}\n{tail}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
