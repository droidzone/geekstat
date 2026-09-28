import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from sarview.cache import DiskCache
from sarview.demo import DemoSource
from sarview.errors import SarviewError
from sarview.server import make_server
from sarview.service import MonitorService


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        service = MonitorService(
            DemoSource(),
            DiskCache(Path(self.directory.name), "demo"),
            log=lambda *_args, **_kwargs: None,
        )
        self.httpd = make_server(service, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.directory.cleanup()

    def test_server_is_loopback_and_serves_the_viewer(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")
        with self.assertRaises(SarviewError):
            make_server(object(), port=0, bind="0.0.0.0")
        page = urlopen(self.base + "/", timeout=5)
        body = page.read().decode()
        self.assertIn("Sysstat history", body)
        self.assertEqual(page.status, 200)
        try:
            urlopen(self.base + "/../sarview/cli.py", timeout=5)
        except HTTPError as exc:
            self.assertEqual(exc.code, 404)
        else:
            self.fail("path traversal was served")

    def test_settings_are_served_with_the_page(self):
        settings = json.load(urlopen(self.base + "/api/settings", timeout=5))
        self.assertEqual(settings["title"], "Sysstat history")
        self.assertEqual(settings["charts"][0], "cpu")
        self.assertTrue(settings["hide_idle"])
        self.assertEqual(settings["ranges"][-1]["span"], "day")
        self.assertNotIn("host", settings)

    def test_day_api_returns_raw_window(self):
        health = json.load(urlopen(self.base + "/api/health", timeout=5))
        self.assertEqual(health["bind"], "127.0.0.1")
        catalog = json.load(urlopen(self.base + "/api/catalog", timeout=5))
        self.assertEqual(catalog["dates"], ["2026-09-28"])
        day = json.load(urlopen(self.base + "/api/day?date=2026-09-28&start=08:00:00&end=08:15:00", timeout=5))
        self.assertEqual([sample["cpu"]["user"] for sample in day["samples"]], [4.0, 72.0, 72.0, 72.0])
        self.assertTrue(day["samples"][1]["iso"].endswith("+05:30"))
        try:
            urlopen(self.base + "/api/day?date=2026-13-40", timeout=5)
        except HTTPError as exc:
            self.assertEqual(exc.code, 400)
            payload = json.loads(exc.read().decode())
            self.assertIn("invalid date", payload["error"])
        else:
            self.fail("invalid date was accepted")


if __name__ == "__main__":
    unittest.main()
