#!/usr/bin/env python3
"""주간 지표를 모아 마크다운으로 출력한다(plan.md 11장).

    python3 scripts/ai/weekly-metrics.py                         # 어제까지 7일(양 끝 포함)
    python3 scripts/ai/weekly-metrics.py --since 2026-11-13 --until 2026-11-20
    python3 scripts/ai/weekly-metrics.py --coverage              # JaCoCo 리포트가 있으면 커버리지 포함

모으는 값:
- 기간 안에 dev로 머지된 PR: 트랙별 수, AI PR 무수정 승인, 변경 줄 수 중앙값, 리드타임(PR 생성부터 머지까지) 중앙값,
  연결 이슈의 유입 경로(개인 요청, 정기 스캔)
- 이슈: 기간 안에 새로 열린 이슈, 열린 이슈 잔량(트랙별)
- 동결된 계층 위반 수(`archunit_store`)
- 커버리지(`--coverage`, 테스트를 먼저 실행해야 한다)

"AI PR"은 `ai: generated` 라벨이 붙은 PR이다. "무수정 승인"은 PR을 연 뒤 추가 커밋이 없고 변경 요청 리뷰도 없이
머지된 경우다. 추가 커밋은 커밋 시각(committedDate)으로 판단하므로, PR을 연 뒤 rebase하면 수정으로 센다.
사용량(토큰)은 gh로 알 수 없어 넣지 않는다.
"""
import argparse
import datetime as dt
import glob
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AI_LABEL = "ai: generated"
TRACKS = [  # (라벨, 표시 이름) 표시 순서
    ("type: refactor", "리팩토링"),
    ("type: bug", "버그 수정"),
    ("type: feature", "기능 개발"),
    ("type: research", "조사/문서"),
    ("type: infra", "인프라/배포"),
    ("type: perf", "성능"),
    ("area: ai-system", "AI 체계"),
]
UNCLASSIFIED = "미분류"
SOURCES = [("source: ad-hoc", "개인 요청"), ("source: scan", "정기 스캔")]
SERVICES = ["user-service", "product-service", "order-service"]


# ---------- 순수 함수(테스트 대상) ----------

def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def track_of(labels: list[str]) -> str:
    for label, name in TRACKS:
        if label in labels:
            return name
    return UNCLASSIFIED


def source_of(labels: list[str]) -> str | None:
    for label, name in SOURCES:
        if label in labels:
            return name
    return None


def commits_after_open(pr: dict) -> int:
    opened = parse_time(pr["createdAt"])
    return sum(1 for c in pr.get("commits", []) if parse_time(c["committedDate"]) > opened)


def changes_requested(pr: dict) -> int:
    return sum(1 for r in pr.get("reviews", []) if r.get("state") == "CHANGES_REQUESTED")


def is_unmodified(pr: dict) -> bool:
    return commits_after_open(pr) == 0 and changes_requested(pr) == 0


def lead_hours(pr: dict) -> float:
    return (parse_time(pr["mergedAt"]) - parse_time(pr["createdAt"])).total_seconds() / 3600


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def fmt_hours(hours: float | None) -> str:
    if hours is None:
        return "-"
    if hours < 48:
        return f"{hours:.1f}시간"
    return f"{hours / 24:.1f}일"


def fmt_num(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def frozen_violations(store_dir: str) -> tuple[int, int]:
    """동결 저장소의 (위반 클래스 수, 위반 의존 수). 내부 클래스는 따로 센다(metrics.md 기준선과 같은 방식)."""
    classes, lines = set(), 0
    for path in glob.glob(os.path.join(store_dir, "*-*")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines += 1
                m = re.match(r"(\w+) <([^>(]+)", line)
                if not m:
                    continue
                kind, name = m.group(1), m.group(2)
                classes.add(name if kind == "Class" else name.rsplit(".", 1)[0])
    return len(classes), lines


def summarize_prs(prs: list[dict], issue_labels: dict[int, list[str]]) -> list[dict]:
    """트랙별 요약 행. 표시 순서는 TRACKS, 미분류는 마지막."""
    order = [name for _, name in TRACKS] + [UNCLASSIFIED]
    rows = {}
    for pr in prs:
        labels = [l["name"] for l in pr.get("labels", [])]
        row = rows.setdefault(track_of(labels), {"prs": 0, "ai": 0, "ai_unmodified": 0, "lines": [], "hours": [],
                                                 "sources": {}})
        row["prs"] += 1
        if AI_LABEL in labels:
            row["ai"] += 1
            row["ai_unmodified"] += is_unmodified(pr)
        row["lines"].append(pr["additions"] + pr["deletions"])
        row["hours"].append(lead_hours(pr))
        linked = [n["number"] for n in pr.get("closingIssuesReferences", [])]
        source = next((s for n in linked if (s := source_of(issue_labels.get(n, [])))), None)
        key = source or ("이슈 연결" if linked else "이슈 없음")
        row["sources"][key] = row["sources"].get(key, 0) + 1
    return [dict(track=name, **rows[name]) for name in order if name in rows]


# ---------- 수집 ----------

def gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        raise SystemExit(f"gh 실행 실패: gh {' '.join(args)}\n{out.stderr.strip()}")
    return json.loads(out.stdout or "null")


def origin_repo() -> str:
    url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    return re.sub(r"(git@github\.com:|https://github\.com/)", "", url).removesuffix(".git")


def fetch(repo: str, base: str, since: str, until: str):
    period = f"{since}..{until}"
    prs = gh_json(["pr", "list", "--repo", repo, "--state", "merged", "--base", base, "--limit", "200",
                   "--search", f"merged:{period}",
                   "--json", "number,title,url,labels,additions,deletions,createdAt,mergedAt,closingIssuesReferences"])
    for pr in prs:  # 커밋과 리뷰는 목록 조회에 넣으면 GraphQL 노드 한도를 넘어서 PR마다 따로 조회한다
        pr.update(gh_json(["pr", "view", str(pr["number"]), "--repo", repo, "--json", "commits,reviews"]))
    opened = gh_json(["issue", "list", "--repo", repo, "--state", "all", "--limit", "200",
                      "--search", f"created:{period}", "--json", "number,title,labels,state"])
    backlog = gh_json(["issue", "list", "--repo", repo, "--state", "open", "--limit", "500",
                       "--json", "number,labels"])
    linked = {n["number"] for pr in prs for n in pr.get("closingIssuesReferences", [])}
    known = {i["number"]: [l["name"] for l in i["labels"]] for i in opened + backlog}
    for number in sorted(linked - known.keys()):
        issue = gh_json(["issue", "view", str(number), "--repo", repo, "--json", "labels"])
        known[number] = [l["name"] for l in issue["labels"]]
    return prs, opened, backlog, known


def coverage_rows() -> list[tuple[str, str, str, int]]:
    spec = importlib.util.spec_from_file_location("coverage_summary", os.path.join(ROOT, "scripts/ai/coverage-summary.py"))
    cov = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cov)
    import xml.etree.ElementTree as ET
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "**/build/reports/jacoco/test/jacocoTestReport.xml"), recursive=True)):
        module = os.path.relpath(path, ROOT).split("/build/")[0]
        c = cov.counters(ET.parse(path).getroot())
        line = c.get("LINE")
        rows.append((module, cov.fmt(cov.pct(line)), cov.fmt(cov.pct(c.get("BRANCH"))), sum(line) if line else 0))
    return rows


# ---------- 출력 ----------

def render(since: str, until: str, prs, opened, backlog, issue_labels, with_coverage: bool) -> str:
    out = [f"## 주간 지표({since} ~ {until})", ""]

    out += ["### 머지된 PR(트랙별)", ""]
    rows = summarize_prs(prs, issue_labels)
    if rows:
        out += ["| 트랙 | PR | AI PR | AI 무수정 승인 | 변경 줄 중앙값 | 리드타임 중앙값 | 유입 경로 |",
                "|---|---:|---:|---:|---:|---:|---|"]
        for r in rows:
            unmodified = f"{r['ai_unmodified']}/{r['ai']}" if r["ai"] else "-"
            sources = ", ".join(f"{k} {v}" for k, v in sorted(r["sources"].items()))
            out.append(f"| {r['track']} | {r['prs']} | {r['ai']} | {unmodified} | {fmt_num(median(r['lines']))} "
                       f"| {fmt_hours(median(r['hours']))} | {sources} |")
        all_lines = [p["additions"] + p["deletions"] for p in prs]
        out += ["", f"전체 {len(prs)}건, 변경 줄 중앙값 {fmt_num(median(all_lines))}."]
        out += ["", "| PR | 트랙 | AI | 변경 줄 | 리드타임 | PR 생성 후 커밋 | 변경 요청 |",
                "|---|---|:-:|---:|---:|---:|---:|"]
        for p in sorted(prs, key=lambda p: p["number"]):
            labels = [l["name"] for l in p["labels"]]
            out.append(f"| #{p['number']} {p['title']} | {track_of(labels)} | {'O' if AI_LABEL in labels else ''} "
                       f"| {p['additions'] + p['deletions']} | {fmt_hours(lead_hours(p))} "
                       f"| {commits_after_open(p)} | {changes_requested(p)} |")
    else:
        out.append("기간 안에 머지된 PR이 없다.")

    out += ["", "### 이슈", ""]
    out += ["| 트랙 | 새로 열림 | 그중 정기 스캔 | 열린 이슈 |", "|---|---:|---:|---:|"]
    names = [name for _, name in TRACKS if name != "AI 체계"] + [UNCLASSIFIED]
    for name in names:
        new = [i for i in opened if track_of([l["name"] for l in i["labels"]]) == name]
        scan = [i for i in new if source_of([l["name"] for l in i["labels"]]) == "정기 스캔"]
        still = [i for i in backlog if track_of([l["name"] for l in i["labels"]]) == name]
        if new or still:
            out.append(f"| {name} | {len(new)} | {len(scan)} | {len(still)} |")
    approved = sum(1 for i in backlog if "spec: approved" in [l["name"] for l in i["labels"]])
    out += ["", f"승인된 스펙 중 열린 이슈: {approved}건."]

    out += ["", "### 동결된 계층 위반", "", "| 서비스 | 클래스 | 의존 |", "|---|---:|---:|"]
    total_c = total_d = 0
    for service in SERVICES:
        c, d = frozen_violations(os.path.join(ROOT, "apps", service, "src/test/resources/archunit_store"))
        total_c, total_d = total_c + c, total_d + d
        out.append(f"| `{service}` | {c} | {d} |")
    out.append(f"| **합계** | **{total_c}** | **{total_d}** |")

    if with_coverage:
        out += ["", "### 커버리지", ""]
        rows = coverage_rows()
        if rows:
            out += ["| 모듈 | 라인 | 분기 | 라인 수 |", "|---|---:|---:|---:|"]
            out += [f"| `{m}` | {l} | {b} | {n} |" for m, l, b, n in rows]
        else:
            out.append("JaCoCo 리포트가 없다(테스트를 먼저 실행한다).")
    return "\n".join(out) + "\n"


def main() -> int:
    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    parser = argparse.ArgumentParser(description="주간 지표 수집")
    parser.add_argument("--since", help="시작일(YYYY-MM-DD, 포함). 기본: 종료일 6일 전(7일 기간)")
    parser.add_argument("--until", help="종료일(YYYY-MM-DD, 포함). 기본: 어제(UTC)")
    parser.add_argument("--repo", help="owner/repo. 기본: origin 원격")
    parser.add_argument("--base", default="dev")
    parser.add_argument("--coverage", action="store_true", help="JaCoCo 리포트로 커버리지 표 추가")
    args = parser.parse_args()

    try:
        until = dt.date.fromisoformat(args.until) if args.until else yesterday
        since = dt.date.fromisoformat(args.since) if args.since else until - dt.timedelta(days=6)
    except ValueError as e:
        print(f"날짜 형식 오류: {e}", file=sys.stderr)
        return 2
    if since > until:
        print(f"시작일이 종료일보다 늦다: {since} > {until}", file=sys.stderr)
        return 2
    repo = args.repo or origin_repo()
    prs, opened, backlog, issue_labels = fetch(repo, args.base, since.isoformat(), until.isoformat())
    print(render(since.isoformat(), until.isoformat(), prs, opened, backlog, issue_labels, args.coverage), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
