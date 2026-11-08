# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ClaudeLimit's own scripts: cache_guard.py, limit.py, drain.py."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import cache_guard  # noqa: E402
import limit  # noqa: E402


def write_jsonl(path, recs):
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def asst(ctx, ts="2026-11-08T10:00:00Z", model="claude-opus-5-5"):
    return {"type": "assistant", "timestamp": ts, "requestId": "r" + ts,
            "message": {"model": model, "usage": {"input_tokens": 0, "cache_read_input_tokens": ctx,
                                                  "cache_creation_input_tokens": 0, "output_tokens": 100}}}


def cmd(name):
    return {"type": "user", "timestamp": "2026-11-08T10:01:00Z",
            "message": {"role": "user", "content": f"<command-name>{name}</command-name> <command-message>x</command-message>"}}


class CacheGuard(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.t = os.path.join(self.d, "t.jsonl")

    def run_guard(self, recs, lang="tr"):
        write_jsonl(self.t, recs)
        return cache_guard.check({"transcript_path": self.t}, {"lang": lang})

    def test_model_switch_warns(self):
        m = self.run_guard([asst(150000), cmd("/model")])
        self.assertIn("/model", m)
        self.assertIn("150K", m)
        self.assertIn("yeniden yazar", m)
        self.assertLessEqual(len(m), 300)

    def test_effort_only_is_hedged(self):
        m = self.run_guard([asst(150000), cmd("/effort")], lang="en")
        self.assertIn("may rewrite", m)

    def test_switch_before_last_request_is_quiet(self):
        self.assertIsNone(self.run_guard([cmd("/model"), asst(150000)]))

    def test_small_context_is_quiet(self):
        self.assertIsNone(self.run_guard([asst(10000), cmd("/model")]))

    def test_other_command_and_tool_result_quiet(self):
        tr = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "<command-name>/model</command-name>"}]}}
        self.assertIsNone(self.run_guard([asst(150000), cmd("/usage"), tr]))

    def test_missing_transcript(self):
        self.assertIsNone(cache_guard.check({"transcript_path": os.path.join(self.d, "none")}, {}))

    def test_hook_never_fails(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "cache_guard.py")], input=b"not json",
                           capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")


class Lean(unittest.TestCase):
    def setUp(self):
        self.h = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.h, ".claude"))
        self.sp = os.path.join(self.h, ".claude", "settings.json")
        self.orig = {"hooks": {}, "permissions": {"deny": ["Read(build/**)"]}, "skillOverrides": {"keep": "name-only"}}
        with open(self.sp, "w", encoding="utf-8", newline="\n") as f:  # LF, like the real settings.json
            json.dump(self.orig, f, indent=2)
            f.write("\n")

    def quiet(self, fn, *a):
        with redirect_stdout(io.StringIO()) as out:
            rc = fn(*a, home=self.h)
        return rc, out.getvalue()

    def load(self):
        with open(self.sp, encoding="utf-8") as f:
            return json.load(f)

    def test_dry_run_changes_nothing(self):
        rc, out = self.quiet(limit.lean_on, ["a"], ["Artifact"], True)
        self.assertEqual(rc, 0)
        self.assertIn('+    "a": "off"', out)
        self.assertEqual(self.load(), self.orig)
        self.assertIsNone(limit.load_state(self.h))

    def test_on_off_roundtrip(self):
        raw = open(self.sp, "rb").read()
        self.quiet(limit.lean_on, ["a", "keep"], ["Artifact", "Read(build/**)"], False)
        self.assertNotIn(b"\r\n", open(self.sp, "rb").read())  # line endings kept (no CRLF on Windows)
        s = self.load()
        self.assertEqual(s["skillOverrides"], {"keep": "name-only", "a": "off"})
        self.assertEqual(s["permissions"]["deny"], ["Read(build/**)", "Artifact"])
        st = limit.load_state(self.h)
        self.assertEqual(st["skills"], {"a": "off"})
        self.assertEqual(st["deny"], ["Artifact"])
        self.assertTrue(os.path.exists(st["backup"]))
        rc, _ = self.quiet(limit.lean_on, ["b"], [], False)
        self.assertEqual(rc, 1)  # already on
        self.quiet(limit.lean_off, False)
        self.assertEqual(self.load(), self.orig)
        self.assertEqual(open(self.sp, "rb").read(), raw)  # byte-identical after off
        self.assertIsNone(limit.load_state(self.h))

    def test_off_removes_created_keys(self):
        with open(self.sp, "w", encoding="utf-8") as f:
            json.dump({"x": 1}, f)
        self.quiet(limit.lean_on, ["a"], ["PowerShell"], False)
        self.quiet(limit.lean_off, False)
        self.assertEqual(self.load(), {"x": 1})

    def test_off_leaves_user_changes(self):
        self.quiet(limit.lean_on, ["a"], [], False)
        s = self.load()
        s["skillOverrides"]["a"] = "name-only"
        with open(self.sp, "w", encoding="utf-8") as f:
            json.dump(s, f)
        self.quiet(limit.lean_off, False)
        self.assertEqual(self.load()["skillOverrides"]["a"], "name-only")

    def test_off_when_not_on(self):
        rc, out = self.quiet(limit.lean_off, False)
        self.assertEqual(rc, 0)
        self.assertIn("off", out)


class Drain(unittest.TestCase):
    def test_runs_on_fake_home(self):
        h = tempfile.mkdtemp()
        pd = os.path.join(h, ".claude", "projects", "p")
        os.makedirs(pd)
        write_jsonl(os.path.join(pd, "s.jsonl"), [
            {"type": "user", "timestamp": "2099-01-01T00:00:00Z", "message": {"content": "hi"}},
            asst(50000, ts="2099-01-01T00:00:01Z"), asst(52000, ts="2099-01-01T02:00:00Z")])
        env = dict(os.environ, USERPROFILE=h, HOME=h)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "drain.py"), "2000-01-01"], env=env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("requests 2", r.stdout)
        self.assertIn("WHAT-IF promptCacheTtl 5m", r.stdout)
        self.assertIn("idle>1h", r.stdout)


if __name__ == "__main__":
    unittest.main()
