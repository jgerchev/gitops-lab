"""Offline safety tests. Run: python3 -B -m unittest discover -s infra/tests -v"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from runtime import CHECKOUT, external

spec = importlib.util.spec_from_file_location("fetch_image", SCRIPTS / "fetch-image.py")
fetch_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_image)
tf_spec = importlib.util.spec_from_file_location("tf_wrapper", SCRIPTS / "tf.py")
tf_wrapper = importlib.util.module_from_spec(tf_spec)
tf_spec.loader.exec_module(tf_wrapper)


class SafetyTests(unittest.TestCase):
    def test_checkout_and_relative_paths_rejected(self):
        for path in ["relative", str(CHECKOUT), str(CHECKOUT / "state"), str(CHECKOUT.parent)]:
            with self.assertRaises(ValueError):
                external(path)

    def test_symlink_into_checkout_rejected(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            link = Path(tmp) / "link"
            link.symlink_to(CHECKOUT, target_is_directory=True)
            with self.assertRaises(ValueError):
                external(str(link / "state"))

    def wrapper(self, command, overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TF_")}
        env.update(overrides)
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / "tf.py"), command],
                              env=env, capture_output=True, text=True)

    def test_hidden_flags_and_workspace_rejected(self):
        for values in [{"TF_CLI_ARGS": "-state=unsafe"}, {"TF_WORKSPACE": "production"}]:
            result = self.wrapper("plan", values)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing", result.stderr)

    def test_runtime_and_data_must_be_external(self):
        result = self.wrapper("validate", {"LAB_RUNTIME_DIR": str(CHECKOUT / "unsafe")})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside", result.stderr)

    def test_corrupt_cached_image_never_overwritten(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            images = Path(tmp) / "images"
            images.mkdir()
            image = images / fetch_image.IMAGE_NAME
            image.write_bytes(b"corrupt")
            with patch.dict(os.environ, LAB_RUNTIME_DIR=tmp):
                with self.assertRaises(ValueError):
                    fetch_image.main()
            self.assertEqual(image.read_bytes(), b"corrupt")

    def test_download_hash_mismatch_leaves_no_image(self):
        import io
        response = io.BytesIO(b"not an Ubuntu image")
        response.url = fetch_image.IMAGE_URL
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            with patch.dict(os.environ, LAB_RUNTIME_DIR=tmp):
                with patch.object(fetch_image.urllib.request, "urlopen", return_value=response):
                    with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                        fetch_image.main()
            self.assertEqual(list((Path(tmp) / "images").iterdir()), [])

    def test_init_forces_external_backend_and_preserves_executable(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            executable = data / "provider"
            executable.write_text("test fixture")
            executable.chmod(0o700)
            env = {"LAB_RUNTIME_DIR": tmp, "TF_DATA_DIR": str(data)}
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["tf.py", "init"]):
                with patch.object(tf_wrapper.subprocess, "check_output", return_value=b'{"terraform_version":"1.17.2"}'):
                    with patch.object(tf_wrapper.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                        self.assertEqual(tf_wrapper.main(), 0)
                        args = run.call_args.args[0]
                        self.assertIn(f"-backend-config=path={tmp}/state/terraform.tfstate", args)
                        self.assertIn("-lockfile=readonly", args)
                        self.assertEqual(run.call_args.kwargs["env"]["TMPDIR"], tmp + "/tmp")
            self.assertEqual(executable.stat().st_mode & 0o777, 0o700)

    def test_apply_requires_explicit_gate(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            env = {"LAB_RUNTIME_DIR": tmp, "TF_DATA_DIR": tmp + "/data"}
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["tf.py", "apply"]):
                with patch.object(tf_wrapper.subprocess, "check_output", return_value=b'{"terraform_version":"1.17.2"}'):
                    with self.assertRaisesRegex(ValueError, "LAB_APPROVE=apply"):
                        tf_wrapper.main()

    def test_plan_rejects_backend_pointing_elsewhere(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data / "terraform.tfstate").write_text(json.dumps({"backend": {"type": "local", "config": {"path": "/unsafe/state"}}}))
            env = {"LAB_RUNTIME_DIR": tmp, "TF_DATA_DIR": str(data)}
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["tf.py", "plan"]):
                with patch.object(tf_wrapper.subprocess, "check_output", return_value=b'{"terraform_version":"1.17.2"}'):
                    with self.assertRaisesRegex(ValueError, "Backend does not match"):
                        tf_wrapper.main()


if __name__ == "__main__":
    unittest.main()
