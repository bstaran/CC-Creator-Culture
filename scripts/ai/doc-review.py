#!/usr/bin/env python3
"""다른 모델(Antigravity CLI `agy`)로 문서의 가독성과 표현을 교정 제안받는다.

내용의 사실 여부는 보지 않고, 어색한 표현, 번역투, 긴 문장, 맞춤법, 문체, 가운뎃점 사용만 본다.
결과는 JSON으로 출력하고, 반영 여부는 호출한 쪽(Claude의 /doc-review)이 판단한다.

비용을 줄이는 방식:
    - 대상: 공유 문서만(`.claude/`, `CLAUDE.md`, 모델 프롬프트는 제외). 파일을 직접 지정하면 그 파일을 본다.
    - 범위: 바뀐 줄과 앞뒤 몇 줄만 보낸다. 기준은 마지막으로 교정한 내용, 없으면 기준 브랜치(origin/dev)의 내용이다.
            새 파일과 기준이 없는 글(PR 본문 등)은 전체를 보낸다. `--full`이면 항상 전체를 보낸다.
    - 호출: 여러 문서의 조각을 묶어(BATCH_LINES 줄 단위) 한 번에 보내고, 묶음끼리는 동시에 호출한다.
            `agy`는 호출마다 고정 비용(약 1.1만 입력 토큰, 약 10초)이 들어서 호출 횟수가 비용을 좌우한다.
    - 거르기: 원문 불일치, 가운뎃점, 백틱/코드 블록 수정, 표 열 변화, 용어 사전 표기 변경은 스크립트가 먼저 걸러 낸다.

사용법:
    python3 scripts/ai/doc-review.py                         # 브랜치에서 바뀐 대상 문서(origin/dev 기준)
    python3 scripts/ai/doc-review.py pr-body.md              # 바뀐 대상 문서 + 지정한 파일(PR 본문 등)
    python3 scripts/ai/doc-review.py --only docs/ai-system/guide.md
    python3 scripts/ai/doc-review.py --only --full docs/ai-system/plan.md
    python3 scripts/ai/doc-review.py --stdin-name pr-body.md < pr-body.md

교정 기록(PR 생성 전 hook이 확인한다):
    교정을 마친 문서는 내용 해시로 기록하고 그 내용을 보관한다(.git/ai-doc-review.json, .git/ai-doc-review/, 커밋되지 않음, worktree 공유).
    교정이 끝나면 자동으로 "reviewed", agy를 못 쓰거나 실패하면 "skipped"로 기록한다.
    doc-write.py로 Gemini가 쓴 글은 "written"으로 기록되며, 교정 기록과 같이 인정한다.
    python3 scripts/ai/doc-review.py --mark <파일 ...>      # 제안을 반영한 뒤, 반영한 내용으로 다시 기록
    python3 scripts/ai/doc-review.py --check-pr [--base dev] [--head <브랜치>] [--body-file <PR 본문>]

종료 코드: 0 완료, 3 agy를 쓸 수 없어 건너뜀, 2 잘못된 입력, 1 교정 기록 없는 파일 있음(--check-pr)
"""
import argparse
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "prompts", "doc-review.md")
SCHEMA_FILE = os.path.join(HERE, "prompts", "doc-review.schema.json")
GLOSSARY_FILE = os.path.join(HERE, "prompts", "doc-review-glossary.txt")
DEFAULT_MODEL = "gemini-4-neon-medium"
DEFAULT_BASE = "dev"
RETRY_WAIT_SECONDS = 20
BATCH_LINES = 200        # 한 번 호출에 보내는 최대 줄 수
CONTEXT_LINES = 3        # 바뀐 줄 앞뒤로 함께 보내는 줄 수
WORKERS = 4              # 동시에 보내는 묶음 수
# 교정 대상에서 제외(AI가 읽는 지침, 모델 프롬프트)
EXCLUDE_PREFIXES = (".claude/", "scripts/ai/prompts/")
EXCLUDE_NAMES = ("CLAUDE.md",)


# ---------- git, 기록 ----------

def git_out(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def git_blob(ref: str, path: str) -> bytes | None:
    p = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True)
    return p.stdout if p.returncode == 0 else None


def common_dir() -> str:
    return git_out("rev-parse", "--path-format=absolute", "--git-common-dir")


def state_path() -> str:
    return os.path.join(common_dir(), "ai-doc-review.json")


def snapshot_dir() -> str:
    return os.path.join(common_dir(), "ai-doc-review")


def load_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def record(entries: list[tuple[str, bytes, str, str]]) -> None:
    """(이름, 내용, 상태, 메모) 목록을 내용 해시 기준으로 기록한다. 여러 프로세스가 동시에 써도 기록이 사라지지 않게 잠근다."""
    path = state_path()
    os.makedirs(snapshot_dir(), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state()
        for name, content, status, note in entries:
            digest = hashlib.sha256(content).hexdigest()
            state[digest] = {"path": name, "status": status, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if status in ("reviewed", "written"):
                with open(os.path.join(snapshot_dir(), digest), "wb") as fh:
                    fh.write(content)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def last_reviewed(name: str, state: dict) -> str | None:
    """같은 이름으로 마지막에 교정(또는 반영 후 기록)하거나 doc-write.py로 쓴 내용."""
    best = None
    for digest, entry in state.items():
        if entry.get("path") == name and entry.get("status") in ("reviewed", "written"):
            if best is None or entry["at"] > best[1]:
                best = (digest, entry["at"])
    if best:
        try:
            with open(os.path.join(snapshot_dir(), best[0]), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None
    return None


def display_name(path: str) -> str:
    """레포 안의 파일은 레포 기준 상대 경로, 밖의 파일은 절대 경로."""
    root = git_out("rev-parse", "--show-toplevel")
    full = os.path.abspath(path)
    if root and (full + os.sep).startswith(root + os.sep):
        return os.path.relpath(full, root)
    return full


def is_target(path: str) -> bool:
    return path.endswith(".md") and not path.startswith(EXCLUDE_PREFIXES) \
        and os.path.basename(path) not in EXCLUDE_NAMES


def resolve_base(base: str) -> str:
    """`dev`는 `origin/dev`로, 원격에 없는 이름(커밋 해시 등)은 그대로 쓴다."""
    if "/" not in base and subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{base}"],
                                          capture_output=True).returncode == 0:
        return f"origin/{base}"
    return base


def changed_docs(base: str) -> list[str]:
    base_ref = resolve_base(base)
    names = git_out("diff", "--name-only", "--diff-filter=AMR", f"{base_ref}...HEAD", "--", "*.md").splitlines()
    for line in git_out("status", "--porcelain", "--", "*.md").splitlines():
        names.append(line[3:].split(" -> ")[-1])
    root = git_out("rev-parse", "--show-toplevel")
    return sorted({n for n in names if n and is_target(n) and os.path.exists(os.path.join(root, n))})


def check_pr(base: str, head: str, body_file: str | None) -> int:
    """PR에 들어갈 대상 문서(브랜치에 커밋된 내용)와 PR 본문 중 교정 기록이 없는 것을 찾는다."""
    state = load_state()
    base_ref = resolve_base(base)
    head = head.split(":", 1)[-1]   # owner:branch 형식
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", head], capture_output=True).returncode != 0:
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{head}"], capture_output=True).returncode == 0:
            head = f"origin/{head}"
        else:
            print(f"PR 브랜치({head})를 찾을 수 없어 교정 여부를 확인하지 못했다. 브랜치를 push했는지 확인한다.")
            return 1
    changed = [p for p in git_out("diff", "--name-only", "--diff-filter=AMR", f"{base_ref}...{head}", "--", "*.md").splitlines()
               if p and is_target(p)]
    missing = []
    for path in changed:
        blob = git_blob(head, path) or b""
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
        print("AI가 쓰는 글은 `/doc-write`로 쓰고, 사람이 쓴 글은 `/doc-review`로 교정한 뒤 커밋한다.")
        return 1
    print(f"교정 확인 통과({len(changed)}개 문서{', PR 본문' if body_file else ''})")
    return 0


def is_secret(path: str) -> bool:
    name = os.path.basename(path)
    if name.endswith(".example"):
        return False
    return name == ".env" or name.startswith(".env.") or name.endswith(".tfvars") \
        or name == "backend.hcl" or ".tfstate" in name


# ---------- 보낼 범위와 묶음 ----------

def changed_ranges(base: list[str] | None, cur: list[str], context: int = CONTEXT_LINES) -> list[tuple[int, int]]:
    """현재 문서에서 보낼 줄 범위(1부터, 끝 포함). 기준이 없으면 전체."""
    if not cur:
        return []
    if base is None:
        return [(1, len(cur))]
    spans = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, base, cur, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        lo, hi = (j1, j2 - 1) if j2 > j1 else (j1 - 1, j1)   # 삭제는 그 자리의 앞뒤 줄
        spans.append((max(1, lo + 1 - context), min(len(cur), hi + 1 + context)))
    merged: list[tuple[int, int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def make_batches(segments: list[tuple[str, int, int]], limit: int = BATCH_LINES) -> list[list[tuple[str, int, int]]]:
    """(이름, 시작, 끝) 조각을 limit 줄 이하 묶음으로 나눈다. 긴 조각은 자른다."""
    pieces = []
    for name, a, b in segments:
        while b - a + 1 > limit:
            pieces.append((name, a, a + limit - 1))
            a += limit
        pieces.append((name, a, b))
    batches: list[list[tuple[str, int, int]]] = []
    size = 0
    for p in pieces:
        n = p[2] - p[1] + 1
        if not batches or size + n > limit:
            batches.append([])
            size = 0
        batches[-1].append(p)
        size += n
    return batches


# ---------- 모델 호출 ----------

def load_glossary() -> list[str]:
    try:
        with open(GLOSSARY_FILE, encoding="utf-8") as fh:
            return [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def build_prompt(batch: list[tuple[str, int, int]], docs: dict[str, list[str]], glossary: list[str]) -> str:
    parts = []
    for name, a, b in batch:
        body = "".join(f"{n}|{docs[name][n - 1]}\n" for n in range(a, b + 1))
        parts.append(f'<document name="{name}" lines="{a}-{b}">\n{body}</document>\n')
    return (
        open(PROMPT_FILE, encoding="utf-8").read()
        + ("\n## 고정 표기\n다음 표기는 띄어쓰기를 포함해 바꾸지 않는다: " + ", ".join(glossary) + "\n" if glossary else "")
        + "\n도구를 쓰지 말고, 아래 문서 내용만 보고 답한다.\n"
        + "문서는 바뀐 부분과 앞뒤 몇 줄만 보낼 수 있다. 보낸 줄에 대해서만 제안하고, 제안마다 문서 이름을 `file`에 적는다.\n"
        + "응답은 다른 설명 없이 아래 JSON 스키마를 따르는 JSON 객체 하나만 출력한다.\n"
        + open(SCHEMA_FILE, encoding="utf-8").read() + "\n\n"
        + "".join(parts)
    )


def call_agy(prompt: str, model: str, timeout: int) -> dict:
    cmd = ["agy", "-p", prompt, "--model", model, "--mode", "plan", "--output-format", "json",
           "--print-timeout", f"{timeout}s"]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "seconds": round(time.time() - started)}
    seconds = round(time.time() - started)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "seconds": seconds, "error": (proc.stderr or proc.stdout)[-500:]}
    if out.get("status") != "SUCCESS":
        return {"status": "error", "seconds": seconds, "error": str(out)[-500:]}
    response = out.get("response")
    try:
        data = extract_json(response) if isinstance(response, str) else response
        suggestions = data.get("suggestions", [])
    except (json.JSONDecodeError, AttributeError, ValueError):
        return {"status": "unparsed", "seconds": seconds, "raw": str(response)[:2000]}
    return {"status": "ok", "seconds": seconds, "usage": out.get("usage", {}), "suggestions": suggestions}


def review_batch(batch, docs, glossary, model, timeout) -> dict:
    prompt = build_prompt(batch, docs, glossary)
    r = call_agy(prompt, model, timeout)
    if r["status"] != "ok":   # 일시 오류(과부하 등)는 한 번 다시 시도한다
        time.sleep(RETRY_WAIT_SECONDS)
        r = call_agy(prompt, model, timeout)
    r["batch"] = batch
    return r


def extract_json(text: str) -> dict:
    """응답에서 JSON 객체를 꺼낸다(코드 블록으로 감싸거나 앞뒤에 설명이 붙어도 처리)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON 객체가 없다")
    return json.loads(text[start:end + 1])


# ---------- 거르기 ----------

BACKTICK = re.compile(r"`[^`]*`")
LINE_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|(?:[-*+]|\d+\.)\s+(?:\[[ xX]\]\s+)?|>\s*)*")   # 들여쓰기, 제목, 목록, 체크박스, 인용


def code_block_lines(lines: list[str]) -> set[int]:
    inside, result = False, set()
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            inside = not inside
            result.add(n)
        elif inside:
            result.add(n)
    return result


def filter_reason(s: dict, lines: list[str], sent: set[int], code: set[int], glossary: list[str]) -> str | None:
    """반영하면 안 되는 제안이면 그 이유를 돌려준다."""
    try:
        ln = int(s.get("line", 0))
    except (TypeError, ValueError):
        return "not-sent-line"
    orig, sug = s.get("original", ""), s.get("suggestion", "")
    if ln not in sent or not (0 < ln <= len(lines)):
        return "not-sent-line"
    text = lines[ln - 1]
    if orig and orig not in text and orig.strip() and orig.strip() in text:
        orig = orig.strip()   # 줄 전체를 다시 쓰는 제안은 앞뒤 공백을 붙여 오기도 한다
    if not orig or orig not in text:
        return "original-not-found"
    if orig == sug:
        return "no-change"
    if "·" in sug:
        return "middle-dot"
    if ln in code:
        return "code-block"
    # 백틱 안 내용은 그대로여야 한다. 문장을 다시 쓰며 같은 식별자를 한 번 더 쓰는 것은 허용한다(집합으로 비교)
    if set(BACKTICK.findall(orig)) != set(BACKTICK.findall(sug)):
        return "backtick"
    new = text.replace(orig, sug, 1)
    if LINE_PREFIX.match(new).group(0) != LINE_PREFIX.match(text).group(0):
        return "structure"   # 목록 기호, 제목, 들여쓰기가 바뀌면 마크다운 구조가 깨진다
    if text.lstrip().startswith("|") and text.count("|") != new.count("|"):
        return "table"
    for term in glossary:
        if glossary_changed(term, text, new):
            return "glossary"
    return None


def glossary_changed(term: str, before: str, after: str) -> bool:
    """고정 표기를 다른 표기(예: 띄어쓰기)로 바꿨거나 아예 없앴으면 True. 문장을 합쳐 횟수만 줄어든 것은 허용한다."""
    loose = re.compile(r"\s*".join(map(re.escape, term)))
    variants = len(loose.findall(after)) - after.count(term)
    return variants > len(loose.findall(before)) - before.count(term) or (term in before and term not in after)


# ---------- 실행 ----------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*")
    parser.add_argument("--model", default=os.environ.get("DOC_REVIEW_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=int, default=420, help="호출 1회의 제한 시간(초)")
    parser.add_argument("--full", action="store_true", help="바뀐 부분이 아니라 문서 전체를 보낸다")
    parser.add_argument("--only", action="store_true", help="브랜치에서 바뀐 문서는 빼고 지정한 파일만 본다")
    parser.add_argument("--stdin-name", help="표준 입력으로 받은 글의 이름(PR 본문 등)")
    parser.add_argument("--verbose", action="store_true", help="걸러 낸 제안도 모두 출력")
    parser.add_argument("--mark", action="store_true", help="교정 없이 현재 내용을 교정 완료로 기록(제안 반영 후에만 쓴다)")
    parser.add_argument("--check-pr", action="store_true", help="PR에 들어갈 문서의 교정 기록 확인")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--body-file")
    args = parser.parse_args()

    if args.check_pr:
        return check_pr(args.base, args.head, args.body_file)
    if args.mark:
        entries = []
        for path in args.files:
            with open(path, "rb") as fh:
                entries.append((display_name(path), fh.read(), "reviewed", "제안 반영 후 기록"))
        record(entries)
        print(f"교정 기록: {len(entries)}개")
        return 0

    root = git_out("rev-parse", "--show-toplevel")
    files: list[str] = []
    for path in ([] if args.only else [os.path.join(root, p) for p in changed_docs(args.base)]) \
            + [os.path.abspath(p) for p in args.files]:
        if path not in files:
            files.append(path)
    if not files and not args.stdin_name:
        print(json.dumps({"status": "ok", "files": {}, "note": "교정할 문서가 없다"}, ensure_ascii=False))
        return 0

    inputs: list[tuple[str, str]] = []
    if args.stdin_name:
        inputs.append((args.stdin_name, sys.stdin.read()))
    for path in files:
        if is_secret(path):
            print(f"비밀 값 파일은 보내지 않는다: {path}", file=sys.stderr)
            return 2
        with open(path, encoding="utf-8") as fh:
            inputs.append((display_name(path), fh.read()))

    if shutil.which("agy") is None:
        record([(n, c.encode("utf-8"), "skipped", "agy 없음") for n, c in inputs])
        print(json.dumps({"status": "skipped", "reason": "agy(Antigravity CLI)를 찾을 수 없다"}, ensure_ascii=False))
        return 3

    state = load_state()
    base_ref = resolve_base(args.base)
    docs: dict[str, list[str]] = {}
    sent: dict[str, list[tuple[int, int]]] = {}
    for name, content in inputs:
        cur = content.split("\n")
        if cur and cur[-1] == "":
            cur.pop()
        docs[name] = cur
        base_text = None
        if not args.full:
            base_text = last_reviewed(name, state)
            if base_text is None and not os.path.isabs(name):
                blob = git_blob(base_ref, name)
                base_text = blob.decode("utf-8", "replace") if blob is not None else None
        base_lines = None
        if base_text is not None:
            base_lines = base_text.split("\n")
            if base_lines and base_lines[-1] == "":
                base_lines.pop()
        sent[name] = changed_ranges(base_lines, cur)

    segments = [(n, a, b) for n in docs for a, b in sent[n]]
    batches = make_batches(segments)
    glossary = load_glossary()
    print(f"교정: 문서 {len(docs)}개, 보낼 줄 {sum(b - a + 1 for _, a, b in segments)}줄, 호출 {len(batches)}회({args.model})",
          file=sys.stderr)
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda b: review_batch(b, docs, glossary, args.model, args.timeout), batches))

    usage = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    failed_docs: dict[str, str] = {}
    raw: dict[str, list[dict]] = {n: [] for n in docs}
    errors = []
    for r in results:
        for k in usage:
            usage[k] += r.get("usage", {}).get(k, 0) or 0
        names = {n for n, _, _ in r["batch"]}
        if r["status"] != "ok":
            errors.append({k: v for k, v in r.items() if k not in ("batch", "suggestions")})
            for n in names:
                failed_docs[n] = r["status"]
            continue
        for s in r["suggestions"]:
            target = s.get("file") if s.get("file") in names else (next(iter(names)) if len(names) == 1 else None)
            if target:
                raw[target].append(s)

    out = {"model": args.model, "calls": len(batches), "seconds": round(time.time() - started), "usage": usage,
           "files": {}}
    if errors:
        out["errors"] = errors
    entries = []
    for name, lines in docs.items():
        lines_sent = {n for a, b in sent[name] for n in range(a, b + 1)}
        code = code_block_lines(lines)
        kept, dropped = [], []
        for s in raw[name]:
            reason = filter_reason(s, lines, lines_sent, code, glossary)
            (dropped if reason else kept).append({**s, "filtered": reason} if reason else s)
        counts: dict[str, int] = {}
        for s in dropped:
            counts[s["filtered"]] = counts.get(s["filtered"], 0) + 1
        info = {"status": failed_docs.get(name, "ok"), "sent_lines": sent[name],
                "suggestions": sorted(kept, key=lambda s: s.get("line", 0)), "filtered": counts,
                "middle_dot_lines": [i + 1 for i, l in enumerate(lines) if "·" in l]}
        if args.verbose:
            info["filtered_detail"] = dropped
        out["files"][name] = info
        content = dict(inputs)[name].encode("utf-8")
        if name in failed_docs:
            entries.append((name, content, "skipped", f"교정 실패: {failed_docs[name]}"))
        else:
            entries.append((name, content, "reviewed", args.model))
    record(entries)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
