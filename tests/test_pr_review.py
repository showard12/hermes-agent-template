"""No model calls or live credentials: verify the review capability boundary."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reader", ROOT / "hermes-plugins/pantryfy-review/__init__.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
HEAD = "a" * 40
BASE = "b" * 40
META = {"head": {"sha": HEAD}, "base": {"sha": BASE}, "state": "open", "draft": False,
        "title": "PR", "body": "", "changed_files": 1, "html_url": "https://github.com/example"}


class ReaderTests(unittest.TestCase):
    def call(self, operation, **kwargs):
        return reader.read({"operation": operation, "pr_number": 441, "head_sha": HEAD, **kwargs})

    def test_only_fixed_get_argv(self):
        with patch.object(reader.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            reader.api("repos/showard12/pantry_app/pulls/441")
        args, options = run.call_args
        self.assertEqual(args[0], [reader.GH, "api", "--hostname", "github.com", "--method", "GET", "repos/showard12/pantry_app/pulls/441"])
        self.assertNotIn("shell", options)

    def test_metadata(self):
        with patch.object(reader, "api", return_value=META):
            self.assertEqual(self.call("metadata")["head_sha"], HEAD)

    def test_page_and_patch(self):
        files = [{"filename": "backend/a.py", "patch": "@@ -1 +1 @@\n-a\n+b"}]
        with patch.object(reader, "api", side_effect=[META, files, META]) as api:
            result = self.call("patch", path="backend/a.py", page=2)
            self.assertIn("+b", result["patch"])
            self.assertIn("page=2", api.call_args_list[1].args[0])

    def test_source_is_data_and_pinned(self):
        code = "import os\nos.remove('/data/important')\n# third line"
        content = {"type": "file", "size": len(code), "encoding": "base64", "content": base64.b64encode(code.encode()).decode()}
        with patch.object(reader, "api", side_effect=[META, content, META]) as api:
            result = self.call("file", path="backend/a.py", revision="base", start_line=2, line_count=1)
            self.assertEqual(result["next_line"], 3)
            self.assertIn("os.remove", result["text"])
            self.assertTrue(api.call_args_list[1].args[0].endswith("ref=" + BASE))

    def test_path_traversal_and_bad_inputs(self):
        for path in ("../.env", "/data/.env", "a/../b", "a\\b", "a\nfile"):
            with self.subTest(path=path), patch.object(reader, "api", return_value=META) as api:
                with self.assertRaises(ValueError):
                    self.call("file", path=path)
                self.assertEqual(api.call_count, 1)
        with patch.object(reader, "api") as api:
            for operation in ("terminal", "exec", "write", "merge"):
                with self.assertRaises(ValueError):
                    self.call(operation)
            api.assert_not_called()

    def test_head_mismatch_and_mid_read_push_fail_closed(self):
        with patch.object(reader, "api", return_value=META) as api:
            with self.assertRaises(ValueError):
                self.call("files", head_sha=BASE)
            self.assertEqual(api.call_count, 1)
        changed = {**META, "head": {"sha": BASE}}
        with patch.object(reader, "api", side_effect=[META, [], changed]):
            with self.assertRaises(ValueError):
                self.call("files")

    def test_binary_large_and_truncated_text(self):
        for content in ({"type": "file", "size": 1000001}, {"type": "symlink"}):
            with patch.object(reader, "api", side_effect=[META, content]):
                with self.assertRaises(ValueError):
                    self.call("file", path="a")
        code = "x" * 31000
        content = {"type": "file", "size": len(code), "encoding": "base64", "content": base64.b64encode(code.encode()).decode()}
        with patch.object(reader, "api", side_effect=[META, content, META]):
            self.assertTrue(self.call("file", path="a")["truncated"])

    def test_errors_do_not_leak_subprocess_output(self):
        with patch.object(reader, "api", side_effect=ValueError("super-secret-token")):
            output = reader.handle({"operation": "metadata", "pr_number": 441})
            self.assertIn("error", json.loads(output))
            self.assertNotIn("super-secret-token", output)

    def test_config_preserves_guards_and_other_routes(self):
        with tempfile.TemporaryDirectory() as home:
            target = Path(home) / "config.yaml"
            existing = {"approvals": {"mode": "manual"}, "plugins": {"enabled": ["other"]},
                        "platforms": {"webhook": {"extra": {"routes": {"other": {"secret": "other-secret"}}}}}}
            target.write_text(yaml.safe_dump(existing))
            env = {**os.environ, "HERMES_HOME": home, "HERMES_GITHUB_WEBHOOK_SECRET": "test-secret"}
            for _ in range(2):
                subprocess.run([os.sys.executable, str(ROOT / "scripts/configure_github_webhook.py")], env=env, check=True)
            config = yaml.safe_load(target.read_text())
            self.assertEqual(config["approvals"], existing["approvals"])
            self.assertEqual(config["plugins"]["enabled"], ["other", "pantryfy-review"])
            routes = config["platforms"]["webhook"]["extra"]["routes"]
            self.assertEqual(routes["other"], {"secret": "other-secret"})
            self.assertEqual(routes["github-pr-review"]["secret"], "test-secret")
            self.assertEqual(routes["github-pr-review"]["toolsets"], ["pantryfy_review"])
            self.assertEqual(routes["github-pr-review"]["deliver"], "github_comment")


if __name__ == "__main__":
    unittest.main()
