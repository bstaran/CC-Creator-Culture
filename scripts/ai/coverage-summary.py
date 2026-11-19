#!/usr/bin/env python3
"""JaCoCo XML 리포트를 모듈별, 패키지별로 요약한다.

사용법(테스트 실행 후):
    python3 scripts/ai/coverage-summary.py            # 모듈 요약 + 커버리지 낮은 패키지 상위 15개
    python3 scripts/ai/coverage-summary.py --top 30   # 낮은 패키지 개수 조정
    python3 scripts/ai/coverage-summary.py --markdown # metrics.md에 붙일 표 형식
"""
import argparse
import glob
import os
import xml.etree.ElementTree as ET


def counters(node):
    result = {}
    for c in node.findall("counter"):
        result[c.get("type")] = (int(c.get("missed")), int(c.get("covered")))
    return result


def pct(pair):
    if not pair:
        return None
    missed, covered = pair
    total = missed + covered
    return None if total == 0 else covered * 100.0 / total


def fmt(value):
    return "-" if value is None else f"{value:.1f}%"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--min-lines", type=int, default=30, help="낮은 패키지 목록에 넣을 최소 라인 수")
    args = parser.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    reports = sorted(glob.glob(os.path.join(root, "**/build/reports/jacoco/test/jacocoTestReport.xml"), recursive=True))
    if not reports:
        print("JaCoCo 리포트가 없다. 먼저 ./gradlew test 를 실행한다.")
        return

    modules, packages = [], []
    for path in reports:
        module = os.path.relpath(path, root).split("/build/")[0]
        tree = ET.parse(path).getroot()
        c = counters(tree)
        modules.append((module, c.get("LINE"), c.get("BRANCH")))
        for pkg in tree.findall("package"):
            pc = counters(pkg)
            line = pc.get("LINE")
            if line and sum(line) >= args.min_lines:
                packages.append((pct(line), module, pkg.get("name").replace("/", "."), sum(line), pct(pc.get("BRANCH"))))

    packages.sort(key=lambda p: (p[0] if p[0] is not None else -1))

    if args.markdown:
        print("| 모듈 | 라인 | 분기 | 라인 수 |\n|---|---:|---:|---:|")
        for module, line, branch in modules:
            print(f"| `{module}` | {fmt(pct(line))} | {fmt(pct(branch))} | {sum(line) if line else 0} |")
        print(f"\n| 라인 커버리지 | 모듈 | 패키지 | 라인 수 | 분기 |\n|---:|---|---|---:|---:|")
        for line, module, name, size, branch in packages[: args.top]:
            print(f"| {fmt(line)} | `{module}` | `{name}` | {size} | {fmt(branch)} |")
        return

    print(f"{'모듈':<28}{'라인':>8}{'분기':>8}{'라인 수':>8}")
    for module, line, branch in modules:
        print(f"{module:<28}{fmt(pct(line)):>8}{fmt(pct(branch)):>8}{(sum(line) if line else 0):>8}")
    print(f"\n커버리지 낮은 패키지 (라인 {args.min_lines}줄 이상, 상위 {args.top}개)")
    for line, module, name, size, branch in packages[: args.top]:
        print(f"{fmt(line):>7}  {module:<24} {name}  ({size}줄, 분기 {fmt(branch)})")


if __name__ == "__main__":
    main()
