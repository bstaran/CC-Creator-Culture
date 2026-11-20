#!/usr/bin/env python3
"""code-review.py 단위 테스트. 스크립트를 고치면 실행한다.

    python3 scripts/ai/test_code_review.py
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("code_review", os.path.join(HERE, "code-review.py"))
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

DIFF = """diff --git a/apps/x/Foo.java b/apps/x/Foo.java
index 111..222 100644
--- a/apps/x/Foo.java
+++ b/apps/x/Foo.java
@@ -10,4 +10,5 @@ class Foo {
     int a;
-    int b;
+    long b;
+    long c;
     int d;
--- e;
@@ -40,2 +41,2 @@ class Foo {
-    void old() {}
+    void neu() {}
     }
\\ No newline at end of file
diff --git a/docs/readme.md b/docs/readme.md
index 1..2 100644
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old
+new
diff --git a/apps/x/Gone.java b/apps/x/Gone.java
deleted file mode 100644
index 3..0
--- a/apps/x/Gone.java
+++ /dev/null
@@ -1,2 +0,0 @@
-class Gone {
-}
diff --git a/apps/x/New.java b/apps/x/New.java
new file mode 100644
index 0..4
--- /dev/null
+++ b/apps/x/New.java
@@ -0,0 +1,2 @@
+class New {
+}
diff --git a/img/logo.png b/img/logo.png
Binary files a/img/logo.png and b/img/logo.png differ
"""


class ParseDiffTest(unittest.TestCase):
    def setUp(self):
        self.files = {f.path: f for f in cr.parse_diff(DIFF)}

    def test_parsesNewSideLineNumbers(self):
        foo = self.files["apps/x/Foo.java"]
        self.assertEqual(len(foo.hunks), 2)
        self.assertEqual(foo.hunks[0].lines[:4], [(" ", 10, "    int a;"), ("-", None, "    int b;"),
                                                  ("+", 11, "    long b;"), ("+", 12, "    long c;")])
        self.assertEqual(foo.commentable(), {10, 11, 12, 13, 41, 42})

    def test_deletedLineStartingWithDashesStaysInHunk(self):
        foo = self.files["apps/x/Foo.java"]
        self.assertIn(("-", None, "-- e;"), foo.hunks[0].lines)

    def test_marksDeletedNewAndBinaryFiles(self):
        self.assertTrue(self.files["apps/x/Gone.java"].deleted)
        self.assertEqual(self.files["apps/x/New.java"].commentable(), {1, 2})
        self.assertTrue(self.files["img/logo.png"].binary)

    def test_reviewTargetsSkipDocsDeletedAndBinary(self):
        targets = [p for p, f in self.files.items() if cr.is_review_target(f)]
        self.assertEqual(sorted(targets), ["apps/x/Foo.java", "apps/x/New.java"])

    def test_excludesFrozenStoreAndSnapshots(self):
        for path in ["apps/a/src/test/resources/archunit_store/abc-1", "libs/common/src/test/resources/schema/events/E.json"]:
            f = cr.FileDiff(path=path, hunks=[cr.Hunk(header="@@ -1 +1 @@", lines=[("+", 1, "x")])])
            self.assertFalse(cr.is_review_target(f), path)


class BatchTest(unittest.TestCase):
    def test_smallFilesShareBatch(self):
        files = [f for f in cr.parse_diff(DIFF) if cr.is_review_target(f)]
        batches = cr.make_batches(files, limit=100)
        self.assertEqual(len(batches), 1)
        self.assertEqual([p for p, _ in batches[0]], ["apps/x/Foo.java", "apps/x/New.java"])

    def test_largeFileSplitsByHunk(self):
        foo = [f for f in cr.parse_diff(DIFF) if f.path == "apps/x/Foo.java"]
        batches = cr.make_batches(foo, limit=8)
        self.assertEqual(len(batches), 2)
        self.assertTrue(batches[0][0][1][0].startswith("@@ -10"))
        self.assertTrue(batches[1][0][1][0].startswith("@@ -40"))

    def test_renderShowsLineNumbersOnlyForNewSide(self):
        foo = [f for f in cr.parse_diff(DIFF) if f.path == "apps/x/Foo.java"][0]
        rendered = cr.render_hunk(foo.hunks[0])
        self.assertEqual(rendered[1], "    10|     int a;")
        self.assertEqual(rendered[2], "-     |     int b;")
        self.assertEqual(rendered[3], "+   11|     long b;")


class SelectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "apps/x"))
        os.makedirs(os.path.join(self.root, "config-repo"))
        with open(os.path.join(self.root, "config-repo/gateway-dev.yaml"), "w") as f:
            f.write("a\nb\nc\n")
        self.diffs = {f.path: f for f in cr.parse_diff(DIFF) if cr.is_review_target(f)}

    def tearDown(self):
        self.tmp.cleanup()

    def finding(self, **kw):
        base = {"file": "apps/x/Foo.java", "line": 11, "severity": "major", "category": "bug",
                "confidence": "high", "title": "타입 변경", "reason": "이유", "suggestion": "제안"}
        base.update(kw)
        return base

    def test_lineInDiffIsInline(self):
        kept, _ = cr.select([self.finding()], self.diffs, self.root)
        self.assertTrue(kept[0]["inline"])

    def test_existingFileOutsideDiffGoesToBody(self):
        kept, _ = cr.select([self.finding(file="config-repo/gateway-dev.yaml", line=2)], self.diffs, self.root)
        self.assertFalse(kept[0]["inline"])

    def test_missingLocationIsDropped(self):
        raw = [self.finding(file="nope/X.java"), self.finding(file="config-repo/gateway-dev.yaml", line=99),
               self.finding(line="abc")]
        kept, filtered = cr.select(raw, self.diffs, self.root)
        self.assertEqual((kept, filtered), ([], {"bad-location": 3}))

    def test_pathPrefixesAreNormalized(self):
        raw = [self.finding(file=f"file://{self.root}/apps/x/Foo.java#L11"), self.finding(file="b/apps/x/Foo.java", line=12)]
        kept, _ = cr.select(raw, self.diffs, self.root)
        self.assertEqual([(k["file"], k["line"], k["inline"]) for k in kept],
                         [("apps/x/Foo.java", 11, True), ("apps/x/Foo.java", 12, True)])

    def test_duplicatesMergedAndSortedBySeverity(self):
        raw = [self.finding(severity="minor", title="사소"), self.finding(), self.finding(),
               self.finding(severity="blocker", confidence="low", line=12, title="장애")]
        kept, filtered = cr.select(raw, self.diffs, self.root)
        self.assertEqual([k["title"] for k in kept], ["장애", "타입 변경", "사소"])
        self.assertEqual([k["id"] for k in kept], [1, 2, 3])
        self.assertEqual(filtered, {"duplicate": 1})

    def test_limitAndMiddleDotCleanup(self):
        raw = [self.finding(line=n, title=f"t{n}", reason="a·b") for n in (10, 11, 12, 13)]
        kept, filtered = cr.select(raw, self.diffs, self.root, limit=2)
        self.assertEqual(len(kept), 2)
        self.assertEqual(filtered, {"over-limit": 2})
        self.assertEqual(kept[0]["reason"], "a, b")

    def test_unknownSeverityBecomesMinor(self):
        kept, _ = cr.select([self.finding(severity="critical", confidence="sure")], self.diffs, self.root)
        self.assertEqual((kept[0]["severity"], kept[0]["confidence"]), ("minor", "low"))


class PayloadTest(unittest.TestCase):
    def result(self):
        return {"model": "m", "head": "abc", "files": ["apps/x/Foo.java"], "summaries": ["요약"],
                "findings": [
                    {"id": 1, "file": "apps/x/Foo.java", "line": 11, "severity": "major", "confidence": "high",
                     "category": "bug", "title": "줄 지적", "reason": "r", "suggestion": "s", "evidence": [], "inline": True},
                    {"id": 2, "file": "config-repo/g.yaml", "line": 2, "severity": "minor", "confidence": "medium",
                     "category": "other", "title": "본문 지적", "reason": "r", "suggestion": "s", "evidence": ["a:1"],
                     "inline": False},
                ]}

    def test_inlineCommentsAndBodyNotes(self):
        p = cr.review_payload(self.result(), set())
        self.assertEqual(p["commit_id"], "abc")
        self.assertEqual(p["event"], "COMMENT")
        self.assertEqual([(c["path"], c["line"], c["side"]) for c in p["comments"]], [("apps/x/Foo.java", 11, "RIGHT")])
        self.assertIn("`config-repo/g.yaml:2`", p["body"])
        self.assertNotIn("줄 지적", p["body"])

    def test_dropRemovesFinding(self):
        p = cr.review_payload(self.result(), {1})
        self.assertEqual(p["comments"], [])
        self.assertIn("지적 1건", p["body"])

    def test_withoutInlineEverythingGoesToBody(self):
        p = cr.review_payload(self.result(), set(), inline=False)
        self.assertNotIn("comments", p)
        self.assertIn("줄 지적", p["body"])
        self.assertIn("본문 지적", p["body"])



class RobustnessTest(unittest.TestCase):
    def test_extractJsonHandlesFencesAndProse(self):
        self.assertEqual(cr.extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(cr.extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(cr.extract_json('결과입니다.\n{"a": 1}\n끝'), {"a": 1})
        self.assertEqual(cr.extract_json('```{"a": 1}```'), {"a": 1})
        with self.assertRaises(ValueError):
            cr.extract_json("```")

    def test_parseResponseRejectsWrongShapes(self):
        for response in ["없음", '{"findings": null}', '{"findings": "x"}', ["x"]]:
            self.assertEqual(cr.parse_response(response, {})["status"], "unparsed", response)
        r = cr.parse_response('{"findings": [{"file": "a"}, "x", 1], "summary": 3}', None)
        self.assertEqual((r["status"], r["findings"], r["summary"], r["usage"]), ("ok", [{"file": "a"}], "", {}))

    def test_largeHunkIsSplitByLinesAndBytes(self):
        hunk = cr.Hunk(header="@@ -0,0 +1,300 @@", lines=[("+", n, "가" * 100) for n in range(1, 301)])
        f = cr.FileDiff(path="apps/Big.java", hunks=[hunk])
        batches = cr.make_batches([f], limit=1000, max_bytes=20_000)
        self.assertGreater(len(batches), 1)
        for b in batches:
            self.assertLessEqual(cr.nbytes([l for _, lines in b for l in lines]), 20_000)
        self.assertTrue(batches[1][0][1][0].startswith("@@ (앞 조각에서 이어짐)"))

    def test_quotedNonAsciiPathIsDecoded(self):
        diff = ('diff --git "a/docs/\\355\\225\\234.java" "b/docs/\\355\\225\\234.java"\n'
                '--- "a/docs/\\355\\225\\234.java"\n+++ "b/docs/\\355\\225\\234.java"\n@@ -1 +1 @@\n-a\n+b\n')
        self.assertEqual(cr.parse_diff(diff)[0].path, "docs/한.java")

    def test_pathOutsideRepositoryIsDropped(self):
        with tempfile.TemporaryDirectory() as root:
            raw = [{"file": "/etc/hostname", "line": 1, "title": "t"}, {"file": "../../etc/hostname", "line": 1, "title": "t"}]
            kept, filtered = cr.select(raw, {}, root)
            self.assertEqual((kept, filtered), ([], {"bad-location": 2}))

    def test_failedBatchesAreShownAndErrorResultIsNotPosted(self):
        result = {"model": "m", "head": "abc", "files": ["a.java", "b.java"], "findings": [], "status": "partial",
                  "errors": [{"files": ["b.java"], "status": "timeout"}]}
        self.assertIn("`b.java`", cr.review_payload(result, set())["body"])
        self.assertEqual(cr.post_review(dict(result, status="error"), "o/r", 1, set()), 1)

    def test_originUrlFormats(self):
        urls = ["git@github.com:o/r.git", "https://github.com/o/r", "ssh://git@github.com/o/r.git",
                "https://user@github.com/o/r.git"]
        for url in urls:
            orig = cr.run
            cr.run = lambda *a, **k: url + "\n"
            try:
                self.assertEqual(cr.origin_repo(), "o/r", url)
            finally:
                cr.run = orig


if __name__ == "__main__":
    unittest.main(verbosity=1)
