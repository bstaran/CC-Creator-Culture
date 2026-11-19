#!/usr/bin/env python3
"""다른 모델(Antigravity CLI `agy`)로 문서의 가독성과 표현을 교정 제안받는다.

내용의 사실 여부는 보지 않고, 어색한 표현, 번역투, 긴 문장, 맞춤법, 문체, 가운뎃점 사용만 본다.
결과는 JSON으로 출력하고, 반영 여부는 호출한 쪽(Claude의 /doc-review)이 판단한다.

사용법:
    python3 scripts/ai/doc-review.py docs/ai-system/guide.md [다른 파일 ...]
    python3 scripts/ai/doc-review.py --model gemini-4-neon-high docs/ai-system/plan.md
    python3 scripts/ai/doc-review.py --stdin-name pr-body.md < pr-body.md   # 파일이 아닌 글(PR 본문 등)

교정 기록(PR 생성 전 hook이 확인한다):
    교정을 마친 문서는 내용 해시로 기록된다(.git/ai-doc-review.json, 커밋되지 않음, worktree 공유).
    교정이 끝나면 자동으로 "reviewed", agy를 못 쓰거나 실패하면 "skipped"로 기록한다.
    python3 scripts/ai/doc-review.py --mark <파일 ...>      # 제안을 반영한 뒤, 반영한 내용으로 다시 기록
    python3 scripts/ai/doc-review.py --check-pr [--base dev] [--head <브랜치>] [--body-file <PR 본문>]
                                                            # 브랜치에서 바뀐 .md와 PR 본문 중 기록 없는 파일 출력(있으면 종료 코드 1)

종료 코드: 0 완료, 3 agy를 쓸 수 없어 건너뜀, 2 잘못된 입력, 1 교정 기록 없는 파일 있음(--check-pr)
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "prompts", "doc-review.md")
SCHEMA_FILE = os.path.join(HERE, "prompts", "doc-review.schema.json")
DEFAULT_MODEL = "gemini-4-hydrogen-medium"
FALLBACK_MODEL = "gemini-3.8-flash-high"   # 기본 모델이 과부하로 실패할 때
RETRY_WAIT_SECONDS = 20
CHUNK_LINES = 250
# 교정 확인에서 제외할 경로(모델에 주는 프롬프트는 문장을 바꾸면 동작이 바뀐다)
CHECK_EXCLUDE_PREFIXES = ("scripts/ai/prompts/",)


def git_out(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd).stdout.strip()


def state_path(cwd: str | None = None) -> str:
    common = git_out("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    return os.path.join(common, "ai-doc-review.json")


def load_state(cwd: str | None = None) -> dict:
    try:
        with open(state_path(cwd), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def record(entries: list[tuple[str, bytes, str, str]], cwd: str | None = None) -> None:
    """(이름, 내용, 상태, 메모) 목록을 내용 해시 기준으로 기록한다."""
    state = load_state(cwd)
    for name, content, status, note in entries:
        state[hashlib.sha256(content).hexdigest()] = {
            "path": name, "status": status, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(state_path(cwd), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def check_pr(base: str, head: str, body_file: str | None) -> int:
    """PR에 들어갈 .md(브랜치에 커밋된 내용)와 PR 본문 중 교정 기록이 없는 것을 찾는다."""
    state = load_state()
    base_ref = base if "/" in base else f"origin/{base}"
    head = head.split(":", 1)[-1]   # owner:branch 형식
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", head], capture_output=True).returncode != 0:
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{head}"], capture_output=True).returncode == 0:
            head = f"origin/{head}"
        else:
            print(f"PR 브랜치({head})를 찾을 수 없어 교정 여부를 확인하지 못했다. 브랜치를 push했는지 확인한다.")
            return 1
    changed = git_out("diff", "--name-only", "--diff-filter=AMR", f"{base_ref}...{head}", "--", "*.md").splitlines()
    missing = []
    for path in changed:
        if not path or path.startswith(CHECK_EXCLUDE_PREFIXES):
            continue
        blob = subprocess.run(["git", "show", f"{head}:{path}"], capture_output=True).stdout
        if hashlib.sha256(blob).hexdigest() not in state:
            missing.append(path)
    if body_file:
        try:
            with open(body_file, "rb") as fh:
                if hashlib.sha256(fh.read()).hexdigest() not in state:
                    missing.append(f"{body_file}(PR 본문)")
        except OSError:
            missing.append(f"{body_file}(PR 본문 파일을 읽을 수 없음)")
    if missing:
        print("교정 기록이 없는 문서(커밋된 내용 기준):")
        for m in missing:
            print(f"  - {m}")
        print("`/doc-review`로 교정하고, 제안을 반영했다면 `python3 scripts/ai/doc-review.py --mark <파일>`로 기록한 뒤 커밋한다.")
        return 1
    print(f"교정 확인 통과({len(changed)}개 문서{', PR 본문' if body_file else ''})")
    return 0


def is_secret(path: str) -> bool:
    name = os.path.basename(path)
    if name.endswith(".example"):
        return False
    return name == ".env" or name.startswith(".env.") or name.endswith(".tfvars") \
        or name == "backend.hcl" or ".tfstate" in name


def chunks(lines: list[str]):
    for start in range(0, len(lines), CHUNK_LINES):
        yield start, lines[start:start + CHUNK_LINES]


def review_chunk_with_fallback(name: str, start: int, part: list[str], model: str, fallback: str, timeout: int) -> dict:
    """일시 오류(과부하 등)는 한 번 다시 시도하고, 그래도 실패하면 대체 모델로 시도한다."""
    r = review_chunk(name, start, part, model, timeout)
    if r["status"] in ("error", "timeout"):
        time.sleep(RETRY_WAIT_SECONDS)
        r = review_chunk(name, start, part, model, timeout)
    if r["status"] in ("error", "timeout") and fallback and fallback != model:
        r = review_chunk(name, start, part, fallback, timeout)
        r["model"] = fallback
    else:
        r["model"] = model
    return r


def review_chunk(name: str, start: int, part: list[str], model: str, timeout: int) -> dict:
    numbered = "".join(f"{start + i + 1}|{line}" for i, line in enumerate(part))
    prompt = (
        open(PROMPT_FILE, encoding="utf-8").read()
        + "\n도구를 쓰지 말고, 아래 문서 내용만 보고 답한다.\n"
        + "응답은 다른 설명 없이 아래 JSON 스키마를 따르는 JSON 객체 하나만 출력한다.\n"
        + open(SCHEMA_FILE, encoding="utf-8").read() + "\n\n"
        + f'<document name="{name}" lines="{start + 1}-{start + len(part)}">\n{numbered}\n</document>\n'
    )
    cmd = [
        "agy", "-p", prompt,
        "--model", model,
        "--mode", "plan",
        "--output-format", "json",
        "--print-timeout", f"{timeout}s",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "suggestions": []}
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "error": (proc.stderr or proc.stdout)[-500:], "suggestions": []}
    if out.get("status") != "SUCCESS":
        return {"status": "error", "error": str(out)[-500:], "suggestions": []}
    response = out.get("response")
    try:
        data = extract_json(response) if isinstance(response, str) else response
        suggestions = data.get("suggestions", [])
    except (json.JSONDecodeError, AttributeError, ValueError):
        return {"status": "unparsed", "raw": str(response)[:4000], "suggestions": []}
    return {"status": "ok", "seconds": round(out.get("duration_seconds", 0)), "suggestions": suggestions}


def extract_json(text: str) -> dict:
    """응답에서 JSON 객체를 꺼낸다(코드 블록으로 감싸거나 앞뒤에 설명이 붙어도 처리)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON 객체가 없다")
    return json.loads(text[start:end + 1])


def check(lines: list[str], suggestions: list[dict]) -> None:
    """제안이 원문과 맞는지, 규칙(가운뎃점)을 어기는지 표시한다."""
    for s in suggestions:
        flags = []
        ln = s.get("line", 0)
        text = lines[ln - 1] if 0 < ln <= len(lines) else ""
        if s.get("original") and s["original"] not in text:
            flags.append("original-not-found")
        if "·" in s.get("suggestion", ""):
            flags.append("middle-dot")
        if flags:
            s["flags"] = flags


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*")
    parser.add_argument("--model", default=os.environ.get("DOC_REVIEW_MODEL", DEFAULT_MODEL))
    parser.add_argument("--fallback-model", default=os.environ.get("DOC_REVIEW_FALLBACK_MODEL", FALLBACK_MODEL),
                        help="기본 모델 실패 시 쓸 모델(빈 문자열이면 사용 안 함)")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--stdin-name", help="표준 입력으로 받은 글의 이름(PR 본문 등)")
    parser.add_argument("--mark", action="store_true", help="교정 없이 현재 내용을 교정 완료로 기록(제안 반영 후에만 쓴다)")
    parser.add_argument("--check-pr", action="store_true", help="PR에 들어갈 문서의 교정 기록 확인")
    parser.add_argument("--base", default="dev")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body-file")
    args = parser.parse_args()

    if args.check_pr:
        return check_pr(args.base, args.head, args.body_file)
    if args.mark:
        entries = []
        for path in args.files:
            with open(path, "rb") as fh:
                entries.append((path, fh.read(), "reviewed", "제안 반영 후 기록"))
        record(entries)
        print(f"교정 기록: {len(entries)}개")
        return 0

    if not args.files and not args.stdin_name:
        parser.print_usage(sys.stderr)
        return 2
    if shutil.which("agy") is None:
        skipped = []
        for path in args.files:
            with open(path, "rb") as fh:
                skipped.append((path, fh.read(), "skipped", "agy 없음"))
        record(skipped)
        print(json.dumps({"status": "skipped", "reason": "agy(Antigravity CLI)를 찾을 수 없다"}, ensure_ascii=False))
        return 3

    inputs = []
    if args.stdin_name:
        inputs.append((args.stdin_name, sys.stdin.read()))
    for path in args.files:
        if is_secret(path):
            print(f"비밀 값 파일은 보내지 않는다: {path}", file=sys.stderr)
            return 2
        with open(path, encoding="utf-8") as fh:
            inputs.append((path, fh.read()))

    result = {"model": args.model, "files": {}}
    for name, content in inputs:
        lines = content.splitlines(keepends=True)
        merged = {"status": "ok", "suggestions": []}
        for start, part in chunks(lines):
            r = review_chunk_with_fallback(name, start, part, args.model, args.fallback_model, args.timeout)
            merged.setdefault("models", []).append(r.get("model"))
            if r["status"] != "ok":
                merged["status"] = r["status"]
                merged.setdefault("errors", []).append({k: v for k, v in r.items() if k != "suggestions"})
            merged["suggestions"].extend(r.get("suggestions", []))
        check([l.rstrip("\n") for l in lines], merged["suggestions"])
        merged["middle_dot_lines"] = [i + 1 for i, l in enumerate(lines) if "·" in l]
        result["files"][name] = merged
        if merged["status"] == "ok":
            record([(name, content.encode("utf-8"), "reviewed", ",".join(filter(None, merged.get("models", []))))])
        else:
            record([(name, content.encode("utf-8"), "skipped", f"교정 실패: {merged['status']}")])

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
