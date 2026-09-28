import tempfile
import unittest
from pathlib import Path

from sarview.config import load_settings, viewer_payload
from sarview.errors import SarviewError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "sarview.conf.example"


class ConfigTests(unittest.TestCase):
    def test_example_file_matches_the_built_in_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory)
            settings = load_settings(cli={"config": str(EXAMPLE)}, env={}, cwd=empty, home=empty)
        self.assertEqual(settings.host, "myopip")
        self.assertEqual(settings.port, 8765)
        self.assertEqual(settings.sa_dir, "/var/log/sysstat")
        self.assertEqual(settings.catalog_ttl, 120)
        self.assertEqual(settings.connect_timeout, 20)
        self.assertEqual(settings.catalog_timeout, 60)
        self.assertEqual(settings.fetch_timeout, 180)
        self.assertTrue(str(settings.cache_dir).endswith("/.cache/myopip-monitor"))
        self.assertEqual(settings.charts, ("cpu", "memory", "swap", "load", "disk", "network"))
        self.assertTrue(settings.hide_idle)
        self.assertEqual(settings.default_from, "00:00:00")
        self.assertEqual(settings.default_to, "23:59:00")
        self.assertEqual(settings.ranges[-1], ("Full day", "day"))
        self.assertEqual(settings.hot_ram, 80.0)
        self.assertEqual(settings.table_open_below, 24)
        payload = viewer_payload(settings)
        self.assertEqual(payload["ranges"][0], {"label": "15m", "span": "900"})
        self.assertNotIn("host", payload)

    def test_file_then_environment_then_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            cwd = root / "work"
            home.mkdir()
            cwd.mkdir()
            (cwd / "sarview.conf").write_text(
                "\n".join(
                    [
                        "[ssh]",
                        "host = clinic",
                        "connect_timeout = 5",
                        "[server]",
                        "port = 9000",
                        "[viewer]",
                        "title = Clinic load",
                        "charts = cpu, load",
                        "hide_idle = no",
                        "default_from = 08:00",
                        "default_to = 14:00:00",
                        "ranges = 15m=900, Morning=day",
                        "hot_user = 70",
                        "table_open_below = 0",
                    ]
                ),
                encoding="utf-8",
            )
            (home / ".config").mkdir(parents=True)
            from_file = load_settings(env={}, cwd=cwd, home=home)
            self.assertEqual(from_file.host, "clinic")
            self.assertEqual(from_file.port, 9000)
            self.assertEqual(from_file.connect_timeout, 5)
            self.assertEqual(from_file.title, "Clinic load")
            self.assertEqual(from_file.charts, ("cpu", "load"))
            self.assertFalse(from_file.hide_idle)
            self.assertEqual(from_file.default_from, "08:00:00")
            self.assertEqual(from_file.ranges, (("15m", "900"), ("Morning", "day")))
            self.assertEqual(from_file.table_open_below, 0)
            self.assertEqual(from_file.path, str(cwd / "sarview.conf"))

            from_env = load_settings(env={"SARVIEW_PORT": "8765", "SARVIEW_HOST": "other"}, cwd=cwd, home=home)
            self.assertEqual(from_env.port, 8765)
            self.assertEqual(from_env.host, "other")
            self.assertEqual(from_env.title, "Clinic load")

            from_cli = load_settings(
                cli={"port": 9001, "host": "myopip"},
                env={"SARVIEW_PORT": "8765", "SARVIEW_HOST": "other"},
                cwd=cwd,
                home=home,
            )
            self.assertEqual(from_cli.port, 9001)
            self.assertEqual(from_cli.host, "myopip")

    def test_cwd_file_beats_the_home_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cwd = root / "work"
            home = root / "home"
            cwd.mkdir()
            config_home = home / ".config" / "myopip-monitor"
            config_home.mkdir(parents=True)
            (cwd / "sarview.conf").write_text("[server]\nport = 9000\n", encoding="utf-8")
            (config_home / "sarview.conf").write_text("[server]\nport = 9001\n", encoding="utf-8")
            settings = load_settings(env={}, cwd=cwd, home=home)
            self.assertEqual(settings.port, 9000)
            self.assertEqual(settings.path, str(cwd / "sarview.conf"))

    def test_bad_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory)
            missing = empty / "nope.conf"
            with self.assertRaises(SarviewError):
                load_settings(cli={"config": str(missing)}, env={}, cwd=empty, home=empty)
            bad = empty / "sarview.conf"
            for text in (
                "[viewer]\ncharts = cpu, cpu\n",
                "[viewer]\ncharts = temperature\n",
                "[viewer]\ndefault_from = 18:00\ndefault_to = 08:00\n",
                "[viewer]\nhide_idle = maybe\n",
                "[ssh]\nhost = bad host\n",
                "[extra]\nport = 1\n",
                "[server]\nlisten = 1\n",
            ):
                bad.write_text(text, encoding="utf-8")
                with self.assertRaises(SarviewError):
                    load_settings(env={}, cwd=empty, home=empty)


if __name__ == "__main__":
    unittest.main()
