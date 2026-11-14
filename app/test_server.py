import http.client
import threading
import unittest
from http.server import HTTPServer

from server import make_handler


class ServerTests(unittest.TestCase):
    def request(self, version, path, method="GET"):
        with HTTPServer(("127.0.0.1", 0), make_handler(version)) as server:
            worker = threading.Thread(target=server.handle_request)
            worker.start()
            connection = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                connection.request(method, path)
                response = connection.getresponse()
                result = response.status, response.read(), response.getheaders()
            finally:
                connection.close()
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            return result

    def test_release_responses(self):
        for version in ("v1", "v2"):
            with self.subTest(version=version):
                status, body, headers = self.request(version, "/")
                self.assertEqual((status, body), (200, f"gitops-lab {version}\n".encode()))
                self.assertIn(("Content-Length", str(len(body))), headers)

    def test_probes(self):
        for path in ("/readyz", "/healthz"):
            self.assertEqual(self.request("v1", path)[:2], (200, b"ok\n"))

    def test_not_found(self):
        self.assertEqual(self.request("v1", "/missing")[:2], (404, b"not found\n"))

    def test_head(self):
        status, body, headers = self.request("v2", "/", "HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertIn(("Content-Length", "14"), headers)

    def test_invalid_release(self):
        with self.assertRaises(ValueError):
            make_handler("latest")


if __name__ == "__main__":
    unittest.main()
