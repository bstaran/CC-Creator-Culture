#!/usr/bin/env python3
"""다른 모델(Antigravity CLI `agy`, Gemini)로 코드 변경을 리뷰받는다(Claude 리뷰와 별개인 2차 의견).

구독 로그인(`agy` 대화형 로그인)으로 로컬에서 실행한다. CI에서는 쓰지 않는다(Antigravity는 구독을 CI에서 쓰는
공식 방법이 없다). 모델은 읽기만 하고, PR에 코멘트를 올리는 일은 이 스크립트가 한다.

사용법:
    python3 scripts/ai/code-review.py                          # 현재 브랜치(HEAD)와 origin/dev의 차이
    python3 scripts/ai/code-review.py --pr 12                  # PR head를 임시 worktree로 받아 리뷰
    python3 scripts/ai/code-review.py --pr 12 --out r.json     # 결과를 파일로도 저장
    python3 scripts/ai/code-review.py --post-from r.json --pr 12 [--drop 2,5]   # 저장한 결과를 PR 리뷰로 게시

방식:
    - 대상: 코드, 설정, SQL, 스크립트. 문서(`*.md`), 동결 저장소(`archunit_store`), 이벤트 스냅샷, 바이너리는 뺀다.
    - 호출: diff를 BATCH_LINES 줄 단위로 묶어 보내고, 묶음끼리는 동시에 호출한다. 모델은 작업 디렉터리의 파일을
            읽기 도구로 열어 맥락을 확인할 수 있다(plan 모드, 셸 명령은 headless에서 자동 거부).
    - 거르기: 위치가 없는 지적(파일이나 줄이 없음)은 버리고, diff 밖 위치는 본문 지적으로 돌린다. 중복을 합치고,
            심각도와 확신 순으로 MAX_FINDINGS개까지 남긴다.

종료 코드: 0 완료, 3 agy를 쓸 수 없거나 모든 호출 실패(건너뜀), 2 잘못된 입력, 1 게시 실패
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "prompts", "code-review.md")
SCHEMA_FILE = os.path.join(HERE, "prompts", "code-review.schema.json")
DEFAULT_MODEL = "gemini-4-neon-high"
DEFAULT_BASE = "dev"
RETRY_WAIT_SECONDS = 20
BATCH_LINES = 600        # 한 번 호출에 보내는 최대 diff 줄 수
BATCH_BYTES = 90_000     # 묶음 하나의 최대 바이트. 프롬프트를 `agy -p` 인자 하나로 넘기므로 Linux 인자 한도(128KiB)보다 작게 둔다
WORKERS = 3
MAX_FINDINGS = 15

EXCLUDE_SUFFIXES = (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".jar", ".lock")
EXCLUDE_PARTS = ("/archunit_store/", "/schema/events/", "gradle/wrapper/", ".ai-cache/")
SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2}
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_LABEL = {"blocker": "차단", "major": "주요", "minor": "참고"}


# ---------- diff ----------

@dataclass
class Hunk:
    header: str
    lines: list = field(default_factory=list)   # (kind, 변경 후 줄 번호 또는 None, 내용)


@dataclass
class FileDiff:
    path: str
    deleted: bool = False
    binary: bool = False
    hunks: list = field(default_factory=list)

    def commentable(self) -> set[int]:
        """GitHub 리뷰 코멘트를 달 수 있는 변경 후 줄(추가 줄과 문맥 줄)."""
        return {n for h in self.hunks for kind, n, _ in h.lines if n is not None}


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def unquote_path(path: str) -> str:
    """git이 따옴표와 8진 이스케이프로 감싼 경로(비ASCII 등)를 원래 문자열로 되돌린다."""
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        raw = path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        path = raw.encode("latin-1").decode("utf-8", "replace")
    return path


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    hunk: Hunk | None = None
    new_no = 0
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r'diff --git "?a/(.*?)"? "?b/(.*?)"?$', line)
            cur = FileDiff(path=unquote_path(f'"{m.group(2)}"') if m and '"' in line else (m.group(2) if m else line.split(" b/")[-1]))
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if hunk is None or not line[:1] in (" ", "+", "-", "\\"):
            if line.startswith("deleted file mode"):
                cur.deleted = True
            elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
                cur.binary = True
            elif line.startswith("+++ "):
                target = unquote_path(line[4:])
                if target != "/dev/null":
                    cur.path = target[2:] if target.startswith("b/") else target
            elif line.startswith("--- "):
                pass
            elif (m := HUNK_RE.match(line)):
                hunk = Hunk(header=line)
                cur.hunks.append(hunk)
                new_no = int(m.group(1))
            continue
        if line.startswith("+"):
            hunk.lines.append(("+", new_no, line[1:]))
            new_no += 1
        elif line.startswith("-"):
            hunk.lines.append(("-", None, line[1:]))
        elif line.startswith(" "):
            hunk.lines.append((" ", new_no, line[1:]))
            new_no += 1
        # "\ No newline at end of file"은 건너뛴다
    return files


def is_review_target(f: FileDiff) -> bool:
    path = "/" + f.path
    if f.deleted or f.binary or not f.hunks:
        return False
    if f.path.lower().endswith(EXCLUDE_SUFFIXES):
        return False
    return not any(part in path for part in EXCLUDE_PARTS)


def render_hunk(h: Hunk) -> list[str]:
    out = [h.header]
    for kind, n, text in h.lines:
        out.append(f"{kind}{'' if n is None else n:>5}| {text}")
    return out


def split_lines(lines: list[str], limit: int, max_bytes: int) -> list[list[str]]:
    """줄 목록을 limit 줄, max_bytes 바이트를 넘지 않는 조각으로 나눈다. 나뉜 조각 앞에는 이어지는 표시를 붙인다."""
    chunks, cur, size = [], [], 0
    for line in lines:
        n = len(line.encode("utf-8")) + 1
        if cur and (len(cur) >= limit or size + n > max_bytes):
            chunks.append(cur)
            cur, size = ["@@ (앞 조각에서 이어짐) @@"], 0
        cur.append(line[: max_bytes // 2])   # 비정상적으로 긴 한 줄(압축된 파일 등)은 자른다
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def make_batches(files: list[FileDiff], limit: int = BATCH_LINES,
                 max_bytes: int = BATCH_BYTES) -> list[list[tuple[str, list[str]]]]:
    """(파일 경로, 렌더링한 줄) 조각을 limit 줄, max_bytes 바이트 단위로 묶는다. 큰 파일은 hunk 단위로,
    큰 hunk는 줄 단위로 나눈다."""
    pieces: list[tuple[str, list[str]]] = []
    for f in files:
        chunk: list[str] = []
        for h in f.hunks:
            for rendered in split_lines(render_hunk(h), limit, max_bytes):
                if chunk and (len(chunk) + len(rendered) > limit or nbytes(chunk) + nbytes(rendered) > max_bytes):
                    pieces.append((f.path, chunk))
                    chunk = []
                chunk.extend(rendered)
        if chunk:
            pieces.append((f.path, chunk))
    batches, cur, size, used = [], [], 0, 0
    for path, lines in pieces:
        if cur and (size + len(lines) > limit or used + nbytes(lines) > max_bytes):
            batches.append(cur)
            cur, size, used = [], 0, 0
        cur.append((path, lines))
        size += len(lines)
        used += nbytes(lines)
    if cur:
        batches.append(cur)
    return batches


def nbytes(lines: list[str]) -> int:
    return sum(len(l.encode("utf-8")) + 1 for l in lines)


# ---------- git / gh ----------

def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 실패: {proc.stderr.strip()[-500:]}")
    return proc.stdout


def resolve_base(base: str) -> str:
    probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"origin/{base}"], capture_output=True)
    return f"origin/{base}" if probe.returncode == 0 else base


def origin_repo() -> str:
    url = run(["git", "remote", "get-url", "origin"]).strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise RuntimeError(f"origin이 GitHub 저장소가 아니다: {url}. --repo로 지정한다.")
    return m.group(1)


# ---------- 모델 호출 ----------

def build_prompt(batch: list[tuple[str, list[str]]]) -> str:
    parts = [f'<diff file="{path}">\n' + "\n".join(lines) + "\n</diff>\n" for path, lines in batch]
    return (
        open(PROMPT_FILE, encoding="utf-8").read()
        + "\n이번 묶음에서 바뀐 파일: " + ", ".join(sorted({p for p, _ in batch})) + "\n"
        + "줄 형식: `+` 추가, ` ` 문맥, `-` 삭제. 숫자는 변경 후 파일의 줄 번호다.\n"
        + "응답은 다른 설명 없이 아래 JSON 스키마를 따르는 JSON 객체 하나만 출력한다.\n"
        + open(SCHEMA_FILE, encoding="utf-8").read() + "\n\n"
        + "".join(parts)
    )


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("JSON 객체가 없다")
    return json.loads(text[start:end + 1])


def call_agy(prompt: str, model: str, timeout: int, cwd: str) -> dict:
    cmd = ["agy", "-p", prompt, "--model", model, "--mode", "plan", "--output-format", "json",
           "--print-timeout", f"{timeout}s"]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "seconds": round(time.time() - started)}
    except OSError as e:   # 인자가 너무 긴 경우(E2BIG) 등. 이 묶음만 실패로 두고 나머지는 계속한다
        return {"status": "error", "seconds": round(time.time() - started), "error": str(e)[:300]}
    seconds = round(time.time() - started)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "seconds": seconds, "error": (proc.stderr or proc.stdout)[-500:]}
    if not isinstance(out, dict) or out.get("status") != "SUCCESS":
        return {"status": "error", "seconds": seconds, "error": str(out)[-500:]}
    return parse_response(out.get("response"), out.get("usage"), seconds)


def parse_response(response, usage, seconds: int = 0) -> dict:
    """모델 응답에서 지적 목록을 꺼낸다. 형식이 어긋나면 unparsed로 돌려준다."""
    try:
        data = extract_json(response) if isinstance(response, str) else response
    except (json.JSONDecodeError, ValueError):
        data = None
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        return {"status": "unparsed", "seconds": seconds, "raw": str(response)[:2000]}
    summary = data.get("summary")
    return {"status": "ok", "seconds": seconds, "usage": usage if isinstance(usage, dict) else {},
            "findings": [f for f in findings if isinstance(f, dict)],
            "summary": summary if isinstance(summary, str) else ""}


def review_batch(batch, model, timeout, cwd) -> dict:
    prompt = build_prompt(batch)
    r = call_agy(prompt, model, timeout, cwd)
    if r["status"] != "ok":   # 일시 오류(과부하 등)는 한 번 다시 시도한다
        time.sleep(RETRY_WAIT_SECONDS)
        r = call_agy(prompt, model, timeout, cwd)
    r["files"] = sorted({p for p, _ in batch})
    return r


# ---------- 거르기 ----------

def normalize_path(path: str, root: str) -> str:
    path = (path or "").strip().strip("`")
    for prefix in ("file://", root.rstrip("/") + "/", "./", "a/", "b/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    return path.split("#")[0]


def clean_text(value) -> str:
    return str(value or "").replace("·", ", ").strip()


def classify(f: dict, diffs: dict[str, FileDiff], root: str) -> tuple[str, dict | None]:
    """지적 하나를 (위치 종류, 정리한 지적)으로 바꾼다. 위치 종류: inline, body, bad-location."""
    path = normalize_path(f.get("file", ""), root)
    try:
        line = int(f.get("line"))
    except (TypeError, ValueError):
        return "bad-location", None
    severity = f.get("severity") if f.get("severity") in SEVERITY_ORDER else "minor"
    confidence = f.get("confidence") if f.get("confidence") in CONFIDENCE_ORDER else "low"
    item = {
        "file": path, "line": line, "severity": severity, "confidence": confidence,
        "category": clean_text(f.get("category")) or "other", "title": clean_text(f.get("title")),
        "reason": clean_text(f.get("reason")), "suggestion": clean_text(f.get("suggestion")),
        "evidence": [clean_text(e) for e in f.get("evidence")][:5] if isinstance(f.get("evidence"), list) else [],
    }
    if not item["title"]:
        return "bad-location", None
    if path in diffs and line in diffs[path].commentable():
        return "inline", item
    real_root = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root, path))
    if os.path.isabs(path) or os.path.commonpath([real_root, full]) != real_root:
        return "bad-location", None   # 저장소 밖 파일은 열지 않는다
    if os.path.isfile(full):
        with open(full, encoding="utf-8", errors="replace") as fh:
            count = sum(1 for _ in fh)
        if 1 <= line <= count:
            return "body", item
    return "bad-location", None


def select(raw: list[dict], diffs: dict[str, FileDiff], root: str, limit: int = MAX_FINDINGS):
    kept, filtered, seen = [], {}, set()
    for f in raw:
        kind, item = classify(f, diffs, root)
        if item is None:
            filtered[kind] = filtered.get(kind, 0) + 1
            continue
        key = (item["file"], item["line"], item["title"])
        if key in seen:
            filtered["duplicate"] = filtered.get("duplicate", 0) + 1
            continue
        seen.add(key)
        item["inline"] = kind == "inline"
        kept.append(item)
    kept.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], CONFIDENCE_ORDER[i["confidence"]], i["file"], i["line"]))
    if len(kept) > limit:
        filtered["over-limit"] = len(kept) - limit
        kept = kept[:limit]
    for n, item in enumerate(kept, 1):
        item["id"] = n
    return kept, filtered


# ---------- 게시 ----------

def comment_body(item: dict) -> str:
    body = (f"**[{SEVERITY_LABEL[item['severity']]}] {item['title']}** "
            f"(`{item['category']}`, 확신 {item['confidence']})\n\n{item['reason']}\n\n**제안**: {item['suggestion']}")
    if item.get("evidence"):
        body += "\n\n근거: " + ", ".join(f"`{e}`" for e in item["evidence"])
    return body


def review_payload(result: dict, drop: set[int], inline: bool = True) -> dict:
    items = [i for i in result["findings"] if i["id"] not in drop]
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITY_ORDER}
    lines = [
        f"### Gemini 코드 리뷰(`{result['model']}`)",
        "다른 모델(Antigravity CLI)의 2차 의견이다. Claude 리뷰와 따로 만들었고, 반영 여부는 작성자가 판단한다.",
        "",
        f"지적 {len(items)}건(차단 {counts['blocker']}, 주요 {counts['major']}, 참고 {counts['minor']}). "
        f"리뷰한 파일 {len(result['files'])}개.",
    ]
    if result.get("summaries"):
        lines += ["", "요약: " + " ".join(result["summaries"])]
    failed = sorted({f for e in result.get("errors", []) for f in e.get("files", [])})
    if failed:
        lines += ["", f"**일부 묶음이 실패해 다음 파일은 리뷰하지 못했다**: " + ", ".join(f"`{f}`" for f in failed)]
    outside = [i for i in items if not (inline and i["inline"])]
    if outside:
        lines += ["", "#### 줄에 달지 못한 지적" if inline else "#### 지적"]
        for i in outside:
            lines.append(f"- `{i['file']}:{i['line']}` " + comment_body(i).replace("\n\n", " "))
    payload = {"commit_id": result["head"], "event": "COMMENT", "body": "\n".join(lines)}
    if inline:
        payload["comments"] = [{"path": i["file"], "line": i["line"], "side": "RIGHT", "body": comment_body(i)}
                               for i in items if i["inline"]]
    return payload


def post_review(result: dict, repo: str, pr: int, drop: set[int]) -> int:
    if result.get("status") not in ("ok", "partial"):
        print(f"리뷰가 끝나지 않은 결과(status={result.get('status')})는 게시하지 않는다.", file=sys.stderr)
        return 1
    head = run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "headRefOid", "-q", ".headRefOid"]).strip()
    if head != result["head"]:
        print(f"PR head({head[:7]})가 리뷰한 커밋({result['head'][:7]})과 다르다. 다시 리뷰한 뒤 게시한다.", file=sys.stderr)
        return 1
    for inline in (True, False):   # 줄 위치가 거부되면(422) 모두 본문으로 옮겨 다시 올린다
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(review_payload(result, drop, inline), tmp, ensure_ascii=False)
        proc = subprocess.run(["gh", "api", "--method", "POST", f"repos/{repo}/pulls/{pr}/reviews", "--input", tmp.name],
                              capture_output=True, text=True)
        os.unlink(tmp.name)
        if proc.returncode == 0:
            url = json.loads(proc.stdout).get("html_url", "")
            print(f"게시 완료{'' if inline else '(줄 코멘트 없이 본문으로)'}: {url}")
            return 0
        print(f"게시 실패({'줄 코멘트' if inline else '본문'}): {proc.stderr.strip()[-300:]}", file=sys.stderr)
    return 1


# ---------- 실행 ----------

def prepare(args) -> tuple[str, str, str, str | None]:
    """(작업 디렉터리, 기준 ref, head sha, 정리할 worktree)."""
    if args.pr is None:
        root = run(["git", "rev-parse", "--show-toplevel"]).strip()
        if run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root).strip():
            print("경고: 커밋하지 않은 변경은 리뷰에 들어가지 않는다.", file=sys.stderr)
        return root, resolve_base(args.base), run(["git", "rev-parse", "HEAD"], cwd=root).strip(), None
    info = json.loads(run(["gh", "pr", "view", str(args.pr), "--repo", args.repo,
                           "--json", "headRefOid,baseRefName,state"]))
    run(["git", "fetch", "--quiet", "origin", f"pull/{args.pr}/head", info["baseRefName"]])
    head = info["headRefOid"]
    common = os.path.abspath(run(["git", "rev-parse", "--git-common-dir"]).strip())
    tree = os.path.join(common, "ai-code-review", f"pr-{args.pr}")
    if os.path.exists(tree):
        subprocess.run(["git", "worktree", "remove", "--force", tree], capture_output=True)
        shutil.rmtree(tree, ignore_errors=True)
    run(["git", "worktree", "add", "--quiet", "--detach", tree, head])
    return tree, f"origin/{info['baseRefName']}", head, tree


def main() -> int:
    parser = argparse.ArgumentParser(description="Gemini(agy) 코드 리뷰")
    parser.add_argument("--pr", type=int, help="리뷰할 PR 번호(없으면 현재 브랜치)")
    parser.add_argument("--base", default=DEFAULT_BASE, help="현재 브랜치 리뷰의 기준 브랜치")
    parser.add_argument("--repo", help="owner/repo. 기본: origin 원격")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=600, help="호출 1회의 제한 시간(초)")
    parser.add_argument("--max-findings", type=int, default=MAX_FINDINGS)
    parser.add_argument("--out", help="결과 JSON을 이 파일에도 저장")
    parser.add_argument("--post-from", help="저장한 결과 JSON을 --pr에 리뷰로 게시")
    parser.add_argument("--drop", default="", help="게시에서 뺄 지적 id(쉼표 구분)")
    args = parser.parse_args()
    if (args.pr is not None or args.post_from) and not args.repo:   # 현재 브랜치 리뷰에는 저장소 이름이 필요 없다
        try:
            args.repo = origin_repo()
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 2

    if args.post_from:
        if args.pr is None:
            print("--post-from에는 --pr이 필요하다.", file=sys.stderr)
            return 2
        with open(args.post_from, encoding="utf-8") as f:
            result = json.load(f)
        drop = {int(x) for x in args.drop.split(",") if x.strip()}
        return post_review(result, args.repo, args.pr, drop)

    if shutil.which("agy") is None:
        print(json.dumps({"status": "skipped", "reason": "agy 없음"}, ensure_ascii=False))
        return 3
    try:
        root, base, head, tree = prepare(args)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        if args.pr is None:
            diff_text = run(["git", "-c", "core.quotepath=false", "diff", "--no-color", "--no-ext-diff", "-U3", "-M",
                             f"{base}...{head}"], cwd=root)
        else:   # 머지된 PR도 같은 diff가 나오도록 GitHub가 계산한 PR diff를 쓴다
            diff_text = run(["gh", "pr", "diff", str(args.pr), "--repo", args.repo, "--color", "never"])
        diffs = [f for f in parse_diff(diff_text) if is_review_target(f)]
        result = {"mode": "pr" if args.pr else "branch", "pr": args.pr, "model": args.model, "base": base,
                  "head": head, "files": [f.path for f in diffs], "calls": 0, "seconds": 0, "usage": {},
                  "findings": [], "filtered": {}, "summaries": [], "errors": []}
        if not diffs:
            result["status"] = "ok"
            print("리뷰할 코드 변경이 없다.", file=sys.stderr)
        else:
            batches = make_batches(diffs)
            print(f"리뷰: 파일 {len(diffs)}개, diff {sum(len(l) for b in batches for _, l in b)}줄, "
                  f"호출 {len(batches)}회({args.model})", file=sys.stderr)
            started = time.time()
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                results = list(pool.map(lambda b: review_batch(b, args.model, args.timeout, root), batches))
            raw = []
            for r in results:
                result["calls"] += 1
                for k, v in r.get("usage", {}).items():
                    if isinstance(v, int):
                        result["usage"][k] = result["usage"].get(k, 0) + v
                if r["status"] == "ok":
                    raw.extend(r["findings"])
                    if r.get("summary"):
                        result["summaries"].append(clean_text(r["summary"]))
                else:
                    result["errors"].append({"files": r["files"], "status": r["status"],
                                             "detail": r.get("error") or r.get("raw", "")[:300]})
            result["seconds"] = round(time.time() - started)
            result["findings"], result["filtered"] = select(raw, {f.path: f for f in diffs}, root, args.max_findings)
            ok = sum(1 for r in results if r["status"] == "ok")
            result["status"] = "ok" if ok == len(results) else ("partial" if ok else "error")
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        print(text)
        return 3 if result["status"] == "error" else 0
    finally:
        if tree:
            subprocess.run(["git", "worktree", "remove", "--force", tree], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
