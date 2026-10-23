"""Offline tests for the tool-enabled Pi teacher; no API or CAD calls."""
import json
import os
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import practice_teacher as teacher


class TeacherTests(unittest.TestCase):
    def config(self, root):
        credential = root / "teacher-secrets.json"
        credential.write_text(json.dumps({"api_key": "private-test-key", "base_url": "https://test/v1"}))
        credential.chmod(0o600)
        (root / "teacher-pi").mkdir()
        (root / "teacher-pi/models.json").write_text(json.dumps({"providers": {
            teacher.PROVIDER: {"baseUrl": "https://test/v1", "models": [{"id": teacher.MODEL}]}}}))
        return root

    def trace(self, path, result, stop="stop"):
        path.write_text(json.dumps({"type": "tool_execution_start", "toolName": "read"}) + "\n" +
                        json.dumps({"type": "message_end", "message": {"role": "assistant",
                            "stopReason": stop, "content": [{"type": "text", "text": result}]}}) + "\n")

    def test_private_key_permissions_and_minimal_environment(self):
        with TemporaryDirectory() as temp:
            root = self.config(Path(temp))
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "worker-secret", "UNRELATED_KEY": "other"}):
                env, key = teacher.environment(root)
            self.assertEqual(key, "private-test-key")
            self.assertNotIn("DEEPSEEK_API_KEY", env)
            self.assertNotIn("UNRELATED_KEY", env)
            (root / "teacher-secrets.json").chmod(0o644)
            with self.assertRaises(PermissionError):
                teacher.environment(root)

    def test_endpoint_mismatch_rejected(self):
        with TemporaryDirectory() as temp:
            root = self.config(Path(temp))
            (root / "teacher-secrets.json").write_text(json.dumps({"api_key": "x", "base_url": "https://other"}))
            with self.assertRaisesRegex(ValueError, "endpoint differs"):
                teacher.environment(root)

    def test_json_parser_ignores_intermediate_text_and_rejects_errors(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            self.trace(path, '{"passed": true}')
            self.assertEqual(teacher.final_json(path), {"passed": True})
            self.assertEqual(teacher.tool_calls(path), ["read"])
            self.trace(path, "not json")
            with self.assertRaises(ValueError):
                teacher.final_json(path)
            self.trace(path, "", "error")
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                teacher.final_json(path)

    def test_agent_has_tools_images_no_shell_and_no_cli_secret(self):
        with TemporaryDirectory() as temp:
            root = self.config(Path(temp))
            snapshot = root / "snapshot"
            snapshot.mkdir()
            image = snapshot / "drawing.jpg"
            image.write_bytes(b"test image")
            def runner(command, cwd, trace, env, timeout, secrets):
                self.assertEqual(cwd, snapshot)
                self.assertIn("read,grep,find,ls", command)
                self.assertIn("--no-session", command)
                self.assertIn("--extension", command)
                self.assertIn("@" + str(image.resolve()), command)
                self.assertNotIn("private-test-key", " ".join(command))
                self.assertEqual(env["KOMPAS_TEACHER_API_KEY"], "private-test-key")
                self.assertEqual(secrets, ["private-test-key"])
                self.trace(trace, '{"passed": true}')
                return 0, 1.5
            result, seconds = teacher.run_agent(snapshot, root / "output", "Review", root, runner, [image])
            self.assertTrue(result["passed"])
            self.assertEqual(seconds, 1.5)
            harness = json.loads((root / "output/harness.json").read_text())
            self.assertEqual(harness["tools_called"], ["read"])

    def test_snapshot_is_curated_and_byte_identical(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            sources = root / "source"
            sources.mkdir()
            paths = {}
            for key in ("condition", "drawing", "preview", "verification", "code", "trace"):
                source = sources / key
                source.write_bytes(key.encode())
                paths[key] = str(source)
            (sources / "secrets.json").write_text("private")
            snapshot = root / "evidence"
            images = teacher.snapshot_review({"paths": paths}, snapshot)
            self.assertEqual([p.name for p in images], ["drawing.jpg", "model.jpg"])
            self.assertFalse((snapshot / "secrets.json").exists())
            self.assertEqual((snapshot / "solution.py").read_bytes(), b"code")
            self.assertFalse(any(p.is_symlink() for p in snapshot.iterdir()))

    def test_real_path_guard_blocks_secrets_shell_and_symlink_escape(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root / "evidence"
            snapshot.mkdir()
            (snapshot / "task.md").write_text("public")
            (root / "secret.json").write_text("private")
            (snapshot / "escape").symlink_to(root, target_is_directory=True)
            script = """
import guard from GUARD;
let handler;
guard({on: (event, fn) => { handler = fn; }});
const cases = [
  ['read', {path:'task.md'}, false],
  ['read', {path:'../secret.json'}, true],
  ['read', {path:'escape/secret.json'}, true],
  ['bash', {command:'printenv'}, true],
  ['write', {path:'task.md'}, true],
  ['find', {path:'.', pattern:'../*'}, true],
  ['ls', {path:'.'}, false],
];
for (const [toolName, input, blocked] of cases) {
  const result = await handler({toolName,input});
  if (Boolean(result?.block) !== blocked) throw new Error(JSON.stringify({toolName,input,result}));
}
""".replace("GUARD", json.dumps(teacher.GUARD.as_uri()))
            subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", script],
                           cwd=snapshot, check=True, capture_output=True, text=True, timeout=20)

    def test_skillopt_uses_pi_harness_for_reflection_call(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "baseline-skill.md").write_text("skill")
            for name in ("teacher-review.json", "verification/verification.json", "workspace/solution.py"):
                path = root / "baseline" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("evidence")
            with patch.object(teacher, "run_agent", return_value=([], 1.)) as agent:
                backend = teacher.PiTeacherBackend(root, root, None)
                self.assertEqual(backend._call("reflect this"), "[]")
            self.assertTrue(agent.called)
            self.assertEqual((root / "reflection/pi-call-1/evidence/optimizer-prompt.txt").read_text(), "reflect this")


if __name__ == "__main__":
    unittest.main()
