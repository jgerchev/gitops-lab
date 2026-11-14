import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("check-release")
updater = load("set-image")


class GateTests(unittest.TestCase):
    def run_gate(self, result):
        with patch.dict("os.environ", {"RELEASE": "v1", "GHCR_USER": "test", "GHCR_TOKEN": "not-a-secret"}):
            with patch.object(gate.urllib.request, "urlopen", side_effect=[io.BytesIO(b'{"token":"test"}'), result]):
                gate.main()

    def error(self, status, code):
        return urllib.error.HTTPError(
            "https://ghcr.io/test", status, "test", {},
            io.BytesIO(json.dumps({"errors": [{"code": code}]}).encode()),
        )

    def test_existing_tag_refused(self):
        with self.assertRaisesRegex(SystemExit, "already exists"):
            self.run_gate(io.BytesIO(b"existing manifest"))

    def test_absent_tag_allowed(self):
        self.run_gate(self.error(404, "MANIFEST_UNKNOWN"))

    def test_absent_repository_allowed(self):
        self.run_gate(self.error(404, "NAME_UNKNOWN"))

    def test_unauthorized_refused(self):
        with self.assertRaisesRegex(SystemExit, "refusing publication"):
            self.run_gate(self.error(401, "UNAUTHORIZED"))

    def test_ambiguous_404_refused(self):
        with self.assertRaisesRegex(SystemExit, "refusing publication"):
            self.run_gate(self.error(404, "UNKNOWN"))

    def test_network_failure_refused(self):
        with self.assertRaisesRegex(SystemExit, "Registry check failed"):
            self.run_gate(TimeoutError("not printed"))


class ImageUpdateTests(unittest.TestCase):
    source = "          image: ghcr.io/jgerchev/gitops-lab-app:v1\n"
    digest = "sha256:" + "a" * 64

    def test_pin_and_upgrade(self):
        pinned = updater.update_image(self.source, "v1", self.digest)
        self.assertIn("v1@" + self.digest, pinned)
        upgraded = updater.update_image(pinned, "v2", self.digest)
        self.assertIn("v2@" + self.digest, upgraded)

    def test_invalid_digest(self):
        with self.assertRaises(ValueError):
            updater.update_image(self.source, "v2", "sha256:placeholder")

    def test_duplicate_refused(self):
        with self.assertRaises(ValueError):
            updater.update_image(self.source * 2, "v1", self.digest)

    def test_unknown_image_refused(self):
        with self.assertRaises(ValueError):
            updater.update_image("image: something-else\n", "v1", self.digest)
