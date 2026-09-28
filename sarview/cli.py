"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sarview import __version__
from sarview.cache import DiskCache
from sarview.config import load_settings, viewer_payload
from sarview.demo import DemoSource
from sarview.errors import SarviewError
from sarview.server import make_server
from sarview.service import MonitorService
from sarview.source import SshSarSource
from sarview.validate import BIND_HOST


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Geekstat, by Geekmaze. A simple sysstat viewer for macOS, Windows, and Linux. "
            "Reads sa files over SSH and serves charts on 127.0.0.1."
        )
    )
    parser.add_argument("--config", help="path to sarview.conf")
    parser.add_argument("--host", default=None, help="SSH config alias (default: myopip)")
    parser.add_argument("--port", type=int, default=None, help="loopback port (default: 8765)")
    parser.add_argument("--cache-dir", default=None, help="directory for decoded sadf JSON")
    parser.add_argument("--sa-dir", default=None, help="sysstat directory on the server")
    parser.add_argument("--catalog-ttl", type=int, default=None, help="seconds to reuse the file list")
    parser.add_argument("--demo", action="store_true", help="serve built-in sample data instead of SSH")
    parser.add_argument("--check", action="store_true", help="list available dates and exit")
    parser.add_argument("--version", action="version", version=f"Geekstat {__version__} by Geekmaze")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(
            cli={
                "config": args.config,
                "host": args.host,
                "port": args.port,
                "cache_dir": args.cache_dir,
                "sa_dir": args.sa_dir,
                "catalog_ttl": args.catalog_ttl,
            }
        )
        if args.demo:
            source = DemoSource()
            host_label = "demo"
        else:
            source = SshSarSource(
                settings.host,
                settings.sa_dir,
                connect_timeout=settings.connect_timeout,
                catalog_timeout=settings.catalog_timeout,
                fetch_timeout=settings.fetch_timeout,
            )
            host_label = source.host
        cache = DiskCache(Path(settings.cache_dir), host_label)
        service = MonitorService(source, cache, catalog_ttl=settings.catalog_ttl)
        if args.check:
            catalog = service.catalog_payload(refresh=True)
            print(f"host {catalog['host']}  timezone {catalog['timezone']} ({catalog['utc_offset']})")
            print(f"files {', '.join(catalog['files']) or '(none)'}")
            for day in catalog["dates"]:
                print(day)
            for warning in catalog["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
            return 0
        httpd = make_server(service, port=settings.port, bind=BIND_HOST, viewer=viewer_payload(settings))
    except SarviewError as exc:
        print(f"Geekstat: {exc}", file=sys.stderr)
        return 1

    url = f"http://{BIND_HOST}:{httpd.server_address[1]}"
    print(f"Geekstat {__version__}", flush=True)
    print("  by Geekmaze  https://geekmaze.com", flush=True)
    print(f"  {url}", flush=True)
    print(f"  host: {host_label}", flush=True)
    print(f"  cache: {cache.root}", flush=True)
    print(f"  config: {settings.path or 'built-in defaults'}", flush=True)
    print("  bind: 127.0.0.1 only", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
    return 0
