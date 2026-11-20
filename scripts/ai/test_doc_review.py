#!/usr/bin/env python3
"""doc-review.py의 범위 계산, 묶음, 거르기 규칙 테스트(agy를 호출하지 않는다).

    python3 scripts/ai/test_doc_review.py
"""
import importlib.util
import os
import sys
import unittest

spec = importlib.util.spec_from_file_location("doc_review", os.path.join(os.path.dirname(__file__), "doc-review.py"))
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)


class ChangedRangesTest(unittest.TestCase):
    def test_noBaseSendsWholeDocument(self):
        self.assertEqual(dr.changed_ranges(None, ["a", "b", "c"]), [(1, 3)])

    def test_sameContentSendsNothing(self):
        self.assertEqual(dr.changed_ranges(["a", "b"], ["a", "b"]), [])

    def test_changedLineIncludesContext(self):
        base = [str(i) for i in range(1, 21)]
        cur = list(base)
        cur[9] = "changed"                      # 10번째 줄
        self.assertEqual(dr.changed_ranges(base, cur, context=3), [(7, 13)])

    def test_nearbyChangesAreMerged(self):
        base = [str(i) for i in range(1, 31)]
        cur = list(base)
        cur[4], cur[9] = "x", "y"               # 5, 10번째 줄
        self.assertEqual(dr.changed_ranges(base, cur, context=2), [(3, 12)])

    def test_deletionSendsSurroundingLines(self):
        base = ["a", "b", "c", "d", "e"]
        cur = ["a", "b", "d", "e"]              # c 삭제
        self.assertEqual(dr.changed_ranges(base, cur, context=1), [(1, 4)])


class BatchTest(unittest.TestCase):
    def test_smallSegmentsShareBatch(self):
        batches = dr.make_batches([("a.md", 1, 50), ("b.md", 1, 60), ("c.md", 10, 20)], limit=200)
        self.assertEqual(len(batches), 1)

    def test_batchesRespectLimit(self):
        batches = dr.make_batches([("a.md", 1, 150), ("b.md", 1, 100)], limit=200)
        self.assertEqual([[s[0] for s in b] for b in batches], [["a.md"], ["b.md"]])

    def test_longSegmentIsSplit(self):
        batches = dr.make_batches([("a.md", 1, 450)], limit=200)
        self.assertEqual([b[0][1:] for b in batches], [(1, 200), (201, 400), (401, 450)])


class FilterTest(unittest.TestCase):
    LINES = ["# 제목", "요구사항을 적는다.", "`gh pr create`를 실행 한다.", "| a | b |", "```", "code line", "```",
             "교정받은 문서를 본다."]
    SENT = set(range(1, 9))
    GLOSSARY = ["요구사항", "교정받"]

    def reason(self, line, orig, sug, sent=None):
        return dr.filter_reason({"line": line, "original": orig, "suggestion": sug}, self.LINES,
                                sent or self.SENT, dr.code_block_lines(self.LINES), self.GLOSSARY)

    def test_validSuggestionPasses(self):
        self.assertIsNone(self.reason(3, "실행 한다", "실행한다"))

    def test_lineNotSentIsFiltered(self):
        self.assertEqual(self.reason(3, "실행 한다", "실행한다", sent={1}), "not-sent-line")

    def test_originalMustExistOnLine(self):
        self.assertEqual(self.reason(2, "없는 문장", "x"), "original-not-found")

    def test_middleDotIsFiltered(self):
        self.assertEqual(self.reason(2, "적는다", "적는다·쓴다"), "middle-dot")

    def test_backtickContentIsProtected(self):
        self.assertEqual(self.reason(3, "`gh pr create`를", "`gh pr new`를"), "backtick")

    def test_tableColumnsAreProtected(self):
        self.assertEqual(self.reason(4, "| a | b |", "| a, b |"), "table")

    def test_codeBlockIsProtected(self):
        self.assertEqual(self.reason(6, "code line", "code-line"), "code-block")

    def test_glossaryTermIsProtected(self):
        self.assertEqual(self.reason(2, "요구사항을", "요구 사항을"), "glossary")
        self.assertEqual(self.reason(8, "교정받은", "교정 받은"), "glossary")


class TargetTest(unittest.TestCase):
    def test_humanDocsAreTargets(self):
        self.assertTrue(dr.is_target("docs/ai-system/plan.md"))
        self.assertTrue(dr.is_target("README.md"))

    def test_aiInstructionsAreExcluded(self):
        self.assertFalse(dr.is_target(".claude/skills/spec/SKILL.md"))
        self.assertFalse(dr.is_target("CLAUDE.md"))
        self.assertFalse(dr.is_target("apps/order-service/CLAUDE.md"))
        self.assertFalse(dr.is_target("scripts/ai/prompts/doc-review.md"))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=1).result.wasSuccessful() else 1)
