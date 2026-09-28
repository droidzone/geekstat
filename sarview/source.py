"""Read sysstat files over the user's existing SSH configuration."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from sarview.errors import SarviewError
from sarview.validate import validate_filename, validate_host, validate_offset, validate_sa_dir

_CATALOG = r"""
export LC_ALL=C
sa_dir='__SA_DIR__'
if [ ! -d "$sa_dir" ]; then
  echo '@@FATAL sysstat directory is missing' >&2
  exit 1
fi
if ! command -v sadf >/dev/null 2>&1; then
  echo '@@FATAL sadf is not installed on the server' >&2
  exit 1
fi
tz=$(timedatectl show -p Timezone --value 2>/dev/null || true)
if [ -z "$tz" ]; then
  tz=$(cat /etc/timezone 2>/dev/null || echo UTC)
fi
off=$(date +%z)
hn=$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo host)
printf '@@META %s %s %s\n' "$tz" "$off" "$hn"
shopt -s nullglob
paths=(
  "$sa_dir"/sa[0-9][0-9]
  "$sa_dir"/sa[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]
  "$sa_dir"/sa[0-9][0-9].xz
  "$sa_dir"/sa[0-9][0-9].gz
  "$sa_dir"/sa[0-9][0-9].bz2
  "$sa_dir"/sa[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].xz
  "$sa_dir"/sa[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].gz
  "$sa_dir"/sa[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].bz2
)
if [ ${#paths[@]} -gt 0 ]; then
  mapfile -t paths < <(printf '%s\n' "${paths[@]}" | LC_ALL=C sort)
fi
for path in "${paths[@]}"; do
  [ -f "$path" ] || continue
  name=$(basename "$path")
  size=$(stat -c '%s' "$path")
  mtime=$(stat -c '%Y' "$path")
  printf '@@FILE %s %s %s\n' "$name" "$size" "$mtime"
  if ! sadf -j -H "$path"; then
    printf '\n@@ERROR header-failed\n'
  fi
  printf '\n@@ENDFILE\n'
done
"""


@dataclass
class RemoteFile:
    name: str
    size: int
    mtime: int
    file_date: str
    file_timezone: str


@dataclass
class Probe:
    timezone: str
    utc_offset: str
    hostname: str
    files: list[RemoteFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SshSarSource:
    """Run sadf on the server. The sa files stay where sysstat wrote them."""

    remote = True

    def __init__(
        self,
        host: str,
        sa_dir: str = "/var/log/sysstat",
        run=None,
        connect_timeout: int = 20,
        catalog_timeout: int = 60,
        fetch_timeout: int = 180,
    ):
        self.host = validate_host(host)
        self.sa_dir = validate_sa_dir(sa_dir)
        self.connect_timeout = connect_timeout
        self.catalog_timeout = catalog_timeout
        self.fetch_timeout = fetch_timeout
        self._run = run or self._ssh

    def probe(self) -> Probe:
        text = self._run(catalog_script(self.sa_dir), self.catalog_timeout)
        return parse_catalog_output(text)

    def fetch_files(self, names: list[str]) -> dict[str, dict]:
        if not names:
            return {}
        text = self._run(fetch_script(self.sa_dir, names), self.fetch_timeout)
        return parse_fetch_output(text, names)

    def _ssh(self, script: str, timeout: int) -> str:
        try:
            completed = subprocess.run(
                ssh_argv(self.host, self.connect_timeout),
                input=script,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SarviewError("timed out talking to the server", status=502) from exc
        except FileNotFoundError as exc:
            raise SarviewError(
                "ssh was not found on PATH. Install OpenSSH "
                "(included on macOS and recent Windows; openssh-client on Linux).",
                status=502,
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "ssh failed").strip()
            raise SarviewError(detail[:1500], status=502)
        if "@@FATAL" in completed.stderr or "@@FATAL" in completed.stdout:
            detail = (completed.stderr or completed.stdout).strip()
            raise SarviewError(detail[:1500], status=502)
        return completed.stdout


def ssh_argv(host: str, connect_timeout: int = 20) -> list[str]:
    host = validate_host(host)
    return [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={int(connect_timeout)}",
        host,
        "bash",
        "-s",
    ]


def catalog_script(sa_dir: str) -> str:
    sa_dir = validate_sa_dir(sa_dir)
    return _CATALOG.replace("__SA_DIR__", sa_dir)


def fetch_script(sa_dir: str, names: list[str]) -> str:
    sa_dir = validate_sa_dir(sa_dir)
    parts = ["export LC_ALL=C", "if ! command -v sadf >/dev/null 2>&1; then echo '@@FATAL sadf is not installed on the server' >&2; exit 1; fi"]
    for name in names:
        name = validate_filename(name)
        parts.append(
            "\n".join(
                [
                    f"printf '@@FILE %s\\n' '{name}'",
                    f"if ! sadf -j -T '{sa_dir}/{name}' -- -u ALL -r ALL -S -q -d -n DEV; then",
                    "  printf '\\n@@ERROR sadf-failed\\n'",
                    "fi",
                    "printf '\\n@@ENDFILE\\n'",
                ]
            )
        )
    return "\n".join(parts) + "\n"


def parse_catalog_output(text: str) -> Probe:
    timezone_name = ""
    offset = ""
    hostname = ""
    files: list[RemoteFile] = []
    warnings: list[str] = []
    saw_meta = False
    for header, body, error in _sections(text):
        if header is None:
            continue
        if header.startswith("META "):
            saw_meta = True
            bits = header.split()
            if len(bits) < 3:
                raise SarviewError("server timezone probe was incomplete", status=502)
            timezone_name = bits[1]
            offset = validate_offset(bits[2])
            hostname = bits[3] if len(bits) > 3 else "host"
            continue
        if not header.startswith("FILE "):
            continue
        bits = header.split()
        if len(bits) != 4:
            warnings.append(f"ignored a malformed file record: {header}")
            continue
        name, size_s, mtime_s = bits[1], bits[2], bits[3]
        try:
            name = validate_filename(name)
        except SarviewError:
            warnings.append(f"ignored unexpected file {name}")
            continue
        if error:
            warnings.append(f"{name}: could not read the sadf header")
            continue
        try:
            document = _extract_json(body)
            host = document["sysstat"]["hosts"][0]
            file_date = host["file-date"]
            file_timezone = str(host.get("timezone") or "UTC")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, SarviewError) as exc:
            warnings.append(f"{name}: unreadable header ({exc})")
            continue
        files.append(
            RemoteFile(
                name=name,
                size=int(float(size_s)),
                mtime=int(float(mtime_s)),
                file_date=file_date,
                file_timezone=file_timezone,
            )
        )
    if not saw_meta:
        raise SarviewError("SSH session did not return a sysstat catalog", status=502)
    return Probe(timezone=timezone_name, utc_offset=offset, hostname=hostname, files=files, warnings=warnings)


def parse_fetch_output(text: str, names: list[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    failures: list[str] = []
    for header, body, error in _sections(text):
        if not header or not header.startswith("FILE "):
            continue
        name = header.split()[1]
        if error:
            failures.append(name)
            continue
        try:
            found[name] = _extract_json(body)
        except (json.JSONDecodeError, SarviewError):
            failures.append(name)
    missing = [name for name in names if name not in found]
    if missing or failures:
        failed = ", ".join(dict.fromkeys([*failures, *missing]))
        raise SarviewError(f"sadf failed for {failed}", status=502)
    return found


def _sections(text: str):
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("@@META "):
            yield line[2:], "", None
            index += 1
            continue
        if line.startswith("@@FILE "):
            header = line[2:]
            index += 1
            body: list[str] = []
            error = None
            while index < len(lines) and lines[index] != "@@ENDFILE":
                if lines[index].startswith("@@ERROR"):
                    error = lines[index]
                else:
                    body.append(lines[index])
                index += 1
            if index < len(lines) and lines[index] == "@@ENDFILE":
                index += 1
            yield header, "\n".join(body), error
            continue
        index += 1


def _extract_json(body: str) -> dict:
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise SarviewError("sadf did not return JSON", status=502)
    value = json.loads(body[start : end + 1])
    if not isinstance(value, dict):
        raise SarviewError("sadf JSON had an unexpected shape", status=502)
    return value
