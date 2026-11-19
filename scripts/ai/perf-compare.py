#!/usr/bin/env python3
"""k6 시나리오를 여러 번 실행해 중앙값을 내고, 저장된 기준선과 비교해 통과/실패를 판정한다.

판정 기준(기본): p95 응답 시간이 기준선 대비 +10%를 넘거나, 요청 실패율이 기준선 대비 1%p 넘게 오르면 실패.
결과는 이 PC의 환경에 묶인 값이라 커밋하지 않는다(.ai-cache/perf/).

사용법(로컬 스택이 떠 있어야 한다: load-test/scripts/up.sh 또는 scripts/ai/stack-up.sh):
    python3 scripts/ai/perf-compare.py baseline scenarios/product-service/search-products.js
    python3 scripts/ai/perf-compare.py compare  scenarios/product-service/search-products.js [--runs 3] [--tolerance 10]
    python3 scripts/ai/perf-compare.py show     scenarios/product-service/search-products.js

종료 코드: 0 통과(또는 기준선 저장), 1 성능 저하 판정, 2 실행 오류
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
CACHE = os.path.join(ROOT, ".ai-cache", "perf")
COMPOSE = ["docker", "compose", "-f", os.path.join(ROOT, "load-test", "docker-compose.yml")]


def run_once(scenario: str, index: int) -> dict:
    """k6를 한 번 실행하고 요약 지표를 돌려준다."""
    export_rel = f".perf-summary-{os.getpid()}-{index}.json"   # load-test/ 아래(/scripts로 마운트됨)
    export_host = os.path.join(ROOT, "load-test", export_rel)
    cmd = COMPOSE + ["run", "--rm", "-e", "TARGET=local", "k6", "run", "--quiet",
                     "--summary-export", f"/scripts/{export_rel}", scenario]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        with open(export_host, encoding="utf-8") as fh:
            summary = json.load(fh)
    except (OSError, json.JSONDecodeError):
        tail = (proc.stderr or proc.stdout)[-800:]
        raise RuntimeError(f"k6 요약을 읽지 못했다(종료 코드 {proc.returncode}).\n{tail}")
    finally:
        if os.path.exists(export_host):
            os.remove(export_host)
    m = summary.get("metrics", {})
    dur = m.get("http_req_duration", {})
    failed = m.get("http_req_failed", {})
    reqs = m.get("http_reqs", {})
    return {
        "p95_ms": dur.get("p(95)"),
        "p50_ms": dur.get("med"),
        "fail_rate": failed.get("value", failed.get("rate")),
        "rps": reqs.get("rate"),
        "k6_exit": proc.returncode,   # threshold 실패 시 0이 아닐 수 있다(지표는 그대로 쓴다)
    }


def measure(scenario: str, runs: int) -> dict:
    results = []
    for i in range(runs):
        print(f"[perf] {scenario} 실행 {i + 1}/{runs}...", file=sys.stderr)
        results.append(run_once(scenario, i))
        time.sleep(5)   # 실행 간 간격(잔여 부하 완화)
    def med(key):
        values = [r[key] for r in results if r[key] is not None]
        return statistics.median(values) if values else None
    return {"scenario": scenario, "runs": results, "median": {k: med(k) for k in ("p95_ms", "p50_ms", "fail_rate", "rps")},
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()}


def baseline_path(scenario: str) -> str:
    return os.path.join(CACHE, scenario.replace("/", "__").removesuffix(".js") + ".baseline.json")


def fmt(v, unit=""):
    return "-" if v is None else (f"{v:.1f}{unit}" if isinstance(v, float) else f"{v}{unit}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["baseline", "compare", "show"])
    parser.add_argument("scenario", help="load-test/ 기준 경로(예: scenarios/product-service/search-products.js)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--tolerance", type=float, default=10.0, help="p95 허용 증가율(%%)")
    parser.add_argument("--fail-rate-delta", type=float, default=0.01, help="실패율 허용 증가폭(0.01 = 1%%p)")
    args = parser.parse_args()

    if not os.path.exists(os.path.join(ROOT, "load-test", args.scenario)):
        print(f"[perf] 시나리오가 없다: load-test/{args.scenario}", file=sys.stderr)
        return 2
    path = baseline_path(args.scenario)

    if args.action == "show":
        if not os.path.exists(path):
            print("[perf] 기준선이 없다", file=sys.stderr)
            return 2
        print(open(path, encoding="utf-8").read())
        return 0

    try:
        current = measure(args.scenario, args.runs)
    except RuntimeError as e:
        print(f"[perf] 실행 오류: {e}", file=sys.stderr)
        return 2

    if args.action == "baseline":
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2)
        med = current["median"]
        print(f"[perf] 기준선 저장: {path}\n  p95 {fmt(med['p95_ms'], 'ms')}, p50 {fmt(med['p50_ms'], 'ms')}, "
              f"실패율 {fmt(med['fail_rate'])}, rps {fmt(med['rps'])}")
        return 0

    if not os.path.exists(path):
        print("[perf] 기준선이 없다. 변경 전 코드에서 먼저 baseline을 실행한다.", file=sys.stderr)
        return 2
    base = json.load(open(path, encoding="utf-8"))
    b, c = base["median"], current["median"]
    p95_limit = b["p95_ms"] * (1 + args.tolerance / 100) if b["p95_ms"] else None
    p95_ok = p95_limit is None or c["p95_ms"] is None or c["p95_ms"] <= p95_limit
    fail_ok = (b["fail_rate"] is None or c["fail_rate"] is None
               or c["fail_rate"] <= b["fail_rate"] + args.fail_rate_delta)
    change = (c["p95_ms"] / b["p95_ms"] - 1) * 100 if b["p95_ms"] and c["p95_ms"] else None

    print(f"| 지표(중앙값, {args.runs}회) | 기준선({base['git']}) | 현재({current['git']}) | 판정 |")
    print("|---|---:|---:|---|")
    print(f"| p95 | {fmt(b['p95_ms'], 'ms')} | {fmt(c['p95_ms'], 'ms')} ({fmt(change, '%')}) | "
          f"{'통과' if p95_ok else '실패'}(허용 +{args.tolerance:.0f}%) |")
    print(f"| p50 | {fmt(b['p50_ms'], 'ms')} | {fmt(c['p50_ms'], 'ms')} | 참고 |")
    print(f"| 실패율 | {fmt(b['fail_rate'])} | {fmt(c['fail_rate'])} | {'통과' if fail_ok else '실패'}"
          f"(허용 +{args.fail_rate_delta * 100:.0f}%p) |")
    print(f"| rps | {fmt(b['rps'])} | {fmt(c['rps'])} | 참고 |")
    print(f"개별 실행 p95: 기준선 {[fmt(r['p95_ms']) for r in base['runs']]}, 현재 {[fmt(r['p95_ms']) for r in current['runs']]}")
    return 0 if (p95_ok and fail_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
