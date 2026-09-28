import unittest

from sarview.errors import SarviewError
from sarview.source import catalog_script, fetch_script, parse_catalog_output, ssh_argv
from sarview.tz import covered_local_dates
from sarview.validate import validate_bind, validate_filename, validate_host, validate_sa_dir
from zoneinfo import ZoneInfo


class SourceTests(unittest.TestCase):
    def test_ssh_uses_the_alias_and_batch_mode(self):
        argv = ssh_argv("myopip")
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertNotIn("StrictHostKeyChecking=no", argv)
        self.assertEqual(argv[-2:], ["bash", "-s"])
        self.assertEqual(argv[argv.index("bash") - 1], "myopip")

    def test_host_and_path_injection_is_rejected(self):
        for host in ("", "-oProxyCommand=x", "myopip;rm", "host name"):
            with self.assertRaises(SarviewError):
                validate_host(host)
        for name in ("sa27;id", "../sa27", "sar27", "sa27'", "sa20260928.xz;ls"):
            with self.assertRaises(SarviewError):
                validate_filename(name)
        for path in ("/var/log/sysstat;rm", "/tmp/../etc", "var/log/sysstat", ""):
            with self.assertRaises(SarviewError):
                validate_sa_dir(path)
        with self.assertRaises(SarviewError):
            validate_bind("0.0.0.0")
        self.assertEqual(validate_bind("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_filename("sa20260928.xz"), "sa20260928.xz")

    def test_fetch_script_uses_sadf_local_time(self):
        script = fetch_script("/var/log/sysstat", ["sa27", "sa20260928"])
        self.assertIn("sadf -j -T '/var/log/sysstat/sa27'", script)
        self.assertIn("sadf -j -T '/var/log/sysstat/sa20260928'", script)
        self.assertIn("-- -u ALL -r ALL -S -q -d -n DEV", script)
        with self.assertRaises(SarviewError):
            fetch_script("/var/log/sysstat", ["sa27;rm -rf /"])

    def test_catalog_parser_reads_headers_and_skips_failures(self):
        text = """@@META Asia/Kolkata +0530 myopip
@@FILE sa27 155076 1790553001
{"sysstat":{"hosts":[{"file-date":"2026-09-27","timezone":"UTC"}]}}
@@ENDFILE
@@FILE sa99 4 10
@@ERROR header-failed
@@ENDFILE
"""
        probe = parse_catalog_output(text)
        self.assertEqual(probe.timezone, "Asia/Kolkata")
        self.assertEqual(probe.utc_offset, "+0530")
        self.assertEqual(probe.hostname, "myopip")
        self.assertEqual(len(probe.files), 1)
        self.assertEqual(probe.files[0].name, "sa27")
        self.assertEqual(probe.files[0].file_date, "2026-09-27")
        self.assertEqual(probe.warnings, ["sa99: could not read the sadf header"])
        self.assertIn("sadf -j -H", catalog_script("/var/log/sysstat"))

    def test_kolkata_file_coverage(self):
        zone = ZoneInfo("Asia/Kolkata")
        self.assertEqual(
            covered_local_dates("2026-09-27", "UTC", 1790553001, "sa27", zone),
            {"2026-09-27", "2026-09-28"},
        )
        self.assertEqual(
            covered_local_dates("2026-09-28", "UTC", 1790563201, "sa28", zone),
            {"2026-09-28"},
        )
        self.assertEqual(
            covered_local_dates("2026-09-27", "UTC", 1, "sa20260927.xz", zone),
            {"2026-09-27", "2026-09-28"},
        )


if __name__ == "__main__":
    unittest.main()
