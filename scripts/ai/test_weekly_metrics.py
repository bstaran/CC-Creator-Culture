#!/usr/bin/env python3
"""weekly-metrics.py 단위 테스트. 스크립트를 고치면 실행한다.

    python3 scripts/ai/test_weekly_metrics.py
"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("weekly_metrics", os.path.join(HERE, "weekly-metrics.py"))
wm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wm)


def pr(number=1, labels=(), created="2026-11-19T01:00:00Z", merged="2026-11-19T04:00:00Z",
       commits=(), reviews=(), issues=(), add=10, delete=5):
    return {
        "number": number, "title": f"PR {number}", "labels": [{"name": l} for l in labels],
        "createdAt": created, "mergedAt": merged, "additions": add, "deletions": delete,
        "commits": [{"committedDate": c} for c in commits],
        "reviews": [{"state": s} for s in reviews],
        "closingIssuesReferences": [{"number": n} for n in issues],
    }


class TrackTest(unittest.TestCase):
    def test_trackLabelWinsOverArea(self):
        self.assertEqual(wm.track_of(["area: ai-system", "type: bug"]), "버그 수정")

    def test_aiSystemAreaIsItsOwnTrack(self):
        self.assertEqual(wm.track_of(["area: ai-system"]), "AI 체계")

    def test_noLabelIsUnclassified(self):
        self.assertEqual(wm.track_of(["documentation"]), wm.UNCLASSIFIED)


class UnmodifiedTest(unittest.TestCase):
    def test_commitsBeforeOpenDoNotCount(self):
        p = pr(commits=["2026-11-19T00:30:00Z", "2026-11-19T01:00:00Z"])
        self.assertEqual(wm.commits_after_open(p), 0)
        self.assertTrue(wm.is_unmodified(p))

    def test_commitAfterOpenIsModification(self):
        p = pr(commits=["2026-11-19T00:30:00Z", "2026-11-19T02:00:00Z"])
        self.assertEqual(wm.commits_after_open(p), 1)
        self.assertFalse(wm.is_unmodified(p))

    def test_changesRequestedIsModification(self):
        p = pr(reviews=["COMMENTED", "CHANGES_REQUESTED", "APPROVED"])
        self.assertEqual(wm.changes_requested(p), 1)
        self.assertFalse(wm.is_unmodified(p))


class SummaryTest(unittest.TestCase):
    def test_summaryGroupsByTrackAndCountsAiUnmodified(self):
        prs = [
            pr(1, ["type: bug", wm.AI_LABEL], issues=[5]),
            pr(2, ["type: bug", wm.AI_LABEL], commits=["2026-11-19T03:00:00Z"], add=100, delete=0),
            pr(3, ["type: bug"], issues=[6]),
            pr(4, []),
        ]
        rows = wm.summarize_prs(prs, {5: ["type: bug", "source: scan"], 6: ["type: bug"]})
        self.assertEqual([r["track"] for r in rows], ["버그 수정", wm.UNCLASSIFIED])
        bug = rows[0]
        self.assertEqual((bug["prs"], bug["ai"], bug["ai_unmodified"]), (3, 2, 1))
        self.assertEqual(wm.median(bug["lines"]), 15)
        self.assertEqual(bug["sources"], {"정기 스캔": 1, "이슈 없음": 1, "이슈 연결": 1})

    def test_leadTimeFormatting(self):
        self.assertEqual(wm.lead_hours(pr()), 3.0)
        self.assertEqual(wm.fmt_hours(3.0), "3.0시간")
        self.assertEqual(wm.fmt_hours(72), "3.0일")
        self.assertEqual(wm.fmt_hours(None), "-")


class FrozenViolationTest(unittest.TestCase):
    def test_countsClassesWithInnerClassesSeparately(self):
        lines = [
            "Constructor <a.app.FooService.<init>(a.infra.Bar)> has parameter of type <a.infra.Bar> in (FooService.java:0)",
            "Method <a.app.FooService.run()> calls method <a.infra.Bar.go()> in (FooService.java:10)",
            "Constructor <a.app.FooService$Inner.<init>(a.web.Res)> has parameter of type <a.web.Res> in (FooService.java:0)",
            "Field <a.app.BazService.bar> has type <a.infra.Bar> in (BazService.java:0)",
            "Class <a.app.QuxUseCase> implements interface <a.web.Port> in (QuxUseCase.java:0)",
        ]
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "11111111-2222"), "w") as f:
                f.write("\n".join(lines) + "\n")
            open(os.path.join(d, "33333333-4444"), "w").close()
            with open(os.path.join(d, "stored.rules"), "w") as f:
                f.write("rule=11111111-2222\n")
            self.assertEqual(wm.frozen_violations(d), (4, 5))

    def test_repositoryStoreIsReadable(self):
        for s in wm.SERVICES:   # 위반을 모두 고쳐 0이 되어도 통과해야 한다
            store = os.path.join(wm.ROOT, "apps", s, "src/test/resources/archunit_store")
            self.assertTrue(os.path.isdir(store), store)
            c, d = wm.frozen_violations(store)
            self.assertTrue(0 <= c <= d, (s, c, d))


class RenderTest(unittest.TestCase):
    def issue(self, number, *labels):
        return {"number": number, "title": f"이슈 {number}", "labels": [{"name": l} for l in labels]}

    def render(self, prs=(), opened=(), backlog=()):
        return wm.render("2026-11-13", "2026-11-19", list(prs), list(opened), list(backlog), {}, False)

    def test_aiSystemIssuesAreCounted(self):
        out = self.render(opened=[self.issue(1, "area: ai-system")], backlog=[self.issue(1, "area: ai-system")])
        self.assertIn("| AI 체계 | 1 | 0 | 1 |", out)

    def test_pipeInTitleIsEscaped(self):
        out = self.render(prs=[dict(pr(7, ["type: bug"]), title="fix: a|b\nc")])
        self.assertIn("#7 fix: a\\|b c |", out)

    def test_reportIssuesAreExcluded(self):
        issues = [self.issue(1, "report: weekly"), self.issue(2, "type: bug")]
        self.assertEqual([i["number"] for i in wm.without_reports(issues)], [2])


class SameRepoRefsTest(unittest.TestCase):
    def test_keepsOnlyIssuesOfThisRepository(self):
        refs = [{"number": 5, "repository": {"name": "CC", "owner": {"login": "me"}}},
                {"number": 6, "repository": {"name": "CC", "owner": {"login": "team"}}},
                {"number": 7}]
        self.assertEqual([r["number"] for r in wm.same_repo_refs({"closingIssuesReferences": refs}, "me/CC")], [5, 7])


if __name__ == "__main__":
    unittest.main(verbosity=1)
