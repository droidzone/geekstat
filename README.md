# myopip-monitor

Charts for the sysstat files already on the production machine. It runs on the laptop, reads `sa` data over SSH, and serves a page on 127.0.0.1. Nothing is installed on the server. The `sa` files are only read.

sysstat there writes a file every few minutes under `/var/log/sysstat/` and keeps 60 days (`HISTORY=60`). This program asks that host's own `sadf` to decode them. `sadf -T` prints timestamps in the server's current timezone, which is Asia/Kolkata, including files recorded while the host was still set to UTC.

## Requirements

Python 3.9 or newer. The standard library is enough; there is nothing to pip install.

You also need the OpenSSH client, and an SSH config alias that logs in without a prompt. The one this was written against is `myopip`.

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

`--check` prints the dates that have `sa` files and exits. Otherwise open:

```text
http://127.0.0.1:8765
```

Use that address. On macOS, `localhost` may try IPv6, and this process does not listen on `::1`.

`python3 -m sarview --demo` serves a built-in day and does not open SSH. `make run`, `make check`, `make demo`, and `make test` are the same commands.

## Configuration

You can run it with no config file. Defaults match `sarview.conf.example`: host `myopip`, port `8765`, cache under `~/.cache/myopip-monitor`, sysstat directory `/var/log/sysstat`.

To change any of that, copy the example and edit it:

```bash
cp sarview.conf.example sarview.conf
```

The file next to the code is picked up automatically. `~/.config/myopip-monitor/sarview.conf` is the other place it looks. A flag such as `--port` wins over `SARVIEW_PORT`, which wins over the file.

The `[viewer]` section is how you drop a chart, change the shortcut buttons, set the window a date opens on, and choose when a readout turns red. All of the keys, and what each one actually does, are in [docs/configuration.md](docs/configuration.md).

## Using the charts

Pick a date from the files that exist. Set From and To, or drag across a chart. `08:00:00` to `08:15:00` keeps every sample in that window, including one timestamped a few seconds after 08:15, because that is how sar labels the interval. The points are not averaged into a grid. A day collected every 10 minutes stays at 10 minutes.

CPU, memory, swap, load, disk, and network share one time cursor. The readout shows CPU and memory for that sample. Pin this moment keeps one sample on screen while you hover another. The peak buttons jump to the busiest sample in the window. Arrow keys step one sample at a time. The table under the charts is the same raw values.

Idle is in the CPU chart but hidden at first, because it is usually near 100% and flattens the other series. Click idle in the legend to show the 0 to 100 scale. `hide_idle` in the config file changes that starting state.

The address bar stores the date and the time window, so a link reopens the same stretch.

## Cache

Decoded `sadf` JSON is stored under `~/.cache/myopip-monitor/<host>/`, unless you set another directory. A repeated view of the same day does not run `sadf` again while the file size and mtime are unchanged.

Within the catalog TTL (two minutes by default), opening the same day does not SSH at all. After that, one short listing checks whether any `sa` file grew. Unchanged files stay cached. Today's file changes as sysstat appends samples, so a later refresh decodes it once more. Refresh on the page forces that listing immediately.

The status line says whether the samples came from the local cache, from a directory check, or from a fresh `sadf` decode.

```bash
rm -rf ~/.cache/myopip-monitor
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use a recorded `sadf` document and the built-in demo day. They do not contact the server. They cover timezone conversion into Asia/Kolkata, merging `saDD` and `saYYYYMMDD` files, raw time windows, cache hits, the config file, and the loopback HTTP API.
