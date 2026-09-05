# Garmin Glance

A native Omarchy topbar and dashboard for Body Battery, steps, sleep and HRV,
with seven-day history and a 24-hour Body Battery chart.
No Garmin credentials, cloud requests, collector, web server or historical database
are added by this plugin. It is independent of Garmin and Omarchy.

**Prerequisite: a working [garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) stack with InfluxDB 1.x.** This plugin does not install or configure the
Garmin collector, Docker, Grafana, database users or network access. A working
Grafana website alone is not sufficient: the plugin reads its **InfluxDB database
directly**, not Grafana's API.

Follow the [step-by-step setup guide](docs/SETUP.md) in this order:

1. Get Garmin data appearing in garmin-grafana.
2. Secure InfluxDB and create a read-only account. Just installed upstream defaults? The guide covers that unauthenticated starting point explicitly.
3. Configure the private connection file and install the Omarchy plugin.
4. Verify data access with `doctor`, then enable the widget.

Maintainers: see the [public-release and marketplace checklist](docs/PUBLISHING.md).

## Requirements

- Omarchy 4 / Quickshell plugin schema 1, tested on Omarchy 4.0.2 and Quickshell 0.3.1.
- System Python 3.9+ with timezone data. No pip packages required.
- InfluxDB 1.x with the upstream GarminStats schema. Tested on InfluxDB 1.11.
- A dedicated database account with READ access and authentication enabled.

## Install And Update

After completing [connection setup](docs/SETUP.md), install from the public repo:

```bash
omarchy plugin add https://github.com/glavman/omarchy-garmin-glance.git --enable
```

No GitHub credentials are needed for public clone access. The repository has
`manifest.json` at its root. Git-managed installations update with:

```bash
omarchy plugin update io.github.glavman.garmin-glance
omarchy restart shell
```

Alternatively, from a separate local checkout of this repository:

```bash
python3 install.py
```

The local installer validates and copies an explicit allowlist of plugin code
and docs to `~/.config/omarchy/plugins/io.github.glavman.garmin-glance/`, backs up
existing code and shell settings, and enables the widget. No sudo. For copied
installations, update the checkout, rerun `python3 install.py`, then
`omarchy restart shell`. Keep the checkout separate from the installed directory
and use the same installation method for updates.

## Connection

Credentials belong in `~/.config/omarchy-garmin-glance/connection.json`.
Its directory must be private, and the file must be owned by you with mode 0600.
Create it for your existing stack using a read-only account. A configuration has this shape:

```json
{
  "url": "http://127.0.0.1:8086",
  "database": "GarminStats",
  "username": "omarchy_reader",
  "password": "YOUR_READ_ONLY_PASSWORD",
  "timezone": "Europe/Dublin",
  "tags": {}
}
```

Do not place passwords in shell settings, command arguments, screenshots or Git.
HTTP is accepted only for literal loopback addresses (localhost resolves to
127.0.0.1); remote connections require HTTPS. Proxies and redirects are disabled.
Use optional exact-match tags to choose a source in a shared database, for example
`{"User_ID":"actual-display-name"}`. The upstream optional User_ID tag is not
necessarily an email. Multiple source series are rejected rather than combined.
Already-merged untagged data cannot be separated by this plugin.

Changing credentials takes effect on the next request. After changing the
endpoint, database, source filters or timezone, restart the shell to discard
the previous in-memory display immediately. Persistent caches are source-scoped.

## Use

- Left-click the bar metric to open or close the dashboard.
- Middle-click to refresh; it queries InfluxDB, never Garmin.
- `R`: refresh metrics and charts. `G`: open Grafana. `Escape`: close.
- `Tab` / `Shift-Tab`: switch Omarchy panels.
- `Up` / `Down` or `J` / `K`: scroll.
- `B`: inspect Body Battery. `S`: switch steps/sleep history.
- `Left` / `Right` or `H` / `L`: inspect exact chart samples.
- Hover chart points for their values and dates.

Settings are available through Omarchy bar settings:

```bash
omarchy bar set io.github.glavman.garmin-glance barMetric steps
omarchy bar set io.github.glavman.garmin-glance refreshMinutes 5 --json
omarchy bar set io.github.glavman.garmin-glance stepGoal 10000 --json
omarchy bar set io.github.glavman.garmin-glance demoMode true --json
omarchy bar set io.github.glavman.garmin-glance demoMode false --json
```

`barMetric` accepts `bodyBattery`, `steps`, `sleep`, `hrv`. Polling is clamped to
1-60 minutes, defaults to 5, and backs off after errors. `stepGoal` is explicitly
a personal goal, not a value returned by Garmin. `grafanaUrl` defaults to
`http://127.0.0.1:3000`; it can include a specific dashboard path.

One shell service owns polling across all monitors. Charts load on demand and
then refresh with that shared service. Requests cannot overlap, and the helper
has an additional process lock. Demo mode makes no database request and does
not overwrite real caches. Switching modes clears the display first.

## Data And Freshness

| Display | Measurement | Field |
|---|---|---|
| Body Battery | BodyBatteryIntraday | BodyBatteryLevel |
| Steps | DailyStats | totalSteps |
| Sleep score | SleepSummary | sleepScore |
| Overnight HRV | SleepSummary | avgOvernightHrv |

Body Battery is stale after two hours, steps at the next source-local midnight,
and sleep/HRV 36 hours after sleep end. These are display heuristics, not health
judgments. A database reading over one hour old is labeled cached. An asterisk
in the bar marks stale/unavailable data or a connection problem.

The seven-day charts use local calendar dates including today and preserve
missing days. Daily cumulative steps are never summed across snapshots. Body
Battery covers a rolling 24 hours, with gaps for nulls or sample outages over
30 minutes. Metric dates use the configured source timezone; displayed clock
times use your desktop timezone. DailyStats timestamps mean the wellness day,
not the time of database import.

Missing data stays unavailable, while genuine zero stays zero. Successful
database reads do not prove the watch synced. Per-field failures retain available
same-source cached values without resetting their measurement timestamps.
The cache holds a small display snapshot, not an additional historical archive.
Charts have a separate fetch timestamp. All output is bounded.

## Diagnostics And Tests

Diagnostics from any directory:

```bash
python3 "$HOME/.config/omarchy/plugins/io.github.glavman.garmin-glance/backend.py" doctor
omarchy-shell garmin-glance status
```

Tests and validation from the **development repository root** (the local
installer does not bundle tests). Here you can also run `python3 backend.py doctor`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests
omarchy plugin validate .
```

`doctor` performs read-only schema queries and emits status without measurement
values or credentials. The shell `status` command reports the active UI mode,
request status and whether charts are loaded, without health values.
`fetch --charts` and `cache --charts` emit **private health
data**; don't paste their output into issues. `fetch --charts --demo` emits only
fabricated values. The JSON contract is version 1.

Use Qt 6 tooling, not the Qt 5 binaries that may be first on PATH. Standalone
`qmllint` needs a `qs` import mapping to the installed shell; dynamic host and
theme properties can produce metadata warnings. Runtime errors can be inspected
with `quickshell log -n -p /usr/share/omarchy/shell --tail 100 --no-color`.

## Privacy And Removal

The plugin is read-only by implementation and database grant. QML plugins still
run unsandboxed as your user; this is not isolation from other local programs.
Secrets are read only by the helper. No telemetry or third-party chart assets.
Connection files and cached health values are private local files, not encrypted
storage. Source tags can contain names and appear in database/proxy query logs;
see [setup privacy notes](docs/SETUP.md#3-configure-the-plugin-connection).
READ grants cover the whole database: source filters are not per-person access
control. The separately maintained collector still contacts Garmin's cloud.

Private cache: `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-garmin-glance/`.

```bash
omarchy plugin remove io.github.glavman.garmin-glance
```

Removal leaves connection credentials, cache and local installer backups intact.
Remove those separately if desired. It never stops the collector or deletes
InfluxDB data. Do not use `docker compose down -v`.

## Scope

InfluxDB 2/3, Grafana query-proxy transport, maps, activities, notifications and
medical interpretation are outside 1.0. The underlying garmin-grafana collector
remains responsible for Garmin login, watch synchronization and backfill.

MIT licensed. Omarchy's native components are supplied by the host, not bundled.
