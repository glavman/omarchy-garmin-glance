# Garmin Glance Reference

Detailed controls, data semantics, diagnostics and maintenance for
[Garmin Glance](../README.md). Start with the [setup guide](SETUP.md), including
[agent-assisted setup](SETUP.md#agent-assisted-setup). Maintainers: see the
[public-release and marketplace checklist](PUBLISHING.md).

The plugin reads the InfluxDB database of an existing
[garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) stack directly,
not the Grafana HTTP API. It adds no Garmin login, cloud scraper, collector,
web server or historical database. Opening Garmin Connect or Grafana launches
your browser; authentication there is separate from the plugin.

## Requirements

- Omarchy 4 / Quickshell plugin schema 1, tested on Omarchy 4.0.2 and Quickshell 0.3.1.
- System Python 3.9+ with timezone data. No pip packages required.
- InfluxDB 1.x with the upstream GarminStats schema. Tested on InfluxDB 1.11.
- A dedicated non-admin database account with only READ access and authentication enabled.

## Install And Update

After completing [connection setup](SETUP.md), install from the public repo:

```bash
omarchy plugin add https://github.com/glavman/omarchy-garmin-glance.git
```

Decline immediate enable if prompted. Verify database authentication and grants,
then run `doctor` as described in [Install and Enable](SETUP.md#4-install-and-enable)
before enabling. No GitHub credentials are needed for public clone access. The
repository has `manifest.json` at its root. Git-managed installations update with:

```bash
omarchy plugin update io.github.glavman.garmin-glance
omarchy restart shell
```

Alternatively, after verifying the connection and permissions, run
`python3 backend.py doctor` from a separate local checkout before using its installer:

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
Its directory must have mode 0700, and the file must be owned by you with mode 0600.
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

- Hover the watch-only bar icon for steps today, Body Battery, sleep score and
  a latest-activity summary. No numeric metric is displayed in the bar itself.
- Left-click the watch icon to open or close the dashboard.
- Middle-click to refresh; it queries InfluxDB, never Garmin.
- `R`: refresh metrics and charts. `G`: open Grafana. `Escape`: close.
- `Tab` / `Shift-Tab`: switch Omarchy panels.
- `Up` / `Down` or `j` / `k`: navigate stats, selectors, charts, activity and
  actions. The focused item scrolls into view automatically.
- `Left` / `Right` or `h` / `l`: choose within button rows or inspect chart samples.
- `Enter` / `Space`: activate the focused control; stats/charts open related
  Grafana views, while activities open the exact activity in Garmin Connect.
  Hover and keyboard share one cursor.
- `1`-`5`: select Steps, Sleep, HRV / Resting HR, Stress or Battery peak and
  reveal its primary chart. Down reaches the secondary chart in paired views.
- `B`: jump to the Body Battery/stress overlay.
- `D`: expand/collapse activity details and reveal them.
- `W`: jump to the [activities overview](#activities-overview), today plus six prior days.
- `O`: open the activity context in Garmin Connect, or stat/chart context in Grafana.
- `A`: open the latest activity in Garmin Connect.
- **Activity GPS**: open the matching GPS view when a verified selector and
  duration are available; this separate Grafana action is keyboard-reachable
  in the footer. **Activity in Grafana** opens the full dashboard over the latest
  activity's time range, not the single Recent Activity table.
- **Ask Coach**: review sharing consent and open your existing agent's terminal;
  see [scope and privacy](#ask-coach).

Settings are available through Omarchy bar settings:

```bash
omarchy bar set io.github.glavman.garmin-glance watchModel "Forerunner 965"
omarchy bar set io.github.glavman.garmin-glance refreshMinutes 5 --json
omarchy bar set io.github.glavman.garmin-glance demoMode true --json
omarchy bar set io.github.glavman.garmin-glance demoMode false --json
```

The exposed settings are `watchModel`, `refreshMinutes`, `demoMode`, `stepGoal` and
`grafanaUrl`. `stepGoal` is a personal goal, not a Garmin reading, and is included
in Coach consent and the approved snapshot. Polling is clamped to 1-60 minutes,
defaults to 5, and backs off after errors. `grafanaUrl` defaults to
`http://127.0.0.1:3000`; it can include a specific dashboard path.

`demoMode: true` forces synthetic data. With `false` (the default), the plugin
uses `fetch/cache --auto-demo`: an absent default connection file shows the demo
without accessing the database or cache. A present but invalid file or a failing
connection never triggers demo fallback. Refresh detects a newly created config.
Older implicit-localhost installs without a file now show the preview; configure
an explicit private connection as described in [SETUP.md](SETUP.md).
Plain CLI `fetch`, `cache` and `doctor` retain their implicit-default behavior;
`doctor` cannot use either demo flag and is not proof of READ-only grants.

**Set up live data** / `S` opens the in-plugin guide with the exact README prompt,
an explicit copy action, a documentation link and refresh. It never collects
credentials or launches an agent. Tab moves among setup controls, Up/Down and
Page Up/Down scroll, and Escape returns to dashboard navigation. Coach and
Grafana/Connect actions remain disabled for demo data.

### Garmin Connect Links

`A`, activity-row clicks and activity-context `O` / `Enter` open
`https://connect.garmin.com/modern/activity/<ActivityID>` in your default browser.
The ID must be a validated numeric ActivityID from the selected source, confirmed
by the collector's matching `Activity_ID` field. Manual FIT imports can use
synthetic IDs; without that confirmation they have no Connect link. The plugin
does not guess from the activity name or date. Missing/invalid IDs and demo data
have no Connect action. The overview summary itself is not an activity link.

Your browser may require Garmin sign-in and permission to view that activity.
The plugin never authenticates to Garmin or stores Garmin credentials/tokens.
Activity IDs can remain in browser history/sync and Garmin's access logs.

### Grafana Navigation

Context links use existing Garmin Stats panels; they do not change Grafana,
dashboards or datasource configuration. A base `grafanaUrl` (including a reverse
proxy prefix) uses `/d/feiibsx498gsgb/garmin-stats`. An explicit `/d/UID/slug` URL
keeps that dashboard path and assumes the same panel IDs. `G` opens the configured
URL unchanged. Context links preserve unrelated query settings such as `orgId`.

| Context | Existing Grafana panel |
|---|---|
| Steps | Today's Steps (30); history: Daily Steps (1) |
| Sleep score | Sleep Score (12) |
| Sleep hours | Last Sleep Hours (32), not an hours-history chart |
| HRV | Daily avg health metrics (11), intraday HRV average, not overnight HRV |
| Resting HR | Today RHR (28); history: Daily avg health metrics (11) |
| Stress | Stress/Body Battery (29); history: Daily avg health metrics (51) |
| Body Battery | Intraday overlay (29); peak history: shared daily-average panel (66) |
| Separate Activity in Grafana / Activity GPS actions | Full dashboard at activity time; verified GPS: GPS Track by Velocity (50) |

These are **related views**, not identical calculations: existing panels can use
daily means, smoothing, or different zero filtering. The activity dashboard
uses a time interval, not an exact-ID summary filter. The existing health
panels do not filter by the plugin's source tags; verify the Grafana datasource
represents the intended account, especially with multi-user databases.

Current stats open their sample's source-local day. History opens the inspected
day or the displayed series' date range, including cached dates and DST. Both
Grafana display timezone and its `TimeZone` variable are set. Activity ranges
cover the recorded start/duration with a minute of padding. GPS selectors are
looked up by ActivityID and validated source in `ActivityGPS`, because FIT imports
can use a different selector from the summary. Missing GPS data or a failed
optional lookup leaves the summary usable without a GPS action.

Context actions are disabled in demo mode. Old payloads without bounds require
a refresh instead of guessing dates. URLs contain dates and, for GPS, an activity
selector: these can appear in browser history/sync and Grafana/proxy logs. Do not
put credentials in `grafanaUrl`; the plugin does not log generated URLs. Panel
routes were verified against local deployment definitions; Grafana login is
still required, and UI-edited dashboards may use different panel IDs.

### Watch Identity

The compact dashboard header shows a native monochrome QML watch icon and the
model name, without a displayed provenance line. It uses the selected source's `Device` tag
when available, with no additional database or Garmin requests for the identity.
Upstream normally fills this from Garmin's last-used device name, but collector
overrides and imports can change it. The collector-reported name is a device
label, **not proof of the exact model or
which watch recorded each historical sample**. Other source tags are not exposed.

Set `watchModel` in bar settings to supply a model when the tag is missing or
customized; leave it blank to use the reported name. This only personalizes the
display, not database filtering. Unknown names keep a generic watch. Recognized
families use round sport, rugged outdoor, square, slim band or hybrid silhouettes
and matching bar icon shapes. These are stylized family silhouettes, not exact
hardware replicas. Body Battery appears in the stats, not in the watch art, and
is not the watch's charge level.
Demo mode uses a synthetic Forerunner 965 and ignores the configured model.

One shell service owns polling across all monitors. Daily history loads when
the dashboard opens and then refreshes with that shared service; the chart is
always visible. Requests cannot overlap, and the helper
has an additional process lock. Demo mode makes no database request and does
not overwrite real caches. Switching modes clears the display first.

## Data And Freshness

| Display | Measurement | Field | Units |
|---|---|---|---|
| Body Battery | BodyBatteryIntraday | BodyBatteryLevel | 0-100 score |
| Steps | DailyStats | totalSteps | steps |
| Sleep score | SleepSummary | sleepScore | 0-100 score |
| Sleep time | SleepSummary | sleepTimeSeconds | seconds, displayed as hours/minutes |
| Overnight HRV | SleepSummary | avgOvernightHrv | ms |
| Resting HR | DailyStats | restingHeartRate | bpm |
| Stress (latest) | StressIntraday | stressLevel | 0-100 score |

The daily stats table pairs the seven current readings under **Today** with a
**7d avg** over the last seven **completed source-local calendar days**, excluding
today. The history chart shows those same days for each stat. Body Battery
history and its average use the reported daily peak from
`DailyStats.bodyBatteryHighestValue`, not the current intraday level. Steps use
the latest daily cumulative snapshot, never a sum; sleep and HRV use the latest
nonnull value per field for each day.

Sleep time uses `sleepTimeSeconds` directly: awake time is **not subtracted**.
The table formats both current sleep and its average as hours/minutes (for
example, `7h 42m`); its history chart converts seconds to hours. Resting HR charts
use bpm, HRV charts ms, and score charts a 0-100 scale. Daily-stat numbers are
rounded for display; the Resting HR table row is in bpm even without a suffix.

History tabs are ordered **Steps, Sleep, HRV / Resting HR, Stress, Battery peak**
(keys **1-5**). The **Sleep** tab pairs score and hours; **HRV / Resting HR** pairs
HRV in ms with resting heart rate in bpm. Each pair uses separate charts,
retaining their own scales and cache indicators. Click either chart to inspect
it with the Left/Right keys. The daily stats table keeps separate readings and
averages for each metric.

Seven-day stress history uses `MEAN("stressLevel")` from `StressIntraday` for
each completed source-local calendar day, filtering observations to 0-100
inclusive before aggregation. **7d avg** averages those daily means. The current
stress reading is the latest valid instantaneous `StressIntraday.stressLevel`,
not today's daily average. Other supplemental history selects the latest valid
value per field per source-local day.

Sleep duration (`sleepDuration`), resting heart rate (`restingHeartRate`),
readiness (`trainingReadiness`) and stress (`stress`) are an optional `wellness`
bundle, separate from the four core `metrics`. Readiness requires opt-in
collection by the upstream collector. This plugin does not enable it or change
the user's collector configuration. Missing readiness means unavailable or not
collected; it does **not** establish that the watch is unsupported.
Readiness is not displayed in the dashboard or history selector.
It is available to Coach when recorded, without enabling collection automatically.

Missing days remain gaps and are excluded from averages, not counted as zero.
Partial averages are marked `*` with an incomplete-history note; with no valid
days, the average is `--`. Genuine zero values contribute to the average.

Body Battery and instantaneous stress are stale after two hours; steps, resting
HR and readiness expire at the next source-local midnight. Sleep score/HRV expire
36 hours after sleep end; sleep duration uses a 36-hour sample-age window.
These are display heuristics, not health
judgments. A database reading over one hour old is labeled cached. The bar icon
dims for stale/unavailable tooltip metrics or a connection problem; expired
steps show `--` rather than yesterday's count.

The **Today** column can include older sleep readings that are still fresh
within the 36-hour window. Their metric dates are compared with `sourceDate`
(the current date in the configured source timezone); older readings are marked
with `*` and their dates listed below the table, even when still fresh. Stale
readings are also flagged. Metric dates use the configured source timezone;
displayed clock times use your desktop timezone. DailyStats timestamps mean the
wellness day, not the time of database import.

If source-local midnight passes without a replacement payload, the column changes
from **Today** to **Latest** and retained readings are marked as older samples.
This conservatively avoids presenting the previous payload as today's data.

### Body Battery And Stress

The overlay draws individual stress observations as bars and Body Battery as a
line, both on a fixed 0-100 scale. Negative Garmin stress sentinel values and
other invalid stress values become `null` gaps, not zero or interpolated bars.
Genuine stress zero remains valid. The battery line breaks at null samples and
sampling outages longer than 30 minutes.

**Today** and daily-history boundaries use the configured source timezone.
The overlay uses `sourceDayStart` and `sourceDayEnd` to cover source-local midnight
to now, capped at that day's end. Fetches cover the full source day, including a
25-hour DST day. If midnight passes without a replacement payload, the overlay
keeps the previous day's bounds and shows **Previous day** rather than relabeling
old samples as today. Endpoint dates and inspection times use the desktop timezone.
Hover to inspect either series, or click the overlay and use Left/Right to move
in 15-minute steps. A missing nearby sample is shown as `--`.

### Activities Overview

`W` reveals recorded activities for **today plus the six prior source-local
calendar days**, from the first day's midnight through the latest fetch. This
is not a calendar week or a rolling 168-hour window. It differs from the stats'
seven **completed** days, which exclude today. The displayed date range remains
attached to cached results rather than being relabeled as a new period.

The overview shows the recorded activity count, total elapsed hours and reported
calories (kcal). Each exact activity type has its own count, elapsed hours and
distance in km. **There is no combined distance across sports.** These are totals
of recorded activities only, not daily calorie expenditure, training targets or
proof that all watch activities have synced. Calories are reported values, not
an inferred active/resting split.

Missing numbers stay unknown (`--`); partial totals show how many activities
contributed, such as `2/3 known`. Genuine zero contributes to totals. A successful
empty result shows no recorded activities; unavailable or failed results are not
presented as zero activity. Same-source cached results retain their original
fetch timestamp and date range, with cached/error indicators.

Rows are newest first, initially ten at a time; **Show more** reveals ten more
without changing the totals. Each row opens its exact activity in Garmin Connect.
The independent latest-activity card can show an activity outside this period.

The optional `ActivitySummary` query loads with charts, uses the same validated
source identity as health readings, excludes `No Activity`, and requires numeric
ActivityIDs. Duplicate IDs are counted once using the latest timestamp;
conflicting rows for the same ID/time are rejected. The lookup is bounded to
500 rows; overflow fails rather than displaying silently truncated totals.
Overview failures do not discard usable latest-activity or health data.

### Latest Activity

The dashboard shows the latest `ActivitySummary` within a bounded 365-day lookup,
excluding `No Activity` placeholders. Activity and daily history require a
validated, nonempty tag identity established by the health readings. Activity
source tags must match that same identity, ignoring only `ActivityID` and
`ActivitySelector`; ambiguous, mismatched or unestablished sources are not used.

The card shows the activity type (`activityType`), date/time and elapsed duration
(`elapsedDuration`, in seconds, formatted as minutes/hours). Distance (`distance`,
in metres, formatted as m/km) appears only when positive and relevant to the
recognized sport. Both the latest-activity card and overview rows use the
native monochrome QML [activity icons](#activity-icons) listed below.

Positive `averageHR` is shown in bpm. Performance uses reported speeds in m/s,
not distance divided by elapsed time:

- Running, walking and hiking: average pace in minutes:seconds per km.
- Swimming: average pace per 100 m. Rowing: average pace per 500 m.
- Cycling, mountain biking, windsurfing and skiing: average and/or maximum speed
  in km/h, converted from `averageSpeed` / `maxSpeed`.
- Missing, nonpositive or implausible speeds, and sports without a defined
  performance display, omit that line rather than inventing a value.

**Details** expands available `movingDuration` (seconds formatted as minutes/hours),
`maxHR` (bpm), `elevationGain` / `elevationLoss` (m), `aerobicTrainingEffect` /
`anaerobicTrainingEffect` (unitless scores, one decimal) and `activityTrainingLoad`
(unitless load). All fields come from the same activity row; missing details are
omitted. Genuine zeros are preserved for moving duration, elevation gain/loss,
training effects and training load. Zero `averageHR`, `maxHR`, `averageSpeed` and
`maxSpeed` are unavailable, not displayed as valid readings.

`calories` and `bmrCalories` are displayed as reported in kcal, including zero,
with BMR labeled resting. No fake active-calorie value or active/resting split is
inferred by subtraction. Missing numeric fields stay unavailable.

A successful empty lookup shows **No activity in the last year**. Optional
activity, activities overview, core history, wellness, supplemental history and
stress-series queries fail independently: an optional failure does not discard usable core readings or
unrelated optional results. Separate requests also keep absent readiness from
blocking other wellness fields. All optional data requires the same validated
source identity; untagged, ambiguous or mismatched sources are not combined.

Available same-source cached values can be retained after failures without
resetting measurement or fetch timestamps. Mixed live/cached supplemental bundles
keep the older fetch timestamp rather than making retained values look new.
History, activity, activities overview and overlay expose cached labels; metric
freshness also uses its bundle's fetch time. Without cached data, the affected
values are unavailable.
A successful empty optional read clears previous values rather than retaining
them indefinitely.

Missing data stays unavailable, while genuine zero stays zero. Successful
database reads do not prove the watch synced. Per-field failures retain available
same-source cached values without resetting their measurement timestamps.
The cache holds a small display snapshot, not an additional historical archive.
Charts, daily history, activity, activities overview, wellness, supplemental
history and stress series have separate fetch timestamps. Wellness and latest
activity refresh on every fetch; history, activities overview and overlay series
load with charts. All output is bounded. Existing version-1 caches without the
new optional bundles load with unavailable defaults.

### Activity Icons

There are exactly **31 distinct sport icons**, plus a generic fallback. Aliases
share icons; they do not add to that count. Type matching ignores case and outer
whitespace and treats runs of spaces or hyphens as underscores.

| Icon | Recognized activity types / aliases |
|---|---|
| Running | `running`, `track_running`, `street_running`, `virtual_run` |
| Cycling | `cycling`, `biking`, `road_biking`, `road_cycling`, `gravel_cycling`, `e_bike_fitness`, `cyclocross`, `recumbent_cycling`, `hand_cycling`, `track_cycling` |
| Mountain biking | `mountain_biking`, `mountainBiking`, `mountain_cycling`, `e_bike_mountain`, `bmx` |
| Windsurfing | `wind_kite_surfing`, `windsurfing`, `wind_surfing`, `kitesurfing`, `kite_surfing` |
| Surfing | `surfing` |
| Rowing | `rowing` |
| Strength | `strength`, `strength_training`, `weight_training`, `weightlifting` |
| Walking | `walking`, `casual_walking`, `speed_walking`, `indoor_walking` |
| Hiking | `hiking`, `mountaineering` |
| Swimming | `swimming`, `lap_swimming`, `pool_swimming` |
| Skiing | `skiing`, `alpine_skiing`, `backcountry_skiing`, `resort_skiing` |
| Yoga | `yoga` |
| Paddling | `paddling`, `canoeing` |
| Cardio | `cardio`, `fitness_equipment`, `indoor_cardio` |
| Trail running | `trail_running`, `ultra_run` |
| Treadmill | `treadmill`, `treadmill_running`, `indoor_running` |
| Indoor cycling | `indoor_cycling`, `virtual_ride` |
| Open-water swimming | `open_water_swimming` |
| Indoor rowing | `indoor_rowing` |
| Pilates | `pilates` |
| Elliptical | `elliptical` |
| Stair climbing | `stair_climbing`, `floor_climbing`, `stair_stepper` |
| HIIT | `hiit`, `high_intensity_interval_training` |
| Snowboarding | `snowboarding`, `resort_snowboarding`, `backcountry_snowboarding` |
| Cross-country skiing | `cross_country_skiing`, `skate_skiing`, `xc_classic_skiing`, `xc_skate_skiing` |
| Kayaking | `kayaking`, `kayaking_v2` |
| Paddleboarding | `paddleboarding`, `stand_up_paddleboarding`, `stand_up_paddle_boarding` |
| Tennis | `tennis` |
| Golf | `golf` |
| Soccer | `soccer` |
| Basketball | `basketball` |

Unknown types, empty values and non-string values use the generic icon. Icons
are selected by `activityIconKind(type)`, separately from the existing
`activityKind(type)` sport families used for metrics. The finer icon distinctions
do not change distance visibility or pace/speed formatting: for example,
`trail_running` retains running pace, `indoor_cycling` retains cycling speed,
and `snowboarding` retains skiing speed. An icon-only alias that previously had
no metric family still has no sport-specific distance or performance display.

## Ask Coach

Coach is an optional, on-demand terminal handoff, not an inline chat or automatic
coaching on dashboard refresh. It requires the existing private connection and an
installed, authenticated Omarchy default **OpenCode, Claude, Codex or Grok**. It
adds no agent configuration, global default change, SDK, API key or MCP server.
Follow [optional setup](SETUP.md#6-optional-ask-coach) before using it.

Choose **Plan my day**, **Review my week** or **Ask a question**, then **7, 30 or
90 days** (default 7). Review the agent and disclosure, and explicitly approve
**Open agent**. There are **no metric checkboxes**: consent covers all available
supported summaries and sanitized recorded activities within that window, plus
the configured personal step goal. Questions and answers belong in the agent
terminal; conversation resumption is not guaranteed. Coach is disabled in demo
mode. A successful launch request does not prove agent readiness, provider login,
snapshot loading or answer completion.

The default response instructions request **60-90 words, under 120 words**, a
**2-3 sentence summary** and **at most two short recommendations**, with more detail
only when requested. This is a response instruction, not an enforced output cap.
Coaching offers cautious wellbeing observations and small optional habits, not
medical diagnosis or training/exercise-intensity prescriptions.

### Shared Data

The initial snapshot includes latest valid summaries for **eight metrics**:
Body Battery, steps, sleep score, overnight HRV, sleep duration, resting heart
rate, training readiness and stress, plus sanitized activity details within the
approved window. Missing metrics remain unavailable. "All available" means this
supported schema, not arbitrary measurements, unknown fields or other databases.
Daily history is fetched on demand, not included as a raw intraday export.

Activity details include time/date, type, elapsed/moving duration, distance,
reported calories/BMR calories, average/max heart rate and speed, elevation
gain/loss, aerobic/anaerobic training effects and training load when available.
**GPS, activity/account IDs, selectors, free-text notes and raw source tags are
excluded.** Invalid numbers become null; invalid type labels are omitted with a
warning. Labels and helper output are untrusted data, never instructions.

Body Battery summary uses the latest valid intraday reading; daily history uses
the reported daily highest value (`DailyStats.bodyBatteryHighestValue`), not a
recomputed maximum. Stress history uses daily means of valid 0-100 readings;
its sample timestamp is null because no single observation represents the mean.
Other daily values are latest valid per source-local date, not sums. Sleep time
does not subtract awake time. History includes the launch day's incomplete date,
unlike dashboard history's seven completed days; completed-day means exclude
that date and missing values. Missing data is not zero. Coverage describes
observed availability, not database retention or proof of complete watch sync.

### Sessions And Helper

The approved source and date window are **fixed at launch**, from source-local
midnight on the first date through the launch instant. Access lasts **24 hours**,
not a rolling date permission. Source/config changes can invalidate access.
Additional in-scope reads need no new consent prompt; broader access, changed
source or expiry requires returning to Ask Coach for explicit approval.

The handoff supplies a session ID and these local commands. Replace `<plugin>`
with the plugin directory and `<session-id>` with that supplied ID, not a path:

```text
python3 <plugin>/coach.py capabilities --session <session-id>
python3 <plugin>/coach.py summary --session <session-id>
python3 <plugin>/coach.py history --session <session-id>
python3 <plugin>/coach.py history --session <session-id> --days 7 --metrics steps,sleep,hrv
python3 <plugin>/coach.py activities --session <session-id> --days 7
```

`capabilities` describes approved scope and expiry, not proven data coverage.
`summary` includes latest wellbeing readings and activities; `history` returns
daily samples without activities; `activities` returns no wellbeing metrics.
Omitting options uses the full approved scope. `--days` can narrow to 1 through
the approved number of days. `--metrics` can narrow summary/history to a nonempty,
unique subset of `bodyBattery,steps,sleep,hrv,sleepDuration,restingHeartRate,trainingReadiness,stress`;
`activities` rejects `--metrics`. No flag expands consent, and there is no arbitrary
query interface or standalone unlimited export command.

Successful data/capabilities, snapshots and stored sessions use **schema v2**.
`check`, `launch`, `clear` and error envelopes remain **v1**. Old v1 sessions return
`session_expired` and require new approval; their narrower consent is never
retroactively expanded. The UI launch request is exactly
`{intent, days, stepGoal, agent}` on standard input, with no metric selection.
Intents are `day`, `week` or `question`; the helper accepts integer days 1-90
(the UI offers 7/30/90) and a positive numeric step goal up to 100000. The detected
agent must still match at launch. Treat helper data output as private health data.

### Limits And Failures

Each v2 read has a **20-second total budget**, including parsing and aggregation,
with at most **2 seconds per job** and **9 read-only query POST requests**. History
uses at most **90 daily selectors per metric request**, not the old v1 raw-history
path. Each response, combined output and saved snapshot is bounded to **1 MiB**.
These limits do not cover agent inference time or guarantee a successful 90-day
read; try a shorter window or fewer metrics in helper history requests.

Activities are limited to **500 raw rows before deduplication**. A 501st row fails
with `truncated_response`, never silent truncation. Duplicate validated private
ActivityIDs retain the latest timestamp; conflicting rows for the same ID/time
fail. IDs are stripped before sharing, and items are newest first. All returned
sections must share the same validated, nonempty source identity.

Independent `query_error`, `timeout`, `network_error`, `auth_error` or `http_error`
section failures preserve usable sections with partial/unavailable statuses and
stable-code warnings. Exhausting the total budget fails the whole call. Malformed
responses, missing/ambiguous source identity, redirects, truncation and size
overflow also fail the call rather than presenting incomplete data as complete.
Activity coverage `complete` only means its bounded query was not degraded, not
that all activities synced or that an empty result proves no exercise.

Launch needs an identified usable summary value **or** activity; activity-only
snapshots can launch. A successful empty read yields `no_data`. If all sections
fail, launch returns a query/transport error instead, or `data_unavailable` for
other warnings with no usable data, **not `no_data`**. In-session reads retain
section error statuses/warnings; do not interpret all-error results as empty
coverage or zero. Read limitations before drawing conclusions.

### Privacy And Cleanup

**The agent may send approved health data to its cloud provider and retain chat
history.** Plugin transport queries InfluxDB, not an AI provider directly, but
coaching is not a local-only promise. Omarchy's launcher may reduce approval
prompts; the agent retains its existing **unsandboxed filesystem/tool access**.
Read-only grants, helper scope checks and `COACH.md` instructions are not OS-level
isolation. Connection secrets and raw source tags are excluded from the handoff;
do not give the agent connection files or session metadata. Keep private output
out of logs, Git, support conversations and screenshots.

Owner-only, unencrypted session metadata and snapshots live under
`${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-garmin-glance/coach/`. At most **20 sessions**
are stored. Expired sessions are cleaned on the next launch; there is **no automatic
deletion timer**, so expiry can leave files on disk. Inside Ask Coach, choose
**Clear coaching files** and confirm, or run:

```bash
python3 "$HOME/.config/omarchy/plugins/io.github.glavman.garmin-glance/coach.py" clear
```

Clear needs neither a working agent nor a working connection. It removes only
plugin-owned session directories and snapshots, invalidating their helper access.
It leaves `.lock`, the parent folder, dashboard caches, connection settings and
unrelated files intact. It does not stop the agent or erase data already read.
**Neither expiry nor clear deletes agent/provider chat history or shared copies.**
Manage those separately using the agent/provider's retention controls. Plugin
removal also leaves these private files intact.

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
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests/tst_model.qml
python3 tests/run_qml.py
omarchy plugin validate .
```

The offscreen command above checks the model only. Plain `qmltestrunner -input
tests` cannot load every suite without the Quickshell runtime and host imports.
The native navigation cases need a running Wayland desktop, Quickshell,
QtTest and Omarchy's `qs` imports. Run them
from the repository root with a temporary import mapping (adjust the shell path
if Omarchy is installed elsewhere):

```bash
(
  imports=$(mktemp -d) || exit 1
  trap 'rm -f "$imports/qs"; rmdir "$imports"' EXIT
  ln -s /usr/share/omarchy/shell "$imports/qs" || exit 1
  QML_IMPORT_PATH="$imports${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}" \
    timeout 30s quickshell --no-color -p tests/run_navigation.qml
)
```

This opens a temporary native window and runs `tst_navigation.qml` against the
real panel with its fake Service. It does not instantiate `Service.qml`, start
the backend, read Garmin credentials or launch a browser. Each case prints
`PASS`; the runner exits 0 only when all cases pass, and 1 on an assertion,
skip or load failure (`timeout` returns 124 if the process hangs). It is not a
live browser-launch integration test.

The additional `tests/run_qml.py` runner covers dashboard and Coach QML suites
with packaged Omarchy imports and Quickshell initialization. It requires a
**running host Wayland desktop**, Quickshell and QtTest; use `--host-shell PATH`
if the shell is not at `/usr/share/omarchy/shell`. Missing host requirements or
skipped cases are failures, not passes. It uses temporary HOME/XDG directories,
copies only QML/JS sources and runs synthetic processes, not the real backend or
configured agent. This is test isolation, not a sandbox for untrusted QML.
For model-only testing without the host UI:

```bash
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests/tst_model.qml
```

`doctor` performs read-only schema queries and emits status without measurement
values or credentials. The shell `status` command reports the active UI mode,
request status and whether charts are loaded, without health values.
`fetch --charts` and `cache --charts` emit **private health
data**; don't paste their output into issues. `fetch --charts --demo` emits only
fabricated values. The dashboard JSON contract is version 1; Coach's separate
data/session v2 and control/error v1 contracts are described [above](#sessions-and-helper).

Python tests cover field mappings and units, seven completed source-local days
and DST boundaries, latest-per-field history, daily versus instantaneous stress,
stress sentinel gaps and zero, independent optional failures, source validation,
cache retention/timestamps, older cache defaults, bounded activity queries and
same-row activity details. They also cover privacy, demo isolation and installer
allowlisting, verified GPS-selector lookup and source-day link bounds. Qt tests
cover Grafana routes, encoding, missing metadata and paired-chart destinations,
along with payload validation, freshness, sleep formatting,
sport-specific pace/speed, zero-preserving detail formatting, averages, tooltips,
watch families and narrow/long-name watch-header layouts. Backend detail tests
verify zero preservation for moving duration, elevation, training effects and
load, and unavailable zero heart rates and speeds. These are automated model,
backend and component checks, not a full live dashboard interaction test.

Retain the 31-sport icon/alias and fallback cases, same-row activity details,
Garmin/Grafana authentication boundaries and native navigation coverage when
adding Coach tests. Coach's Python/QML suites cover scoped consent, v1-session
rejection, v2 queries/limits, activity deduplication, empty versus failed reads,
cleanup, launch lifecycle and synthetic process handoffs. Synthetic launch tests
and CLI-help checks do not establish live inference, provider authentication,
snapshot loading or completed coaching answers; report those separately from
any explicitly authorized live verification.

Use Qt 6 tooling, not the Qt 5 binaries that may be first on PATH. Standalone
`qmllint` needs a `qs` import mapping to the installed shell; dynamic host and
theme properties can produce metadata warnings. Runtime errors can be inspected
with `quickshell log -n -p /usr/share/omarchy/shell --tail 100 --no-color`.

## Privacy And Removal

Database access is read-only by implementation and database grant. QML plugins still
run unsandboxed as your user; this is not isolation from other local programs.
Connection secrets are read by Python helpers, not QML or the coaching handoff;
this does not restrict an unsandboxed agent's filesystem access.
No plugin telemetry or third-party chart assets.
The plugin needs no sudo, Docker socket access or Grafana API token.
Connection files and cached health values are private local files, not encrypted
storage. Source tags can contain names and appear in database/proxy query logs;
see [setup privacy notes](SETUP.md#3-configure-the-plugin-connection).
READ grants cover the whole database: source filters are not per-person access
control. The separately maintained collector still contacts Garmin's cloud.
Optional Coach may disclose health data through your agent to its provider;
[local cleanup](#privacy-and-cleanup) cannot erase those conversations.

Private cache: `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-garmin-glance/`.

```bash
omarchy plugin remove io.github.glavman.garmin-glance
```

Removal leaves connection credentials, cache and local installer backups intact.
Remove those separately if desired. It never stops the collector or deletes
InfluxDB data. Do not use `docker compose down -v`.

## Scope

InfluxDB 2/3, Grafana query-proxy transport, embedded maps, full activity archives,
notifications, medical interpretation and training prescriptions are outside the
plugin's scope. Coach exposes only eight supported wellbeing metrics and sanitized
activity fields, not arbitrary database contents or GPS. It adds no inline answers,
guaranteed chat resumption or setup wizard. The underlying
garmin-grafana collector remains responsible for Garmin login, watch
synchronization and backfill.

[MIT licensed](../LICENSE). Independent of Garmin and Omarchy. Omarchy's native
components are supplied by the host, not bundled.
