#!/usr/bin/env python3
"""사람이 읽는 글을 다른 모델(Antigravity CLI `agy`, Gemini)이 쓰게 한다.

역할 분담:
    - Claude: 사실 초안(brief)을 만든다. 바뀐 것, 이유, 근거(실행한 명령과 결과 수치, 경로, 링크)를 다듬지 않은 목록으로 적는다.
    - Gemini: 사실 초안과 `CLAUDE.md`의 "문서 작성" 규칙, 양식(PR 템플릿 등), 기존 문서를 받아 최종 글을 쓴다.
    - 이 스크립트: 결과물에 초안에 없던 사실(숫자, 백틱 안 내용, 링크, `#번호`)이 생겼는지 검사한다.
      어긋나면 이유를 붙여 한 번 다시 쓰게 하고, 그래도 어긋나면 결과물을 쓰지 않고 `.rejected` 파일로 남긴다.

사용법:
    # 새 글(PR 본문 등): 양식을 지정한다
    python3 scripts/ai/doc-write.py --brief brief.md --template .github/pull_request_template.md --out .ai-cache/pr/x.md
    # 기존 문서 고치기: 초안에 바꿀 내용을 적고, 결과는 그 문서에 바로 쓴다
    python3 scripts/ai/doc-write.py --brief brief.md --target docs/ai-system/guide.md
    # 참고 문서(용어, 문체를 맞출 글)를 함께 넘긴다. 참고 문서의 사실도 결과물에 쓸 수 있다
    python3 scripts/ai/doc-write.py --brief brief.md --target docs/x.md --context docs/ai-system/README.md
    # agy를 쓸 수 없어 Claude가 직접 쓴 경우(CI 등)
    python3 scripts/ai/doc-write.py --mark-skipped <파일 ...>

사실 초안에서 `작성 메모:`로 시작하는 줄은 Gemini에게 주는 지시다. 본문에 옮기지 않으며 빠짐 검사에서도 제외하지만,
메모에 적은 제목이나 식별자를 결과물에 쓰는 것은 허용한다.

기록: 완료한 글은 `doc-review.py`와 같은 저장소에 "written"으로 기록한다. PR 생성 hook은 이 기록도 인정한다.
종료 코드: 0 완료, 2 잘못된 입력, 3 agy를 쓸 수 없어 건너뜀, 4 사실 검사 실패(결과물은 <출력>.rejected)
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "prompts", "doc-write.md")
DEFAULT_MODEL = "gemini-4-neon-medium"
MEMO_PREFIX = "작성 메모:"

_spec = importlib.util.spec_from_file_location("doc_review", os.path.join(HERE, "doc-review.py"))
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)


# ---------- 사실 토큰 ----------

LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
BARE_URL = re.compile(r"(?<!\()https?://[^\s)>\]]+")
ISSUE_REF = re.compile(r"(?<![\w/])#\d+")
NUMBER = re.compile(r"(?<![\w.#])\d+(?:[.,:/-]\d+)*(?:%p|%)?")
LIST_NUMBER = re.compile(r"^\d+\.\s+")


def fact_tokens(text: str, include_memo: bool = False) -> set[str]:
    """글에서 사실로 볼 토큰(백틱 안 내용, 링크 주소, `#번호`, 숫자)을 모은다.

    목록과 제목의 번호(`1. `)는 구조라서 뺀다. 코드 블록 안의 줄은 통째로 사실로 본다.
    `작성 메모:` 줄은 include_memo일 때만 본다(메모에 적은 제목, 식별자는 써도 되지만 빠짐 검사 대상은 아니다).
    """
    tokens: set[str] = set()
    in_code = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            if line.strip():
                tokens.add(line.strip())
            continue
        if line.startswith(MEMO_PREFIX):
            if not include_memo:
                continue
            line = line[len(MEMO_PREFIX):]
        rest = dr.LINE_PREFIX.sub("", line, count=1)
        rest = LIST_NUMBER.sub("", rest)
        for span in dr.BACKTICK.findall(rest):
            tokens.add(span)
        rest = dr.BACKTICK.sub(" ", rest)
        for url in LINK_TARGET.findall(rest) + BARE_URL.findall(rest):
            tokens.add(url)
        rest = BARE_URL.sub(" ", LINK_TARGET.sub(" ", rest))
        tokens.update(ISSUE_REF.findall(rest))
        rest = ISSUE_REF.sub(" ", rest)
        tokens.update(NUMBER.findall(rest))
    return tokens


def check_facts(output: str, brief: str, sources: list[str]) -> dict:
    """새로 생긴 사실(실패 사유)과 빠진 사실(경고)을 돌려준다."""
    allowed = fact_tokens(brief, include_memo=True)
    for s in sources:
        allowed |= fact_tokens(s)
    out = fact_tokens(output)
    return {
        "new_facts": sorted(out - allowed),
        "missing_facts": sorted(fact_tokens(brief) - out),
    }


def template_headings(template: str) -> list[str]:
    return [l.strip() for l in template.split("\n") if re.match(r"^#{1,6}\s", l)]


def problems(output: str, brief: str, sources: list[str], template: str | None) -> tuple[list[str], dict]:
    facts = check_facts(output, brief, sources)
    issues = []
    if facts["new_facts"]:
        issues.append("사실 초안과 참고 문서에 없는 사실이 들어갔다: " + ", ".join(facts["new_facts"]))
    if "·" in output:
        issues.append("가운뎃점(·)을 썼다.")
    if template:
        out_lines = {l.strip() for l in output.split("\n")}
        lost = [h for h in template_headings(template) if h not in out_lines]
        if lost:
            issues.append("양식의 제목이 빠졌다: " + ", ".join(lost))
    return issues, facts


# ---------- 프롬프트와 호출 ----------

def writing_rules() -> str:
    """`CLAUDE.md`의 "문서 작성" 절을 그대로 가져온다(규칙을 한 곳에서 관리한다)."""
    root = dr.git_out("rev-parse", "--show-toplevel")
    try:
        with open(os.path.join(root, "CLAUDE.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    m = re.search(r"^## 문서 작성\n(.*?)(?=^## )", text, re.DOTALL | re.MULTILINE)
    return m.group(1).strip() if m else ""


def build_prompt(brief: str, template: str | None, target: tuple[str, str] | None,
                 contexts: list[tuple[str, str]], feedback: list[str]) -> str:
    glossary = dr.load_glossary()
    with open(PROMPT_FILE, encoding="utf-8") as fh:
        instructions = fh.read()
    parts = [instructions,
             "\n## 문서 작성 규칙(CLAUDE.md)\n" + writing_rules() + "\n"]
    if glossary:
        parts.append("\n## 고정 표기\n다음 표기는 띄어쓰기를 포함해 바꾸지 않는다: " + ", ".join(glossary) + "\n")
    if feedback:
        parts.append("\n## 이전 결과의 문제(이번에는 반드시 고친다)\n" + "\n".join(f"- {f}" for f in feedback) + "\n")
    parts.append(f"\n<brief>\n{brief}\n</brief>\n")
    if template:
        parts.append(f"\n<template>\n{template}\n</template>\n")
    if target:
        parts.append(f'\n<target name="{target[0]}">\n{target[1]}\n</target>\n')
    for name, text in contexts:
        parts.append(f'\n<context name="{name}">\n{text}\n</context>\n')
    return "".join(parts)


def call_agy(prompt: str, model: str, timeout: int) -> dict:
    cmd = ["agy", "-p", prompt, "--model", model, "--mode", "plan", "--output-format", "json",
           "--print-timeout", f"{timeout}s"]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "seconds": round(time.time() - started)}
    except OSError as e:   # 프롬프트가 너무 길면 E2BIG
        return {"status": "error", "seconds": 0, "error": str(e)}
    seconds = round(time.time() - started)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "seconds": seconds, "error": (proc.stderr or proc.stdout)[-500:]}
    if out.get("status") != "SUCCESS" or not isinstance(out.get("response"), str):
        return {"status": "error", "seconds": seconds, "error": str(out)[-500:]}
    return {"status": "ok", "seconds": seconds, "usage": out.get("usage", {}), "text": strip_fence(out["response"])}


def strip_fence(text: str) -> str:
    """모델이 결과를 코드 블록으로 감싸 보내면 벗긴다."""
    t = text.strip()
    m = re.match(r"^```(?:markdown|md)?\n(.*)\n```$", t, re.DOTALL)
    return (m.group(1) if m else t).strip() + "\n"


# ---------- 실행 ----------

def read(path: str) -> str:
    if dr.is_secret(path):
        print(f"시크릿 파일은 보내지 않는다: {path}", file=sys.stderr)
        sys.exit(2)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", help="사실 초안 파일")
    parser.add_argument("--template", help="양식 파일(PR 템플릿 등). 제목 구조를 유지한다")
    parser.add_argument("--target", help="고칠 기존 문서. --out이 없으면 결과를 이 파일에 쓴다")
    parser.add_argument("--context", action="append", default=[], help="문체, 용어를 맞출 참고 문서(여러 번 지정 가능)")
    parser.add_argument("--out", help="결과 파일")
    parser.add_argument("--model", default=os.environ.get("DOC_WRITE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=int, default=420, help="호출 1회의 제한 시간(초)")
    parser.add_argument("--mark-skipped", nargs="+", metavar="FILE", help="agy 없이 Claude가 쓴 글을 '건너뜀'으로 기록")
    args = parser.parse_args()

    if args.mark_skipped:
        entries = []
        for p in args.mark_skipped:
            with open(p, "rb") as fh:
                entries.append((dr.display_name(p), fh.read(), "skipped", "agy 없음, Claude 작성"))
        dr.record(entries)
        print(f"건너뜀 기록: {len(args.mark_skipped)}개")
        return 0
    if not args.brief or not (args.out or args.target):
        print("--brief와 --out(또는 --target)이 필요하다", file=sys.stderr)
        return 2
    out_path = args.out or args.target

    brief = read(args.brief)
    template = read(args.template) if args.template else None
    target = (dr.display_name(args.target), read(args.target)) if args.target else None
    contexts = [(dr.display_name(p), read(p)) for p in args.context]
    sources = [s for s in [template, target[1] if target else None] if s] + [t for _, t in contexts]

    if shutil.which("agy") is None:
        print(json.dumps({"status": "skipped", "reason": "agy(Antigravity CLI)를 찾을 수 없다. Claude가 직접 쓰고 "
                          "--mark-skipped로 기록한다"}, ensure_ascii=False))
        return 3

    started = time.time()
    usage = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    feedback: list[str] = []
    attempts = []
    result = None
    for attempt in (1, 2):   # 사실 검사에 걸리면 이유를 붙여 한 번만 다시 쓰게 한다
        r = call_agy(build_prompt(brief, template, target, contexts, feedback), args.model, args.timeout)
        for k in usage:
            usage[k] += (r.get("usage") or {}).get(k, 0) or 0
        if r["status"] != "ok":
            attempts.append({"attempt": attempt, "status": r["status"], "error": r.get("error", "")[:300]})
            continue
        issues, facts = problems(r["text"], brief, sources, template)
        attempts.append({"attempt": attempt, "status": "ok" if not issues else "rejected", "issues": issues})
        result = (r["text"], issues, facts)
        if not issues:
            break
        feedback = issues

    summary = {"model": args.model, "seconds": round(time.time() - started), "usage": usage, "attempts": attempts}
    if result is None:
        summary["status"] = "error"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 3
    text, issues, facts = result
    summary["missing_facts"] = facts["missing_facts"]
    if issues:
        with open(out_path + ".rejected", "w", encoding="utf-8") as fh:
            fh.write(text)
        summary.update(status="rejected", issues=issues, rejected_file=out_path + ".rejected")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 4
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    dr.record([(dr.display_name(out_path), text.encode("utf-8"), "written", args.model)])
    summary.update(status="ok", out=out_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
