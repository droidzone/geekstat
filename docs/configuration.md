# Configuration

sarview runs with built-in defaults if you never create a config file. Those defaults are the same values as `sarview.conf.example`. Copy that file when you want to change something and keep the change.

```bash
cp sarview.conf.example sarview.conf
```

or, if you would rather not keep it next to the code:

```bash
mkdir -p ~/.config/myopip-monitor
cp sarview.conf.example ~/.config/myopip-monitor/sarview.conf
```

On startup the process looks in this order and stops at the first file it finds:

1. `--config /path/to/sarview.conf`, or `SARVIEW_CONFIG` if you did not pass `--config`
2. `./sarview.conf` in the directory you started it from
3. `~/.config/myopip-monitor/sarview.conf`

`sarview.conf` is for this machine. It is listed in `.gitignore`. The example file is the one that belongs in git.

A setting you pass on the command line wins. An environment variable wins over the file. Anything you leave out of the file keeps the built-in default.

```bash
# file says port = 9000
# this still listens on 8765
SARVIEW_PORT=8765 python3 -m sarview

# and this listens on 9001, whatever the file and the variable say
python3 -m sarview --port 9001
```

The page reads the `[viewer]` section from the process that is actually running. Restart after you edit the file. Refresh in the browser only re-reads `sa` files, not the config.

The process only binds `127.0.0.1`. That is not configurable. `localhost` on macOS sometimes goes to IPv6, so use `http://127.0.0.1:<port>`.

`~/.ssh/config` is separate. The `host` value here is the `Host` alias in that file, the same name you would pass to `ssh`.

## ssh

| Key | Default | What it changes |
| --- | --- | --- |
| `host` | `myopip` | SSH config alias. Also `--host` and `SARVIEW_HOST`. |
| `sa_dir` | `/var/log/sysstat` | Directory on the server. Also `--sa-dir` and `SARVIEW_SA_DIR`. |
| `connect_timeout` | `20` | Seconds for the SSH handshake. |
| `catalog_timeout` | `60` | Seconds for the remote listing (`sadf -H` on each file). |
| `fetch_timeout` | `180` | Seconds for a full `sadf` decode of the files for one day. |

`host` has to match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. That rules out spaces and shell metacharacters. The alias still has to log in with `BatchMode=yes`; sarview will not prompt, and it will not turn host-key checking off.

`sa_dir` is an absolute path on the server. `..` is rejected.

Timeouts are integers from 1 to 3600. If a listing of a long history regularly dies at 60 seconds, raise `catalog_timeout` before you assume `sadf` is broken.

Check the alias before you blame the config:

```bash
ssh -o BatchMode=yes myopip true
python3 -m sarview --check
```

`--check` prints the host, the timezone, and the dates, then exits. It does not start the page.

## server

| Key | Default | What it changes |
| --- | --- | --- |
| `port` | `8765` | TCP port on 127.0.0.1. Also `--port` and `SARVIEW_PORT`. |

Any integer from 1 to 65535. If something else already has 8765, pick another port rather than killing whatever is there.

## cache

| Key | Default | What it changes |
| --- | --- | --- |
| `dir` | `~/.cache/myopip-monitor` | Where decoded JSON is stored. Also `--cache-dir` and `SARVIEW_CACHE`. |
| `catalog_ttl` | `120` | Seconds to trust the file list. Also `--catalog-ttl` and `SARVIEW_CATALOG_TTL`. `0` lists the server on every request. |

Decoded files land in `<dir>/<host>/`. A day is decoded again only when the remote file's size or mtime changes, or when you hit Refresh (that forces a new listing; unchanged files still come from disk).

`catalog_ttl` is how long the process will answer from the listing it already has, with no SSH at all. After that, one short listing checks whether any `sa` file grew. Today's file grows through the day, so a later view of today decodes it once more.

`0` is allowed. The upper bound is 86400. Wipe the cache with `rm -rf` on the directory you set. Do not point `dir` at a folder you care about; sarview writes `catalog.json` and one JSON file per `sa` file under it.

## viewer

These only affect the page. They are not flags and they are not environment variables.

| Key | Default | What it changes |
| --- | --- | --- |
| `title` | `Sysstat history` | Browser title and the heading. 80 characters max. |
| `charts` | all six, in the usual order | Which panels are drawn, and in what order. |
| `hide_idle` | `yes` | CPU idle starts hidden. `no` draws it immediately. |
| `default_from` | `00:00:00` | Start of the window filled in for a date. |
| `default_to` | `23:59:00` | End of that window. |
| `ranges` | `15m`, `1h`, `6h`, `Full day` | The shortcut buttons. |
| `hot_user` | `50` | User % at which the readout goes red. |
| `hot_iowait` | `5` | Iowait % for the same. |
| `hot_ram` | `80` | RAM used % for the same. |
| `hot_swap` | `10` | Swap used % for the same. |
| `table_open_below` | `24` | Open the sample table when the window has this many rows or fewer. |

`charts` is a comma-separated list. Names are `cpu`, `memory`, `swap`, `load`, `disk`, `network`. Unknown names are an error, and so is listing one twice. Order in the file is the order on the page. This is the whole CPU and load view, nothing else:

```ini
charts = cpu, load
```

`hide_idle = no` when you want the 0 to 100 scale as soon as the page loads. The legend still toggles it either way. `yes` and `no` are the spellings configparser accepts, along with `true`/`false` and `1`/`0`.

`default_from` and `default_to` are clock times, `HH:MM` or `HH:MM:SS`. The end has to be the same moment or later. An end time that lands on a whole minute still includes the rest of that minute, same as a window you type into the page: sar stamps the sample a few seconds after the interval. These values are what you get when the page opens, when you change the date, when you hit a shortcut whose span is `day`, and when you double-click a chart. A `?start=` and `?end=` already in the address bar still win for that one visit.

`ranges` is `label=seconds` entries separated by commas. `label=day` means "put `default_from` and `default_to` back". Seconds are counted back from the last sample in the day, not from the wall clock now. A morning-only set of buttons:

```ini
default_from = 08:00:00
default_to = 14:00:00
ranges = 15m=900, 1h=3600, Morning=day
```

`hot_*` values are numbers from 0 to 100. They colour the readout cards. They do not draw a line on the chart, and load is still compared with the CPU count recorded on the sample, which is not a config key.

`table_open_below = 0` keeps the raw-sample table collapsed until you open it. A short window (a 15 minute drag on a 10 minute collection) still opens by itself when the row count is under the limit.

## Flags that are not in the file

`--demo` serves the built-in day and does not SSH. The `[viewer]` section still applies, so you can check a chart layout without the server.

`--check` prints dates and exits.

`--version` prints the version.

`--help` lists the flags. It does not dump this file; the file is the longer reference.
