#!/usr/bin/env python3
"""doc-write.py의 사실 검사, 프롬프트 구성, 다시 쓰기 흐름 테스트(실제 agy는 호출하지 않는다).

    python3 scripts/ai/test_doc_write.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "doc-write.py")
spec = importlib.util.spec_from_file_location("doc_write", SCRIPT)
dw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dw)


def slurp(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class FactTokensTest(unittest.TestCase):
    def test_collectsNumbersBackticksLinksAndRefs(self):
        tokens = dw.fact_tokens("- 테스트 786개 통과(`./gradlew build`), [PR #15](https://x/pull/15), 이슈 #7, 2분 26초")
        self.assertTrue({"786", "`./gradlew build`", "https://x/pull/15", "#7", "2", "26"} <= tokens)

    def test_numbersInsideBackticksAndLinksAreNotSplit(self):
        tokens = dw.fact_tokens("`gemini-4-neon-high` 모델, [문서](docs/v2/a.md)")
        self.assertNotIn("4", tokens)
        self.assertNotIn("2", tokens)

    def test_listAndHeadingNumbersAreStructure(self):
        tokens = dw.fact_tokens("## 1. 배경\n1. 첫 단계\n10. 열 번째")
        self.assertEqual(tokens, set())

    def test_versionAndDateAreOneToken(self):
        tokens = dw.fact_tokens("8.10.4로 올렸다(2026-11-23), 10% 증가, 1%p 증가")
        self.assertTrue({"8.10.4", "2026-11-23", "10%", "1%p"} <= tokens)

    def test_memoLinesAreIgnored(self):
        self.assertEqual(dw.fact_tokens("작성 메모: 3문장 이내로"), set())

    def test_codeBlockLinesAreFacts(self):
        tokens = dw.fact_tokens("```bash\n./gradlew :apps:order-service:test\n```")
        self.assertIn("./gradlew :apps:order-service:test", tokens)


class CheckFactsTest(unittest.TestCase):
    def test_inventedNumberIsNewFact(self):
        r = dw.check_facts("호출을 83% 줄였다", "호출 18회에서 3회", [])
        self.assertEqual(r["new_facts"], ["83%"])
        self.assertEqual(r["missing_facts"], ["18", "3"])

    def test_factsFromSourcesAreAllowed(self):
        r = dw.check_facts("PR #9와 테스트 15개", "PR #9", ["재현 테스트 15개"])
        self.assertEqual(r["new_facts"], [])

    def test_identifierInMemoIsAllowedButNotRequired(self):
        brief = "작성 메모: 새 절 \"## 문서 작성(`/doc-write`) 측정\"을 추가한다.\n- 호출 5회"
        r = dw.check_facts("## 문서 작성(`/doc-write`) 측정\n호출 5회", brief, [])
        self.assertEqual(r["new_facts"], [])
        r = dw.check_facts("## 문서 작성 측정\n호출 5회", brief, [])
        self.assertEqual(r["missing_facts"], [])

    def test_changedBacktickIsNewFact(self):
        r = dw.check_facts("`doc-review.py`를 쓴다", "`scripts/ai/doc-review.py`를 쓴다", [])
        self.assertEqual(r["new_facts"], ["`doc-review.py`"])


class ProblemsTest(unittest.TestCase):
    def test_missingTemplateHeadingIsProblem(self):
        issues, _ = dw.problems("## 개요\n내용\n", "내용", [], "## 개요\n## 테스트\n")
        self.assertTrue(any("## 테스트" in i for i in issues))

    def test_middleDotIsProblem(self):
        issues, _ = dw.problems("등록·판매", "등록, 판매", [], None)
        self.assertTrue(any("가운뎃점" in i for i in issues))

    def test_cleanOutputHasNoProblem(self):
        issues, _ = dw.problems("## 개요\n테스트 3개를 추가했습니다.\n## 테스트\n", "- 테스트 3개 추가", [],
                                "## 개요\n## 테스트\n")
        self.assertEqual(issues, [])


class PromptTest(unittest.TestCase):
    def test_stripFence(self):
        self.assertEqual(dw.strip_fence("```markdown\n# 제목\n본문\n```"), "# 제목\n본문\n")
        self.assertEqual(dw.strip_fence("# 제목\n"), "# 제목\n")

    def test_writingRulesComeFromClaudeMd(self):
        rules = dw.writing_rules()
        self.assertIn("합쇼체", rules)
        self.assertNotIn("## 변경 시 주의", rules)

    def test_promptContainsBriefTemplateAndFeedback(self):
        p = dw.build_prompt("- 사실", "## 개요\n", ("docs/a.md", "원문"), [("docs/b.md", "참고")], ["가운뎃점(·)을 썼다."])
        for part in ("<brief>\n- 사실", "<template>", '<target name="docs/a.md">', '<context name="docs/b.md">',
                     "이전 결과의 문제", "## 문서 작성 규칙(CLAUDE.md)"):
            self.assertIn(part, p)


FAKE_AGY = """#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_AGY_DIR"]
n = len([f for f in os.listdir(d) if f.startswith("call")]) + 1
prompt = sys.argv[sys.argv.index("-p") + 1]
open(os.path.join(d, f"call{n}"), "w").write(prompt)
replies = json.load(open(os.path.join(d, "replies.json")))
text = replies[min(n, len(replies)) - 1]
print(json.dumps({"status": "SUCCESS", "response": text, "usage": {"input_tokens": 10}}))
"""


class MainFlowTest(unittest.TestCase):
    """임시 git 저장소에서 가짜 agy로 스크립트 전체를 실행한다(실제 교정 기록을 건드리지 않는다)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="doc-write-test-")
        self.repo = os.path.join(self.tmp, "repo")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.repo)
        os.makedirs(self.bin)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        shutil.copy(os.path.join(HERE, "..", "..", "CLAUDE.md"), os.path.join(self.repo, "CLAUDE.md"))
        with open(os.path.join(self.bin, "agy"), "w") as fh:
            fh.write(FAKE_AGY)
        os.chmod(os.path.join(self.bin, "agy"), 0o755)
        with open(os.path.join(self.repo, "brief.md"), "w") as fh:
            fh.write("- 테스트 786개 통과\n- PR #15\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, replies, *args, path_has_agy=True):
        with open(os.path.join(self.tmp, "replies.json"), "w") as fh:
            json.dump(replies, fh, ensure_ascii=False)
        env = dict(os.environ, FAKE_AGY_DIR=self.tmp,
                   PATH=(self.bin + os.pathsep if path_has_agy else "") + "/usr/bin:/bin")
        return subprocess.run([sys.executable, SCRIPT, "--brief", "brief.md", *args], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def calls(self):
        return sorted(f for f in os.listdir(self.tmp) if f.startswith("call"))

    def test_cleanOutputIsWrittenAndRecorded(self):
        p = self.run_script(["테스트 786개가 통과했습니다(PR #15).\n"], "--out", "out.md")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(slurp(os.path.join(self.repo, "out.md")), "테스트 786개가 통과했습니다(PR #15).\n")
        state = json.loads(slurp(os.path.join(self.repo, ".git", "ai-doc-review.json")))
        self.assertEqual([e["status"] for e in state.values()], ["written"])
        self.assertEqual(len(self.calls()), 1)

    def test_inventedFactTriggersOneRetryWithFeedback(self):
        p = self.run_script(["테스트 786개, 커버리지 97%(PR #15)\n", "테스트 786개가 통과했습니다(PR #15).\n"],
                            "--out", "out.md")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn("97%", slurp(os.path.join(self.tmp, "call2")))

    def test_twoFailuresAreRejectedWithoutWritingOutput(self):
        p = self.run_script(["커버리지 97%\n", "커버리지 97%\n"], "--out", "out.md")
        self.assertEqual(p.returncode, 4)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "out.md")))
        self.assertTrue(os.path.exists(os.path.join(self.repo, "out.md.rejected")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "ai-doc-review.json")))

    def test_targetIsRewrittenInPlace(self):
        with open(os.path.join(self.repo, "doc.md"), "w") as fh:
            fh.write("# 문서\n기존 테스트 781개\n")
        p = self.run_script(["# 문서\n테스트 786개가 통과했습니다(PR #15).\n"], "--target", "doc.md")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("786", slurp(os.path.join(self.repo, "doc.md")))
        self.assertIn('<target name="doc.md">', slurp(os.path.join(self.tmp, "call1")))

    def test_withoutAgyIsSkipped(self):
        p = self.run_script(["x"], "--out", "out.md", path_has_agy=False)
        self.assertEqual(p.returncode, 3)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "out.md")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
