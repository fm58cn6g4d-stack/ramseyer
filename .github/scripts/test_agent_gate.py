#!/usr/bin/env python3
"""Tests for ramseyer's merge gate: tier rules, review parsing and Espen-approval check (standard library only).
Adapted from Project 2050's gate tests; reviews are between Claude Code sessions."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_gate as g  # noqa: E402

POLICY = g.load_policy()
HEAD = "a" * 40


def item(body, t="2026-10-26T12:00:00Z", user="fm58cn6g4d-stack", app=None):
    return {"body": body, "created_at": t, "user": user, "app": app}


def review(verdict="approve", head=HEAD, who="claude-code session_B"):
    return f"Looks fine.\n\nAgent-Review: {verdict}\nReviewed-Head: {head}\nReviewer: {who}\n"


class Wording(unittest.TestCase):
    def test_wording_fix(self):
        self.assertTrue(g.wording_only(["The surge is $105B for CAP-7S."], ["The rebuild surge is $105B for CAP-7S."]))

    def test_number_change_is_not_wording(self):
        self.assertFalse(g.wording_only(["The surge is $105B."], ["The surge is $110B."]))

    def test_id_change_is_not_wording(self):
        self.assertFalse(g.wording_only(["See HLT-2."], ["See HLT-3."]))

    def test_program_ids(self):
        self.assertEqual(g.program_ids("CAP-7S and DEV-P and SS-5, not FY2029 or D4-B"), {"CAP-7S", "SS-5", "DEV-P"})


class Rules(unittest.TestCase):
    def tier(self, path):
        return g.match_rule(path, POLICY)["tier"]

    def test_paths(self):
        self.assertEqual(self.tier(".github/merge-policy.json"), 3)
        self.assertEqual(self.tier("CLAUDE.md"), 3)
        self.assertEqual(self.tier("CONTRIBUTING.md"), 3)
        self.assertEqual(self.tier("tests/oracle/labels.json"), 3)
        self.assertEqual(self.tier("tests/oracle/m6_baseline.json"), 2)
        self.assertEqual(self.tier("docs/06-dry-run.md"), 2)
        self.assertEqual(self.tier("ramseyer.toml"), 2)
        self.assertEqual(self.tier("src/ramseyer/dryrun/engine.py"), 1)
        self.assertEqual(self.tier("tests/unit/test_dryrun.py"), 1)
        self.assertEqual(self.tier("records/milestones.md"), 1)
        self.assertEqual(self.tier("something-new.txt"), 2)

    def test_no_generated_outputs_or_owners(self):
        self.assertFalse(g.is_generated("src/ramseyer/cli.py", POLICY))
        self.assertEqual(g.owners_of("src/ramseyer/cli.py", POLICY), set())


class Headlines(unittest.TestCase):
    def test_tiers(self):
        base = {"num:debt": 100.0, "margin:m": 0.10, "test:t": True}
        self.assertEqual(g.compare_headlines(base, dict(base), POLICY), [])
        small = g.compare_headlines(base, {**base, "num:debt": 100.5}, POLICY)
        self.assertEqual([r[3] for r in small], [2])
        big = g.compare_headlines(base, {**base, "num:debt": 102.0}, POLICY)
        self.assertEqual([r[3] for r in big], [3])
        self.assertEqual(g.compare_headlines(base, {**base, "margin:m": 0.12}, POLICY)[0][3], 3)
        self.assertEqual(g.compare_headlines(base, {**base, "margin:m": 0.101}, POLICY)[0][3], 2)
        self.assertEqual(g.compare_headlines(base, {**base, "test:t": False}, POLICY)[0][3], 3)
        self.assertEqual(g.compare_headlines(base, {"num:debt": 100.0, "margin:m": 0.10}, POLICY)[0][3], 3)


class Reviews(unittest.TestCase):
    author = ("claude-code", "session_A")

    def ev(self, items, owners=()):
        return g.evaluate_reviews(items, HEAD, self.author, list(owners), POLICY)

    def test_review_must_come_through_claimed_agents_app(self):
        # Claude Code posts through the 'claude' app; a Claude session cannot pass itself off as Codex.
        self.assertTrue(self.ev([item(review(who="claude-code session_B"), app="claude")])[0])
        self.assertFalse(self.ev([item(review(who="claude-code session_B"), app=None)])[0])
        self.assertFalse(self.ev([item(review(who="codex t1"), app="claude")])[0])

    def test_stale_head_does_not_count(self):
        self.assertFalse(self.ev([item(review(head="b" * 40), app="claude")])[0])

    def test_changes_requested_on_older_head_still_blocks(self):
        old = item(review("changes-requested", head="b" * 40, who="claude-code session_C"), t="2026-10-26T12:00:00Z",
                   app="claude")
        other = item(review(who="claude-code session_B"), t="2026-10-26T13:00:00Z", app="claude")
        ok, why, _, _ = self.ev([old, other])
        self.assertFalse(ok)
        self.assertIn("session_C", why)
        again = item(review(who="claude-code session_C"), t="2026-10-26T14:00:00Z", app="claude")
        self.assertTrue(self.ev([old, other, again])[0])

    def test_short_sha_prefix_counts(self):
        self.assertTrue(self.ev([item(review(head=HEAD[:12]), app="claude")])[0])

    def test_author_cannot_self_review(self):
        self.assertFalse(self.ev([item(review(who="claude-code session_A"))])[0])
        self.assertFalse(self.ev([item(review(who="claude-code"))])[0])

    def test_other_session_same_vendor(self):
        self.assertTrue(self.ev([item(review(who="claude-code session_B"), app="claude")])[0])

    def test_changes_requested_blocks_until_reapproved(self):
        a = item(review(), t="2026-10-26T12:00:00Z", app="claude")
        b = item(review("changes-requested"), t="2026-10-26T13:00:00Z", app="claude")
        c = item(review(), t="2026-10-26T14:00:00Z", app="claude")
        self.assertFalse(self.ev([a, b])[0])
        self.assertTrue(self.ev([a, b, c])[0])

    def test_edited_into_block_counts_from_the_edit(self):
        old = item(review("changes-requested"), t="2026-10-26T10:00:00Z", app="claude")
        old["updated_at"] = "2026-10-26T12:00:00Z"
        later = item(review(), t="2026-10-26T11:00:00Z", app="claude")
        self.assertFalse(self.ev([old, later])[0])

    def test_edited_old_approval_does_not_lift_a_later_block(self):
        old = item(review(), t="2026-10-26T10:00:00Z", app="claude")
        old["updated_at"] = "2026-10-26T12:00:00Z"
        block = item(review("changes-requested"), t="2026-10-26T11:00:00Z", app="claude")
        self.assertFalse(self.ev([old, block])[0])

    def test_outsider_comment_ignored(self):
        self.assertFalse(self.ev([item(review(), user="someone-else", app="claude")])[0])

    def test_commit_time_is_utc(self):
        t = g.commit_time("HEAD")
        self.assertRegex(t, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(g.commit_time("0" * 40), "")

    def test_author_from_body_or_branch(self):
        self.assertEqual(g.pr_author("x\nAgent-Author: claude-code session_9\n", "whatever", POLICY),
                         ("claude-code", "session_9"))
        self.assertEqual(g.pr_author("x\nAgent-Author: codex task-9\n", "codex/x", POLICY), (None, None))
        self.assertEqual(g.pr_author("", "claude/agent-automation", POLICY), ("claude-code", None))
        self.assertEqual(g.pr_author("", "feature/x", POLICY), (None, None))


class ReviewItems(unittest.TestCase):
    def rev(self, verdict, state):
        body = f"Agent-Review: {verdict}\nReviewed-Head: abc1234\nReviewer: claude-code session_B"
        return {"body": body, "state": state, "submitted_at": "t", "user": {"login": "u"},
                "performed_via_github_app": {"slug": "claude"}}

    def test_dismissed_approval_does_not_count(self):
        self.assertEqual(len(g.review_items([], [self.rev("approve", "COMMENTED")])), 1)
        self.assertEqual(g.review_items([], [self.rev("approve", "DISMISSED")]), [])

    def test_dismissed_block_still_blocks(self):
        self.assertEqual(len(g.review_items([], [self.rev("changes-requested", "DISMISSED")])), 1)


class ReviewFlow(unittest.TestCase):
    author = ("claude-code", "session_A")
    OLD = "c" * 40

    def test_approval_carries_over_a_plain_main_update(self):
        items = [item(review(head=self.OLD), app="claude")]
        self.assertFalse(g.evaluate_reviews(items, HEAD, self.author, [], POLICY)[0])
        ok, why, approvals, blocks = g.evaluate_reviews(items, HEAD, self.author, [], POLICY,
                                                        carries=lambda h: h == self.OLD)
        self.assertTrue(ok, why)
        self.assertEqual(blocks, [])

    def test_objection_is_reported_as_a_block(self):
        items = [item(review("changes-requested"), app="claude")]
        ok, why, approvals, blocks = g.evaluate_reviews(items, HEAD, self.author, [], POLICY)
        self.assertFalse(ok)
        self.assertEqual(blocks, [("claude-code", "session_B")])


    def test_override_label_is_checked_like_approval(self):
        ev = [{"event": "labeled", "label": {"name": "espen-override"}, "actor": {"login": "fm58cn6g4d-stack"},
               "performed_via_github_app": None}]
        self.assertTrue(g.espen_approval(ev, POLICY, "espen-override")[0])
        self.assertFalse(g.espen_approval(ev, POLICY)[0])
        ev[0]["performed_via_github_app"] = {"slug": "claude"}
        self.assertFalse(g.espen_approval(ev, POLICY, "espen-override")[0])


class OverrideAndLabels(unittest.TestCase):
    """The decision behind agent-review, and when a push voids Espen's labels (review of PR #34)."""
    author = ("claude-code", "session_A")
    OBJECTION = item(review("changes-requested", head="b" * 40), app="claude")

    def decide(self, items, tier, espen_ok=False, override_ok=False, owners=()):
        return g.review_decision(items, HEAD, self.author, list(owners), POLICY, lambda h: False, tier, espen_ok, override_ok)

    def test_override_alone_does_not_approve_tier1(self):
        # Codex objected; Espen overrode; nobody approved the current head: still blocked.
        ok, why = self.decide([self.OBJECTION], tier=1, override_ok=True)
        self.assertFalse(ok)
        self.assertIn("Espen overrode the objection", why)
        self.assertIn("no approving agent review", why)

    def test_override_plus_approval_merges_tier1(self):
        ok, _ = self.decide([self.OBJECTION, item(review(who="claude-code session_B"), app="claude")], tier=1, override_ok=True)
        self.assertTrue(ok)

    def test_override_still_needs_path_owner(self):
        ok, why = self.decide([self.OBJECTION, item(review(who="claude-code session_B"), app="claude")],
                              tier=1, override_ok=True, owners=["codex"])
        self.assertFalse(ok)
        self.assertIn("path owner", why)

    def test_tier3_espen_label_stands_in_only_without_objection(self):
        self.assertTrue(self.decide([], tier=3, espen_ok=True)[0])
        ok, why = self.decide([self.OBJECTION], tier=3, espen_ok=True)
        self.assertFalse(ok)
        self.assertIn("espen-override", why)
        self.assertTrue(self.decide([self.OBJECTION], tier=3, espen_ok=True, override_ok=True)[0])

    NAMES = ["espen-approved", "espen-override"]

    def void(self, labels, heads, head, carries=lambda old: False, event="", pushed_at="", events=()):
        return g.voided_labels(labels, heads, head, list(events), event, pushed_at, carries, self.NAMES)

    def test_push_after_override_voids_it(self):
        # Reviewer's scenario: override added on H1, author pushes H2 with new content.
        void, heads = self.void(["espen-override"], {"espen-override": "h1"}, "h2", event="synchronize")
        self.assertEqual(void, ["espen-override"])
        self.assertEqual(heads, {})

    def test_cancelled_synchronize_run_cannot_save_a_label(self):
        # Any later run (ready_for_review, a comment) sees the labeled head differs and voids it.
        void, _ = self.void(["espen-approved"], {"espen-approved": "h1"}, "h2", event="ready_for_review")
        self.assertEqual(void, ["espen-approved"])

    def test_main_only_push_keeps_labels(self):
        void, heads = self.void(["espen-approved", "espen-override"], {"espen-approved": "h1", "espen-override": "h1"},
                                "h2", carries=lambda old: old == "h1", event="synchronize")
        self.assertEqual(void, [])
        self.assertEqual(heads, {"espen-approved": "h2", "espen-override": "h2"})

    def test_unknown_labeled_head_falls_back_to_push_time(self):
        ev = [{"event": "labeled", "label": {"name": "espen-approved"}, "created_at": "2026-10-26T10:00:00Z"}]
        void, _ = self.void(["espen-approved"], {}, "h2", event="synchronize", pushed_at="2026-10-26T11:00:00Z", events=ev)
        self.assertEqual(void, ["espen-approved"])
        void, heads = self.void(["espen-approved"], {}, "h2", event="synchronize", pushed_at="2026-10-26T09:00:00Z", events=ev)
        self.assertEqual((void, heads), ([], {"espen-approved": "h2"}))

    def test_unknown_labeled_head_dated_by_commit_in_any_run(self):
        ev = [{"event": "labeled", "label": {"name": "espen-approved"}, "created_at": "2026-10-26T10:00:00Z"}]
        # A comment-triggered run, no labeled head on record, head commit made after the label: void.
        void, _ = g.voided_labels(["espen-approved"], {}, "h2", ev, "created", "", lambda o: False, self.NAMES,
                                  head_time="2026-10-26T10:30:00Z")
        self.assertEqual(void, ["espen-approved"])
        # Head commit older than the label: Espen labeled this version; keep it.
        void, heads = g.voided_labels(["espen-approved"], {}, "h2", ev, "created", "", lambda o: False, self.NAMES,
                                      head_time="2026-10-26T09:30:00Z")
        self.assertEqual((void, heads), ([], {"espen-approved": "h2"}))

    def test_removed_label_is_forgotten(self):
        self.assertEqual(self.void([], {"espen-approved": "h1"}, "h2"), ([], {}))

    def test_override_detail_names_the_label(self):
        self.assertEqual(g.espen_approval([], POLICY, "espen-override"), (False, "no espen-override label"))


class EspenApproval(unittest.TestCase):
    def ev(self, actor="fm58cn6g4d-stack", app=None, event="labeled"):
        return {"event": event, "label": {"name": "espen-approved"}, "actor": {"login": actor},
                "performed_via_github_app": {"slug": app} if app else None}

    def test_direct_label(self):
        self.assertTrue(g.espen_approval([self.ev()], POLICY)[0])

    def test_label_via_agent_app_rejected(self):
        self.assertFalse(g.espen_approval([self.ev(app="claude")], POLICY)[0])

    def test_other_actor_rejected(self):
        self.assertFalse(g.espen_approval([self.ev(actor="someone")], POLICY)[0])

    def test_removed_label(self):
        self.assertFalse(g.espen_approval([self.ev(), self.ev(event="unlabeled")], POLICY)[0])


class LabelTiming(unittest.TestCase):
    def test_label_before_and_after_push(self):
        ev = [{"event": "labeled", "label": {"name": "espen-approved"}, "created_at": "2026-10-26T16:20:00Z"}]
        self.assertTrue(g.label_added_before(ev, "espen-approved", "2026-10-26T16:21:00Z"))
        self.assertFalse(g.label_added_before(ev, "espen-approved", "2026-10-26T16:19:00Z"))
        self.assertFalse(g.label_added_before([], "espen-approved", "2026-10-26T16:19:00Z"))


class FakeGitHub:
    """Answers the digest's API calls from fixed data and records writes."""
    def __init__(self, repo, token):
        self.writes = []
        FakeGitHub.last = self

    def call(self, method, path, data=None):
        if method != "GET":
            self.writes.append((method, path, data))
            return {"number": 99}
        if path.startswith("/pulls?state=closed"):
            return [{"number": 30, "title": "Wording fix", "merged_at": "2999-01-01T00:00:00Z",
                     "labels": [{"name": "tier-1"}], "merged_by": {"login": "github-actions[bot]"}},
                    {"number": 29, "title": "Old", "merged_at": "2000-01-01T00:00:00Z", "labels": []}]
        if path.startswith("/pulls/"):
            n = int(path.split("/")[2])
            return {"number": n, "head": {"sha": f"sha{n}"}, "base": {"ref": "main"}, "mergeable": True}
        if path.startswith("/compare/"):
            return {"behind_by": 2 if path.endswith("sha31") else 0}
        if path.startswith("/commits/sha31/status"):
            return {"statuses": [{"context": "agent-review", "state": "failure", "description": "changes requested by codex t1"}]}
        if path.startswith("/commits/"):
            return {"statuses": [{"context": "agent-review", "state": "success", "description": "approved"}]}
        raise AssertionError(path)

    def pages(self, path):
        if path.startswith("/pulls?state=open"):
            return [{"number": 31, "title": "Adopt new input", "labels": [{"name": "tier-3"}]},
                    {"number": 32, "title": "Approved", "labels": [{"name": "tier-3"}, {"name": "espen-approved"}]}]
        if "labels=needs-espen" in path:
            return [{"number": 40, "title": "Choose a surge size"}]
        if "labels=agent-digest" in path:
            return []
        raise AssertionError(path)


class Retry(unittest.TestCase):
    """GitHub.call against a fake urlopen. Each scripted step is 200, an HTTP error code, an exception raised
    by urlopen(), or ('read', exc) for an exception raised while reading the response body."""

    def setUp(self):
        import urllib.request
        self.urlopen, self.delays = urllib.request.urlopen, g.RETRY_DELAYS
        g.RETRY_DELAYS = (0, 0)

    def tearDown(self):
        import urllib.request
        urllib.request.urlopen, g.RETRY_DELAYS = self.urlopen, self.delays

    def fake(self, steps):
        import io, urllib.error, urllib.request
        calls = []

        class Resp(io.BytesIO):
            def __init__(self, fail=None):
                super().__init__(b'{"ok": true}')
                self.fail = fail
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *a):
                if self.fail:
                    raise self.fail
                return super().read(*a)

        def urlopen(req):
            calls.append(req.get_method())
            step = steps[len(calls) - 1]
            if isinstance(step, tuple):
                return Resp(fail=step[1])
            if isinstance(step, BaseException):
                raise step
            if step != 200:
                raise urllib.error.HTTPError(req.full_url, step, "err", {}, io.BytesIO(b"{}"))
            return Resp()
        urllib.request.urlopen = urlopen
        return calls

    def call(self, method="GET", path="/pulls/1"):
        return g.GitHub("o/r", "t").call(method, path, {} if method != "GET" else None)

    def test_retries_server_errors_then_succeeds(self):
        calls = self.fake([502, 503, 200])
        self.assertEqual(self.call(), {"ok": True})
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_retries(self):
        self.fake([502, 502, 502])
        with self.assertRaises(RuntimeError):
            self.call()

    def test_client_errors_are_not_retried(self):
        calls = self.fake([404])
        with self.assertRaises(RuntimeError):
            self.call()
        self.assertEqual(len(calls), 1)

    def transport_errors(self):
        import http.client, urllib.error
        return [urllib.error.URLError("refused"), http.client.RemoteDisconnected("closed"),
                ConnectionResetError("reset"), TimeoutError("slow")]

    def test_transport_failures_recover(self):
        import http.client
        for exc in self.transport_errors():
            calls = self.fake([exc, 200])
            self.assertEqual(self.call(), {"ok": True}, exc)
            self.assertEqual(len(calls), 2)
        # Failures while reading the body of an opened response.
        for exc in (http.client.IncompleteRead(b"par"), ConnectionResetError("reset mid-body")):
            calls = self.fake([("read", exc), 200])
            self.assertEqual(self.call(), {"ok": True}, exc)
            self.assertEqual(len(calls), 2)

    def test_transport_failures_exhaust(self):
        import http.client
        for exc in self.transport_errors():
            calls = self.fake([exc, exc, exc])
            with self.assertRaises(RuntimeError):
                self.call()
            self.assertEqual(len(calls), 3)
        calls = self.fake([("read", http.client.IncompleteRead(b"x"))] * 3)
        with self.assertRaises(RuntimeError):
            self.call()
        self.assertEqual(len(calls), 3)

    def test_other_exceptions_are_not_caught(self):
        self.fake([ValueError("bug")])
        with self.assertRaises(ValueError):
            self.call()

    def test_new_comments_are_not_retried(self):
        calls = self.fake([502, 200])
        with self.assertRaises(RuntimeError):
            self.call("POST", "/issues/1/comments")
        self.assertEqual(len(calls), 1)

    def test_repeatable_calls(self):
        self.assertTrue(g.repeatable("GET", "/pulls/1"))
        self.assertTrue(g.repeatable("POST", "/statuses/abc"))
        self.assertTrue(g.repeatable("POST", "/issues/1/labels"))
        self.assertTrue(g.repeatable("PATCH", "/issues/comments/9"))
        self.assertTrue(g.repeatable("PUT", "/pulls/1/merge"))
        self.assertFalse(g.repeatable("POST", "/issues/1/comments"))
        self.assertFalse(g.repeatable("POST", "/issues"))

    def test_delete_already_done_counts_as_done(self):
        calls = self.fake([502, 404])
        self.assertIsNone(self.call("DELETE", "/issues/1/labels/tier-2"))
        self.assertEqual(len(calls), 2)


class MergePatience(unittest.TestCase):
    class GH:
        """Fake GitHub: PUT raises the scripted errors in turn; GET reports whether the PR is merged."""
        def __init__(self, errors, merged_after_error=False):
            self.errors, self.merged_after_error, self.puts = list(errors), merged_after_error, 0

        def call(self, method, path, data=None):
            if method == "GET":
                return {"merged": self.merged_after_error}
            self.puts += 1
            if self.errors:
                raise RuntimeError(self.errors.pop(0))
            return {"merged": True}

    PENDING = 'PUT /pulls/1/merge: 405 {"message":"Repository rule violations found 2 of 3 required status checks are pending."}'

    def test_waits_for_statuses_to_register(self):
        gh = self.GH([self.PENDING, self.PENDING])
        self.assertEqual(g.merge_with_patience(gh, 1, {}, delays=(0, 0, 0)), {"merged": True})
        self.assertEqual(gh.puts, 3)

    def test_other_refusals_fail_at_once(self):
        gh = self.GH(['PUT /pulls/1/merge: 405 {"message":"Pull Request is not mergeable"}'])
        with self.assertRaises(RuntimeError):
            g.merge_with_patience(gh, 1, {}, delays=(0, 0))
        self.assertEqual(gh.puts, 1)

    def test_merge_applied_before_an_error_is_success(self):
        gh = self.GH(["PUT /pulls/1/merge: 502 {}"], merged_after_error=True)
        self.assertEqual(g.merge_with_patience(gh, 1, {}, delays=(0,)), {"merged": True})
        self.assertEqual(gh.puts, 1)


class Digest(unittest.TestCase):
    def test_digest_lists_merged_and_waiting(self):
        old, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"] = g.GitHub, "o/r", "x"
        g.GitHub = FakeGitHub
        try:
            import argparse, contextlib, io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                g.digest(argparse.Namespace(hours=24, dry_run=False), POLICY)
        finally:
            g.GitHub = old
        text = out.getvalue()
        self.assertIn("#30 Wording fix", text)
        self.assertNotIn("#29", text)
        self.assertIn("PR #31", text)
        self.assertNotIn("PR #32", text)
        self.assertIn("Issue #40", text)
        self.assertIn("PR #31 Adopt new input: review: changes requested by codex t1", text)
        self.assertIn("PR #31 Adopt new input: out of date", text)
        writes = FakeGitHub.last.writes
        self.assertEqual(writes[0][1], "/issues")          # creates the digest issue
        self.assertEqual(writes[1][1], "/issues/99/comments")  # and comments because there is news


class Classify(unittest.TestCase):
    """Runs classify() on a scratch git repository."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_root = g.ROOT
        g.ROOT = self.tmp
        g._DOMAIN_IDS.clear()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com"); self.git("config", "user.name", "t")
        self.write("src/ramseyer/engine.py", "X = 1\n")
        self.write("records/notes.md", "Research note.\n")
        self.write("tests/oracle/labels.json", "{}\n")
        self.write("tests/oracle/m6_baseline.json", "{}\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        g.ROOT = self.old_root
        shutil.rmtree(self.tmp)

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.tmp, capture_output=True, text=True, check=True).stdout

    def write(self, path, text):
        p = os.path.join(self.tmp, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-qm", msg)
        return self.git("rev-parse", "HEAD").strip()

    def test_code_is_tier1(self):
        self.write("src/ramseyer/engine.py", "X = 2\n")
        self.assertEqual(g.classify(self.base, self.commit("c"), POLICY)["tier"], 1)

    def test_baseline_is_tier2(self):
        self.write("tests/oracle/m6_baseline.json", '{"matched": 2}\n')
        self.assertEqual(g.classify(self.base, self.commit("b"), POLICY)["tier"], 2)

    def test_hand_labels_are_tier3(self):
        self.write("tests/oracle/labels.json", '{"x": "editorial"}\n')
        self.assertEqual(g.classify(self.base, self.commit("l"), POLICY)["tier"], 3)

    def test_same_changes_after_merging_main(self):
        self.git("checkout", "-q", "-b", "pr")
        self.write("records/notes.md", "Research note, revised.\n")
        reviewed = self.commit("pr work")
        self.git("checkout", "-q", "main")
        self.write("records/other.md", "Someone else's work.\n")
        self.commit("main moves")
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "main")
        merged = self.git("rev-parse", "HEAD").strip()
        self.write("records/notes.md", "Research note, revised again.\n")
        edited = self.commit("more pr work")
        self.git("checkout", "-q", "main")  # the gate runs from a checkout of main
        self.assertTrue(g.same_changes(reviewed, merged))
        self.assertTrue(g.same_changes(reviewed[:12], merged))
        self.assertFalse(g.same_changes(reviewed, edited))
        self.assertFalse(g.same_changes("0" * 40, merged))

    def test_unusual_filename_keeps_its_tier(self):
        self.write(".github/workflows/\u00e9 x.yml", "on: push\n")
        self.assertEqual(g.classify(self.base, self.commit("w"), POLICY)["tier"], 3)

    def test_rename_keeps_source_tier(self):
        self.git("mv", "tests/oracle/labels.json", "tests/labels_archive.json")
        cls = g.classify(self.base, self.commit("r"), POLICY)
        self.assertEqual(cls["tier"], 3)
        self.assertIn("renamed from tests/oracle/labels.json", cls["reasons"][0][2])

    def test_same_changes_when_main_edits_the_same_file(self):
        lines = [f"line {i}\n" for i in range(60)]
        self.write("records/long.md", "".join(lines))
        self.commit("long file")
        self.git("checkout", "-q", "-b", "pr")
        self.write("records/long.md", "".join(lines[:2] + ["line 2, revised\n"] + lines[3:]))
        reviewed = self.commit("pr edits line 2")
        self.git("checkout", "-q", "main")
        self.write("records/long.md", "".join(lines[:45] + ["line 45, main\n"] + lines[46:]))
        self.commit("main edits line 45")
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "main")
        merged = self.git("rev-parse", "HEAD").strip()
        self.write("records/long.md", "".join(lines[:2] + ["    line 2, revised\n"] + lines[3:]))
        indented = self.commit("pr re-indents its line")
        self.write("records/long.md", "".join(lines[:2] + lines[3:6] + ["line 2, revised\n"] + lines[6:45]
                                              + ["line 45, main\n"] + lines[46:]))
        moved = self.commit("pr moves its line")
        self.git("checkout", "-q", "main")
        self.assertTrue(g.same_changes(reviewed, merged))
        self.assertFalse(g.same_changes(reviewed, indented))  # whitespace can change behaviour (Python)
        self.assertFalse(g.same_changes(reviewed, moved))

    def test_merge_rules_are_tier3(self):
        self.write(".github/merge-policy.json", "{}\n")
        self.assertEqual(g.classify(self.base, self.commit("g"), POLICY)["tier"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
