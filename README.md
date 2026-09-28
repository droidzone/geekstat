# Geekstat

Geekstat, by [Geekmaze](https://geekmaze.com), is a simple sysstat viewer. It runs on macOS, Windows, and Linux, reads the `sa` files already on a server over SSH, and draws the original samples in a browser. Nothing is installed on the server. There is no collector, database, or agent. The `sa` files are only read.

sysstat there writes a file every few minutes under `/var/log/sysstat/` and keeps 60 days (`HISTORY=60`). This program asks that host's own `sadf` to decode them. `sadf -T` prints timestamps in the server's current timezone, which is Asia/Kolkata, including files recorded while the host was still set to UTC.

## Requirements

Python 3.9 or newer. The standard library is enough; there is nothing to pip install. The same command runs on macOS, Windows, and Linux.

You also need the OpenSSH client, and an SSH config alias that logs in without a prompt. The one this was written against is `myopip`. macOS already includes OpenSSH. On Windows, install the OpenSSH Client optional feature. On Linux, install `openssh-client`.

```bash
ssh -o BatchMode=yes myopip true
```

If that asks for a password or a key passphrase, load the key into `ssh-agent` first. Over SSH the program lists `/var/log/sysstat`, reads file sizes and mtimes, asks for the timezone, and runs `sadf`.

## Run

From this directory:

```bash
python3 -m sarview --check
python3 -m sarview
```

On Windows, `py -m sarview` or `python -m sarview` is the same thing when `python3` is not on PATH.

`--check` prints the dates that have `sa` files and exits. Otherwise open:

```text
http://127.0.0.1:8765
```

Use that address. On macOS and Windows, `localhost` may try IPv6, and this process does not listen on `::1`.

`python3 -m sarview --demo` serves a built-in day and does not open SSH. `make run`, `make check`, `make demo`, and `make test` are the same commands.

## Configuration

You can run it with no config file. Defaults match `sarview.conf.example`: host `myopip`, port `8765`, sysstat directory `/var/log/sysstat`, and a cache folder chosen for the operating system (see Cache).

To change any of that, copy the example and edit it:

```bash
cp sarview.conf.example sarview.conf
```

The file next to the code is picked up automatically. The other place it looks is:

- macOS: `~/Library/Application Support/Geekstat/sarview.conf`
- Windows: `%APPDATA%\Geekstat\sarview.conf`
- Linux: `~/.config/geekstat/sarview.conf` (or `$XDG_CONFIG_HOME/geekstat/sarview.conf`)

A flag such as `--port` wins over `SARVIEW_PORT`, which wins over the file.

The `[viewer]` section is how you drop a chart, change the shortcut buttons, set the window a date opens on, and choose when a readout turns red. All of the keys, and what each one actually does, are in [docs/configuration.md](docs/configuration.md).

## Using the charts

Pick a date from the files that exist. Set From and To, or drag across a chart. `08:00:00` to `08:15:00` keeps every sample in that window, including one timestamped a few seconds after 08:15, because that is how sar labels the interval. The points are not averaged into a grid. A day collected every 10 minutes stays at 10 minutes.

CPU, memory, swap, load, disk, and network share one time cursor. The readout shows CPU and memory for that sample. Pin this moment keeps one sample on screen while you hover another. The peak buttons jump to the busiest sample in the window. Arrow keys step one sample at a time. The table under the charts is the same raw values.

Idle is in the CPU chart but hidden at first, because it is usually near 100% and flattens the other series. Click idle in the legend to show the 0 to 100 scale. `hide_idle` in the config file changes that starting state.

The address bar stores the date and the time window, so a link reopens the same stretch.

## Cache

Decoded `sadf` JSON is stored under a per-user cache directory, unless you set another one:

- macOS: `~/Library/Caches/Geekstat/<host>/`
- Windows: `%LOCALAPPDATA%\Geekstat\<host>\`
- Linux: `~/.cache/geekstat/<host>/` (or `$XDG_CACHE_HOME/geekstat/<host>/`)

A repeated view of the same day does not run `sadf` again while the file size and mtime are unchanged.

Within the catalog TTL (two minutes by default), opening the same day does not SSH at all. After that, one short listing checks whether any `sa` file grew. Unchanged files stay cached. Today's file changes as sysstat appends samples, so a later refresh decodes it once more. Refresh on the page forces that listing immediately.

The status line says whether the samples came from the local cache, from a directory check, or from a fresh `sadf` decode.

Delete that cache directory when you want a clean copy. On Linux that is `rm -rf ~/.cache/geekstat`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use a recorded `sadf` document and the built-in demo day. They do not contact the server. They cover timezone conversion into Asia/Kolkata, merging `saDD` and `saYYYYMMDD` files, raw time windows, cache hits, the config file, and the loopback HTTP API.

## License

Geekstat is free to use, copy, and modify, including inside an organization. You may not sell it, and you may not rebrand it or remove the Geekmaze name and the links to [geekmaze.com](https://geekmaze.com). The terms are in [LICENSE](LICENSE).
