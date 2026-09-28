"""Read sarview.conf. Flags beat environment variables, which beat the file."""

from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sarview.errors import SarviewError
from sarview.validate import validate_host, validate_port, validate_sa_dir
from sarview.window import parse_clock, window_bounds

CHARTS = ("cpu", "memory", "swap", "load", "disk", "network")
PRODUCT = "Geekstat"


def default_cache_dir(home: Path | None = None, platform: str | None = None, env=None) -> str:
    """Decoded sadf JSON for this operating system."""
    system = platform or sys.platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if system == "win32":
        base = str(env.get("LOCALAPPDATA") or "").strip()
        root = Path(base) if base else home / "AppData" / "Local"
        return str(root / PRODUCT)
    if system == "darwin":
        return str(home / "Library" / "Caches" / PRODUCT)
    base = str(env.get("XDG_CACHE_HOME") or "").strip()
    root = Path(base) if base else home / ".cache"
    return str(root / "geekstat")


def user_config_file(home: Path, platform: str | None = None, env=None) -> Path:
    """Per-user sarview.conf for this operating system."""
    system = platform or sys.platform
    env = os.environ if env is None else env
    home = Path(home)
    if system == "win32":
        base = str(env.get("APPDATA") or "").strip()
        root = Path(base) if base else home / "AppData" / "Roaming"
        return root / PRODUCT / "sarview.conf"
    if system == "darwin":
        return home / "Library" / "Application Support" / PRODUCT / "sarview.conf"
    base = str(env.get("XDG_CONFIG_HOME") or "").strip()
    root = Path(base) if base else home / ".config"
    return root / "geekstat" / "sarview.conf"

_SECTIONS = {
    "ssh": {"host", "sa_dir", "connect_timeout", "catalog_timeout", "fetch_timeout"},
    "server": {"port"},
    "cache": {"dir", "catalog_ttl"},
    "viewer": {
        "title",
        "charts",
        "hide_idle",
        "default_from",
        "default_to",
        "ranges",
        "hot_user",
        "hot_iowait",
        "hot_ram",
        "hot_swap",
        "table_open_below",
    },
}


@dataclass
class Settings:
    host: str = "myopip"
    port: int = 8765
    sa_dir: str = "/var/log/sysstat"
    cache_dir: str = field(default_factory=default_cache_dir)
    catalog_ttl: int = 120
    connect_timeout: int = 20
    catalog_timeout: int = 60
    fetch_timeout: int = 180
    title: str = PRODUCT
    charts: tuple = CHARTS
    hide_idle: bool = True
    default_from: str = "00:00:00"
    default_to: str = "23:59:00"
    ranges: tuple = (
        ("15m", "900"),
        ("1h", "3600"),
        ("6h", "21600"),
        ("Full day", "day"),
    )
    hot_user: float = 50.0
    hot_iowait: float = 5.0
    hot_ram: float = 80.0
    hot_swap: float = 10.0
    table_open_below: int = 24
    path: str | None = None


def load_settings(cli=None, env=None, cwd=None, home=None) -> Settings:
    cli = cli or {}
    if env is None:
        env = os.environ
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    home = Path(home) if home is not None else Path.home()
    path = locate_config(cli.get("config"), env, cwd, home)
    settings = Settings()
    if path is not None:
        apply_file(settings, path)
        settings.path = str(path)
    apply_env(settings, env)
    apply_cli(settings, cli)
    return settings


def locate_config(explicit, env, cwd: Path, home: Path) -> Path | None:
    if explicit:
        return _existing(Path(str(explicit)).expanduser())
    named = _blank(env.get("SARVIEW_CONFIG"))
    if named:
        return _existing(Path(named).expanduser())
    local = cwd / "sarview.conf"
    if local.is_file():
        return local
    user = user_config_file(home, env=env)
    if user.is_file():
        return user
    return None


def apply_file(settings: Settings, path: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        read = parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise SarviewError(f"could not read {path}: {exc}") from exc
    if not read:
        raise SarviewError(f"could not read {path}")
    for section in parser.sections():
        if section not in _SECTIONS:
            raise SarviewError(f"unknown section [{section}] in {path.name}")
        allowed = _SECTIONS[section]
        for key in parser.options(section):
            if key not in allowed:
                raise SarviewError(f"unknown setting {section}.{key} in {path.name}")
    if parser.has_section("ssh"):
        _set(parser, "ssh", "host", lambda value: setattr(settings, "host", validate_host(value.strip())))
        _set(parser, "ssh", "sa_dir", lambda value: setattr(settings, "sa_dir", validate_sa_dir(value.strip())))
        _set(parser, "ssh", "connect_timeout", lambda value: setattr(settings, "connect_timeout", _span(value, "connect_timeout")))
        _set(parser, "ssh", "catalog_timeout", lambda value: setattr(settings, "catalog_timeout", _span(value, "catalog_timeout")))
        _set(parser, "ssh", "fetch_timeout", lambda value: setattr(settings, "fetch_timeout", _span(value, "fetch_timeout")))
    if parser.has_section("server"):
        _set(parser, "server", "port", lambda value: setattr(settings, "port", validate_port(_int(value, "port"))))
    if parser.has_section("cache"):
        _set(parser, "cache", "dir", lambda value: setattr(settings, "cache_dir", _cache_dir(value)))
        _set(parser, "cache", "catalog_ttl", lambda value: setattr(settings, "catalog_ttl", _nonneg(value, "catalog_ttl")))
    if parser.has_section("viewer"):
        _set(parser, "viewer", "title", lambda value: setattr(settings, "title", _title(value)))
        _set(parser, "viewer", "charts", lambda value: setattr(settings, "charts", _charts(value)))
        if parser.has_option("viewer", "hide_idle"):
            try:
                settings.hide_idle = parser.getboolean("viewer", "hide_idle")
            except ValueError as exc:
                raise SarviewError("hide_idle must be yes or no") from exc
        _set(parser, "viewer", "default_from", lambda value: setattr(settings, "default_from", _clock(value)))
        _set(parser, "viewer", "default_to", lambda value: setattr(settings, "default_to", _clock(value)))
        if parser.has_option("viewer", "default_from") or parser.has_option("viewer", "default_to"):
            window_bounds(settings.default_from, settings.default_to)
        _set(parser, "viewer", "ranges", lambda value: setattr(settings, "ranges", _ranges(value)))
        _set(parser, "viewer", "hot_user", lambda value: setattr(settings, "hot_user", _percent(value, "hot_user")))
        _set(parser, "viewer", "hot_iowait", lambda value: setattr(settings, "hot_iowait", _percent(value, "hot_iowait")))
        _set(parser, "viewer", "hot_ram", lambda value: setattr(settings, "hot_ram", _percent(value, "hot_ram")))
        _set(parser, "viewer", "hot_swap", lambda value: setattr(settings, "hot_swap", _percent(value, "hot_swap")))
        _set(
            parser,
            "viewer",
            "table_open_below",
            lambda value: setattr(settings, "table_open_below", _nonneg(value, "table_open_below", 10000)),
        )


def apply_env(settings: Settings, env) -> None:
    host = _blank(env.get("SARVIEW_HOST"))
    if host:
        settings.host = validate_host(host)
    port = _blank(env.get("SARVIEW_PORT"))
    if port:
        settings.port = validate_port(_int(port, "SARVIEW_PORT"))
    cache = _blank(env.get("SARVIEW_CACHE"))
    if cache:
        settings.cache_dir = _cache_dir(cache)
    sa_dir = _blank(env.get("SARVIEW_SA_DIR"))
    if sa_dir:
        settings.sa_dir = validate_sa_dir(sa_dir)
    ttl = _blank(env.get("SARVIEW_CATALOG_TTL"))
    if ttl:
        settings.catalog_ttl = _nonneg(ttl, "SARVIEW_CATALOG_TTL")


def apply_cli(settings: Settings, cli) -> None:
    if cli.get("host"):
        settings.host = validate_host(str(cli["host"]).strip())
    if cli.get("port") is not None:
        settings.port = validate_port(_int(cli["port"], "port"))
    if cli.get("cache_dir"):
        settings.cache_dir = _cache_dir(str(cli["cache_dir"]))
    if cli.get("sa_dir"):
        settings.sa_dir = validate_sa_dir(str(cli["sa_dir"]).strip())
    if cli.get("catalog_ttl") is not None:
        settings.catalog_ttl = _nonneg(cli["catalog_ttl"], "catalog_ttl")


def viewer_payload(settings: Settings) -> dict:
    return {
        "title": settings.title,
        "charts": list(settings.charts),
        "hide_idle": settings.hide_idle,
        "default_from": settings.default_from,
        "default_to": settings.default_to,
        "ranges": [{"label": label, "span": span} for label, span in settings.ranges],
        "hot_user": settings.hot_user,
        "hot_iowait": settings.hot_iowait,
        "hot_ram": settings.hot_ram,
        "hot_swap": settings.hot_swap,
        "table_open_below": settings.table_open_below,
    }


def _set(parser, section, key, apply) -> None:
    if parser.has_option(section, key):
        apply(parser.get(section, key))


def _existing(path: Path) -> Path:
    if not path.is_file():
        raise SarviewError(f"config file not found: {path}")
    return path


def _blank(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value, key: str) -> int:
    if isinstance(value, bool):
        raise SarviewError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SarviewError(f"{key} must be an integer") from exc


def _nonneg(value, key: str, limit: int = 86400) -> int:
    number = _int(value, key)
    if not 0 <= number <= limit:
        raise SarviewError(f"{key} must be between 0 and {limit}")
    return number


def _span(value, key: str) -> int:
    number = _int(value, key)
    if not 1 <= number <= 3600:
        raise SarviewError(f"{key} must be between 1 and 3600 seconds")
    return number


def _percent(value, key: str) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise SarviewError(f"{key} must be a number") from exc
    if not 0 <= number <= 100:
        raise SarviewError(f"{key} must be between 0 and 100")
    return number


def _cache_dir(value: str) -> str:
    text = value.strip()
    if not text:
        raise SarviewError("cache dir is empty")
    return str(Path(text).expanduser())


def _title(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        raise SarviewError("title is empty")
    if len(text) > 80:
        raise SarviewError("title is longer than 80 characters")
    return text


def _clock(value: str) -> str:
    hour, minute, second = parse_clock(value)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _charts(value: str) -> tuple:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise SarviewError("charts is empty")
    unknown = [name for name in names if name not in CHARTS]
    if unknown:
        raise SarviewError(f"unknown chart {unknown[0]!r}")
    if len(names) != len(set(names)):
        raise SarviewError("charts lists the same panel twice")
    return tuple(names)


def _ranges(value: str) -> tuple:
    items = []
    for part in value.replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SarviewError(f"bad range {part!r}; use label=seconds or label=day")
        label, span = part.split("=", 1)
        label = " ".join(label.split())
        span = span.strip()
        if not label:
            raise SarviewError("a range is missing its label")
        if span != "day":
            seconds = _int(span, f"range {label}")
            if not 1 <= seconds <= 86400:
                raise SarviewError(f"range {label} must be between 1 and 86400 seconds, or day")
            span = str(seconds)
        items.append((label, span))
    if not items:
        raise SarviewError("ranges is empty")
    return tuple(items)
