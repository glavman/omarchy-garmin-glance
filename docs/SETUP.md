# Garmin Glance Setup

## Before You Start

This is an **Omarchy frontend for an existing garmin-grafana installation**.
It is not a Garmin Connect client or a replacement for the collector.

Data travels from your watch to Garmin Connect, through the garmin-grafana
collector into InfluxDB, and finally to this plugin. Grafana and this plugin
are two independent viewers of the same stored data. No Grafana API token is
needed, and refreshing this plugin never requests a Garmin sync.

Supported starting point: Omarchy 4 with Quickshell, system Python 3.9+ and
timezone data, and InfluxDB **1.x using InfluxQL**. Version 1.11 was tested.
InfluxDB 2.x/3.x and Grafana-proxy transport are not supported in this release.
Pin your container versions rather than using an unqualified `latest` tag.

## Agent-Assisted Setup

If garmin-grafana is already collecting your data, you can ask your Omarchy
agent to perform the connection setup instead of following every command
manually. This assumes your agent has the Omarchy skill available. The skill
covers desktop integration; the database-specific instructions are in this
guide. The agent should read both rather than assume your stack matches the
upstream defaults.

Paste the following into your agent. Optionally add your existing stack's
directory, local/remote host information and preferred IANA timezone. If you
do not know them, let the agent inspect or ask. **Do not paste credentials or
health records into the conversation.**

```text
Set up Garmin Glance on this Omarchy machine using my existing garmin-grafana
installation. Load the Omarchy skill and read these current instructions:
https://github.com/glavman/omarchy-garmin-glance/blob/main/docs/SETUP.md
https://github.com/glavman/omarchy-garmin-glance/blob/main/README.md

1. Inspect before changing anything. Locate the existing Compose deployment
   or ask me where it runs. Confirm the Omarchy plugin interface, InfluxDB
   version, database name, authentication state, reachable endpoint and source
   timezone. If the database is InfluxDB 2/3, stop and explain the incompatibility;
   do not downgrade, replace or recreate it. If Garmin data is not being
   collected yet, explain that prerequisite rather than pretending it works.

2. Explain any required stack changes and get my approval before changing
   accounts/grants, network exposure, stopping containers or restarting the
   desktop shell. Back up affected configuration and, before an authentication
   migration, the database including metadata. Preserve the Compose project
   name, volumes, mount paths, existing users, Garmin tokens and working clients.
   Never run docker compose down -v or the upstream initial installer.

3. Follow the appropriate authenticated/default-stack branch of the guide.
   The plugin reads InfluxDB directly; it needs no Grafana API token, Garmin
   password or new Garmin collector. Use a dedicated non-admin READ-only user.
   Ensure authentication is actually enabled. Keep local database access on
   loopback only; remote access needs trusted HTTPS and restricted networking.
   Do not weaken existing security or grant the plugin Docker/root access.

4. Handle secrets locally without returning their contents to the agent/chat.
   Use hidden interactive prompts or private files and redacted diagnostics.
   Never put passwords in command arguments, URLs, shell history, source code
   or shell.json. Do not print expanded Compose configuration, container
   environments, raw query results, Garmin tokens or health data. Ask me to
   enter any required administrator credentials through a local secure prompt.

5. Create or carefully update this owner-only file (directory 0700, file 0600):
   ~/.config/omarchy-garmin-glance/connection.json
   Set the endpoint, database, reader credentials and confirmed IANA timezone.
   Use source tags only if needed; do not treat tags as access controls.
   Review the plugin source, install from:
   https://github.com/glavman/omarchy-garmin-glance.git
   Then run its doctor diagnostic and enable io.github.glavman.garmin-glance.
   Preserve unrelated Omarchy settings; never edit /usr/share/omarchy/.

6. Verify anonymous database queries are denied and the plugin account is
   non-admin with only READ on the intended database. Check existing Grafana
   and collector access still works. Open the plugin and check
   `omarchy-shell garmin-glance status`: demo must be false, with no connection
   error and charts loaded. Explain missing/stale device metrics honestly;
   doctor deliberately redacts metric values, and SELECT success alone does
   not prove read-only permissions. Do not write health data to test access.

Finish with a short summary of changes, backup locations, verification results
and anything still blocked. Do not reveal credentials or health measurements,
commit/push files, or publish screenshots. If approval or secure credential
entry is unavailable, stop that step and tell me what to do locally.
```

This is a setup request, not an unattended installer. Expect the agent to ask
for confirmation when your existing database needs an authentication migration
or a restart. Review its proposed changes before approving them. It should
leave your existing collector responsible for Garmin login and synchronization.

The numbered sections below are the manual reference for both you and the
agent. If your stack is already authenticated and reachable, most of the
bootstrap work can be skipped; do not run it again unnecessarily.

## 1. Set Up Garmin Grafana

If you already have fresh data appearing in Grafana, continue to step 2.

Follow the upstream [garmin-grafana installation instructions](https://github.com/arpanghosh8453/garmin-grafana#manual-install-with-docker-recommended-if-you-understand-linux-concepts).
Keep that checkout and its secrets outside this plugin repository. The external
stack is maintained and updated separately; installing or updating Garmin Glance
does not update its containers, configure its accounts, or migrate its data.

1. Install Docker and Docker Compose for your system.
2. Review the upstream repository and Compose example before running scripts.
3. Configure its collector, InfluxDB 1.x and Grafana services with persistent volumes.
4. Complete Garmin authentication/MFA through the collector's documented login flow.
5. Sync your watch to Garmin Connect and let the first import finish.
6. Open Grafana and confirm recent values appear, not merely that its login page loads.

The plugin expects the upstream schema, verified against commit
`8e47830364817bc1a355eab857fa0535a99d401f`:

| Required Data | Measurement | Field | Upstream Fetch Selection |
|---|---|---|---|
| Body Battery | BodyBatteryIntraday | BodyBatteryLevel | stress |
| Daily steps | DailyStats | totalSteps | daily_avg |
| Sleep score | SleepSummary | sleepScore | sleep |
| Overnight HRV | SleepSummary | avgOvernightHrv | sleep |

Device support and upstream fetch settings determine which values exist. HRV
or sleep data may legitimately be unavailable. No need to import years of data:
the plugin uses seven calendar dates for history and 24 hours for Body Battery.
Set the collector's `USER_TIMEZONE` and the plugin's timezone intentionally.

**Security cautions:** base64 is not encryption; don't paste credentials into
online encoders. Avoid world-readable token directories, default Grafana admin
passwords, and unauthenticated database ports exposed to your network. Review
upstream instructions against your own deployment rather than copying insecure
convenience defaults. The plugin installer does not fix the stack for you.

## 2. Prepare Read-Only InfluxDB Access

The plugin runs on your desktop, outside Docker. The container hostname
`influxdb` is normally visible only inside the Compose network. It is not the
address to enter in the desktop plugin's connection file.

For a local installation the intended endpoint is `http://127.0.0.1:8086`.
Use another free host port if necessary, and match it in the plugin config.
Do not change Grafana's internal datasource URL from `http://influxdb:8086`
to localhost: localhost inside Grafana means the Grafana container itself.

Choose your starting point:

- **Just installed upstream defaults:** follow [2A](#2a-just-installed-upstream-defaults). Upstream's example leaves InfluxDB authentication disabled, even though username/password variables are present. Creating a READ user alone does not restrict an unauthenticated database.
- **Already secured:** follow [2B](#2b-already-secured). Keep working collector/Grafana accounts and authentication; only add a dedicated plugin reader.
- **Unsure or shared/remote server:** ask its administrator to check the effective auth setting and accounts. Do not disable authentication to follow the bootstrap instructions.

### 2A. Just Installed Upstream Defaults

These are reviewed manual steps for a local, single-owner InfluxDB 1.x stack,
not an automatic migration. Read through them before changing anything.
Run Compose commands in your **existing garmin-grafana deployment directory**,
using its usual Compose files and project name. Examples use upstream service
names `influxdb`, `garmin-fetch-data`, `grafana` and database `GarminStats`;
substitute your actual names throughout.

If Docker requires elevated access on your machine, run these Docker commands
with `sudo` in an interactive terminal. Do not run the plugin or its installer
with sudo, and do not grant the plugin access to the Docker socket.

**Preserve the existing project, service/container names, database name, named
volumes and bind-mount paths**, including Garmin tokens and Grafana provisioning.
Renaming the Compose project or moving its directory can select new, empty
volumes. Never run `docker compose down -v`, remove volumes, rerun upstream's
initial installer, or change InfluxDB major versions as part of this procedure.

#### Contain And Back Up

1. Make a private, restorable [InfluxDB backup including metadata](https://docs.influxdata.com/influxdb/v1/administration/backup_and_restore/) and preserve the existing Compose/provisioning configuration. Keep backups outside Git; they contain health data and account metadata.
2. Stop the clients with `docker compose stop garmin-fetch-data grafana`. InfluxDB stays running; no volumes are removed.
3. In the existing `influxdb` service, replace the unrestricted `8086:8086` port entry with `127.0.0.1:8086:8086`. Remove any other public bindings to this database. Keep auth unchanged for this bootstrap step, then run `docker compose up -d --no-deps influxdb` and `docker compose port influxdb 8086`. The latter must show only `127.0.0.1:8086`.

Do not add a second ports list or assume an override replaces existing entries:
Compose can merge them. Until auth is enabled, local users and containers on the
database network can still read/write everything. Use this short bootstrap
window only on a trusted host/network; do not expose it remotely.

Use a current Docker Engine (28 or newer). Older Docker versions have known
localhost-published port exposure to adjacent hosts, and custom direct routing
can change isolation. Verify your network/firewall restrictions rather than
treating the port listing alone as a security test.

Check existing users without passwords or health values:

```bash
docker compose exec influxdb influx -execute 'SHOW USERS'
```

If authentication is required, stop and use **2B**. If an administrator already
exists, or a proposed username below already exists, review it rather than
overwriting it. Upstream may have created `influxdb_user` with its example
password; that account must be retired or rotated before this setup is secure.

#### Create The Accounts Safely

Use a password manager to generate and store four different random passwords.
For this example, use **at least 32 random alphanumeric characters each** to avoid
SQL, JSON and Compose escaping pitfalls. These are InfluxDB accounts, not Garmin
credentials or the Grafana website login.

| Account | Permission | Used By |
|---|---|---|
| `admin` | Administrator | You, for database administration only |
| `garmin_collector` | READ + WRITE on `GarminStats` | Collector, including reading sync state |
| `grafana_reader` | READ on `GarminStats` | Grafana datasource |
| `omarchy_reader` | READ on `GarminStats` | Garmin Glance |

Create a protected temporary directory outside both repositories:

```bash
umask 077
admin_work=$(mktemp -d)
touch "$admin_work/accounts.sql"
chmod 600 "$admin_work/accounts.sql"
```

Keep this terminal open so `admin_work` remains set. Open
`"$admin_work/accounts.sql"` in a trusted local editor (for example,
`nano "$admin_work/accounts.sql"`). Disable editor backups, cloud sync and
clipboard history for secrets. Put the following **InfluxQL, not Bash** in it,
replacing each placeholder locally with its different saved password:

```sql
CREATE USER "admin" WITH PASSWORD 'REPLACE_ADMIN_PASSWORD' WITH ALL PRIVILEGES;
CREATE USER "garmin_collector" WITH PASSWORD 'REPLACE_COLLECTOR_PASSWORD';
GRANT ALL ON "GarminStats" TO "garmin_collector";
CREATE USER "grafana_reader" WITH PASSWORD 'REPLACE_GRAFANA_READER_PASSWORD';
GRANT READ ON "GarminStats" TO "grafana_reader";
CREATE USER "omarchy_reader" WITH PASSWORD 'REPLACE_PLUGIN_READER_PASSWORD';
GRANT READ ON "GarminStats" TO "omarchy_reader";
```

`GRANT ALL ON "GarminStats"` means database-level READ + WRITE, **not** global
administrator privileges. Do not give any application `WITH ALL PRIVILEGES`.

Submit the file directly to the local InfluxDB HTTP API in the **request body**:

```bash
curl -q --noproxy '*' --silent --show-error --fail-with-body \
  --data-urlencode "q@$admin_work/accounts.sql" \
  'http://127.0.0.1:8086/query'
```

There are deliberately **no authentication arguments during this unauthenticated
bootstrap**. Keep auth disabled only until the accounts and client configuration
are ready, then enable it below. Check the response: each statement should have
a `statement_id` and no `error`. HTTP 200 alone is not enough; InfluxDB can return
statement errors inside a successful HTTP response. Stop and inspect failures
locally, rather than blindly rerunning account creation. Statements are not a
transaction and earlier statements may already have succeeded.

Never put real passwords in URLs, shell commands, `curl --user user:password`,
`influx -execute`, or pasted terminal SQL. Do not use tracing (`set -x`, curl
`--verbose`/`--trace`) or share error output without inspection. These commands
disable curl config loading and proxies, and do not follow redirects. Request
bodies and Authorization headers must also be excluded from diagnostic logging.

**Why not `influx -import`?** InfluxDB 1.11 supports `-import -path` and a hidden
prompt with `-username admin -password ''`, but its importer passes DDL through
the client's URL query string. A protected import file alone would not keep
CREATE USER passwords out of URLs. The body-based workflow above avoids that
transport; it uses plain SQL, **not** the import format's `# DDL`/`# DML` headers.
The interactive CLI also has `.influx_history`; do not use it for secret SQL.

#### Configure The Existing Clients

Create a private env file outside Git, preserving it if it already exists:

```bash
install -d -m 700 "$HOME/.config/garmin-grafana"
touch "$HOME/.config/garmin-grafana/influx.env"
chmod 600 "$HOME/.config/garmin-grafana/influx.env"
```

Edit it locally with the **same** collector and Grafana-reader passwords just
created. Do not include the admin or plugin-reader password here:

```dotenv
GARMIN_COLLECTOR_PASSWORD='REPLACE_COLLECTOR_PASSWORD'
GRAFANA_READER_PASSWORD='REPLACE_GRAFANA_READER_PASSWORD'
```

Merge the following keys into the **existing** Compose services. This is a
fragment, not a replacement Compose file. Preserve images, dependencies, token
mounts, data volumes and all unrelated environment settings. Upstream uses
list-style environment entries; convert each service's complete environment
list to mapping style if using this example. Do not mix the two styles or leave
duplicate old username/password entries.

```yaml
services:
  influxdb:
    environment:
      INFLUXDB_HTTP_AUTH_ENABLED: "true"
    ports:
      - "127.0.0.1:8086:8086"
  garmin-fetch-data:
    environment:
      INFLUXDB_HOST: influxdb
      INFLUXDB_PORT: "8086"
      INFLUXDB_DATABASE: GarminStats
      INFLUXDB_USERNAME: garmin_collector
      INFLUXDB_PASSWORD: "${GARMIN_COLLECTOR_PASSWORD:?Set GARMIN_COLLECTOR_PASSWORD}"
  grafana:
    environment:
      GRAFANA_INFLUXDB_USER: grafana_reader
      GRAFANA_INFLUXDB_PASSWORD: "${GRAFANA_READER_PASSWORD:?Set GRAFANA_READER_PASSWORD}"
```

Remove obsolete InfluxDB initialization `INFLUXDB_USER`/`INFLUXDB_USER_PASSWORD`
entries with upstream example credentials. Keep `INFLUXDB_DB` and existing
storage/index settings. Initialization env variables only provision empty
volumes: changing them does **not** change users in this existing database.
Do not put the admin password into the InfluxDB container environment either.

For upstream's provisioned Grafana datasource, edit its existing YAML under
`Grafana_Datasource/`, already mounted at
`/etc/grafana/provisioning/datasources`. Merge this shape into the existing entry,
keeping its exact **name, UID and database** so dashboards still reference it.
Do not add a duplicate datasource. The sample UID is upstream's `garmin_influxdb`:

```yaml
apiVersion: 1
datasources:
  - name: Garmin-InfluxDB
    uid: garmin_influxdb
    type: influxdb
    access: proxy
    url: http://influxdb:8086
    database: GarminStats
    user: $GRAFANA_INFLUXDB_USER
    jsonData:
      version: InfluxQL
      httpMode: POST
    secureJsonData:
      password: $GRAFANA_INFLUXDB_PASSWORD
```

Use `secureJsonData.password`, removing an old plaintext `password` field.
The `$VARIABLE` syntax here is expanded by **Grafana**, not Compose; keep this
YAML in its separate provisioning file. Grafana recommends this form instead of
`${VARIABLE}` for passwords to avoid double expansion of embedded dollar signs.
The Compose `${VARIABLE:?...}` values above come from the private `--env-file`.
Simply having an env file on disk does not pass its values into a container.

If you configured the datasource manually instead, edit the existing datasource
in Grafana's UI after restarting it below: InfluxQL, database `GarminStats`, user `grafana_reader`, and its
password in the secure password field. Do not enable unrelated HTTP Basic Auth
or replace the internal URL with localhost. A provisioned datasource must be
changed in its file, or the next restart may overwrite UI changes.

Also change the Grafana website's default admin password in its UI when it is
running again; that login is separate from InfluxDB. Remove default startup credentials from Compose;
changing `GF_SECURITY_ADMIN_PASSWORD` alone does not rotate an existing login.

#### Enable Authentication And Verify

From now on, supply this env file for **every** Compose operation that loads
these substitutions, including future updates. If your stack already uses an
env file, preserve it too (Compose supports repeated `--env-file`, later wins).
Do not print `docker compose config`, `config --environment`, container
environments or `docker inspect` into tickets: expanded output can expose secrets.
Docker administrators can read container environment credentials; mode 0600 is
not encryption or isolation from them.

```bash
docker compose --env-file "$HOME/.config/garmin-grafana/influx.env" config --quiet
docker compose --env-file "$HOME/.config/garmin-grafana/influx.env" up -d --no-deps influxdb
docker compose --env-file "$HOME/.config/garmin-grafana/influx.env" port influxdb 8086
```

Keep the same volume attached. If a healthcheck uses anonymous queries, update
it for authenticated access without embedding secrets in its command. `/ping`
alone is liveness, not proof that database reads are authorized.

Verify anonymous access is rejected using **Host Access and Verification** below,
then check users and grants. The official v1 CLI accepts `-password ''` to prompt
without echo; keep Compose's default TTY (do not add `-T` or pipe its input):

```bash
docker compose --env-file "$HOME/.config/garmin-grafana/influx.env" exec influxdb \
  influx -username admin -password '' \
  -execute 'SHOW USERS; SHOW GRANTS FOR "garmin_collector"; SHOW GRANTS FOR "grafana_reader"; SHOW GRANTS FOR "omarchy_reader"'
```

Expect only the intended admin to have `admin=true`, collector `ALL PRIVILEGES`
on `GarminStats`, and each reader `READ` on only that database. Review all other
accounts, especially upstream's example `influxdb_user`. After confirming no
client uses it, retire it with an admin `DROP USER "influxdb_user"` query; if it
must remain, rotate its password via the protected SQL/body workflow in **2B**
and update its clients. Do not leave known default credentials active.

Restart clients with the new configuration (a plain `restart` does not apply
changed environment variables):

```bash
docker compose --env-file "$HOME/.config/garmin-grafana/influx.env" up -d --no-deps garmin-fetch-data grafana
```

Confirm Grafana's datasource test works and recent data appears, and that the
collector resumes normal sync-state reads and writes without authorization
errors. Inspect logs privately; do not paste raw collector output into issues.
Do not disable authentication or give applications admin access to fix errors.
After verifying, remove the temporary SQL file and empty directory:

```bash
rm -- "$admin_work/accounts.sql"
rmdir -- "$admin_work"
unset admin_work
```

Remove any editor backup/swap copies too. Deletion is not guaranteed secure
erasure on SSDs or snapshotting filesystems. Retain the passwords in your password
manager and the two application passwords in the private env file. Continue
with host verification, then step 3 for the plugin's separate reader password.

### 2B. Already Secured

Keep authentication enabled, preserve existing users, and ask your administrator
to create a new, non-admin `omarchy_reader` with only READ on the actual Garmin
database. No collector/Grafana migration is needed if they already have suitable
dedicated accounts: collector READ + WRITE, Grafana READ, admin not used by apps.

For a local admin, use the protected temporary-file creation/editor steps in
[Create The Accounts Safely](#create-the-accounts-safely), but put **only** these statements in the
file, with a new saved random password:

```sql
CREATE USER "omarchy_reader" WITH PASSWORD 'REPLACE_PLUGIN_READER_PASSWORD';
GRANT READ ON "GarminStats" TO "omarchy_reader";
```

After establishing the loopback binding below, submit with the existing InfluxDB
admin username (replace `admin` if yours differs):

```bash
curl -q --noproxy '*' --silent --show-error --fail-with-body --user admin \
  --data-urlencode "q@$admin_work/accounts.sql" \
  'http://127.0.0.1:8086/query'
```

`--user admin` with **no colon or password** prompts for the admin password
without echo. Run in a private interactive terminal. Check every JSON result for
errors, then verify the account with the container's v1 CLI, supplying your usual
Compose env-file/project options if needed:

```bash
docker compose exec influxdb influx -username admin -password '' \
  -execute 'SHOW USERS; SHOW GRANTS FOR "omarchy_reader"'
```

Expect `admin=false` for `omarchy_reader` and only `GarminStats / READ`.
Clean up the secret SQL file and editor copies using the cleanup steps in 2A.
Never create a second admin or reset shared users merely to install the plugin.

### Host Access And Verification

This applies to **both** starting points. If not already configured, merge the
following into the existing InfluxDB service, preserving its volumes and other
environment entries. Replace any unrestricted port binding, do not append:

```yaml
services:
  influxdb:
    environment:
      INFLUXDB_HTTP_AUTH_ENABLED: "true"
    ports:
      - "127.0.0.1:8086:8086"
```

Recreate only the database service with `docker compose up -d --no-deps influxdb`
using your normal env-file/project options. Check `docker compose port influxdb 8086`
shows only loopback. After restart, this credential-free check must return
HTTP `401`:

```bash
curl -q --noproxy '*' --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  'http://127.0.0.1:8086/query?q=SHOW%20DATABASES'
```

If it returns `200`, authentication is not enforcing the intended boundary.
Do not proceed until fixed. Verify grants as admin and reader access with step
4's `doctor`; do not write real health data as an access test. Reader grants
cover an entire database, not particular measurements or people. Source tags
are display filters, not an authorization boundary.

Database setup requires administrator privileges; the plugin itself should
never run as root or require access to Docker's socket. For remote deployments,
have the administrator configure a trusted HTTPS endpoint with certificate
validation and restricted network access; do not run the local unauthenticated
bootstrap remotely. Plain remote HTTP and redirects are rejected. A reachable
Grafana website does not imply a reachable InfluxDB; there is no Grafana proxy
fallback in this release.

References: [InfluxDB authentication](https://docs.influxdata.com/influxdb/v1/administration/authentication_and_authorization/),
[HTTP query API](https://docs.influxdata.com/influxdb/v1/api/query/),
[v1 CLI flags](https://docs.influxdata.com/influxdb/v1/tools/influx-cli/),
[1.11 importer source](https://github.com/influxdata/influxdb/blob/1.11/importer/v8/importer.go),
[1.11 client transport](https://github.com/influxdata/influxdb/blob/1.11/client/influxdb.go),
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).

## 3. Configure the Plugin Connection

Create the private directory and an empty file if one doesn't already exist:

```bash
umask 077
install -d -m 700 "$HOME/.config/omarchy-garmin-glance"
touch "$HOME/.config/omarchy-garmin-glance/connection.json"
chmod 600 "$HOME/.config/omarchy-garmin-glance/connection.json"
```

Edit the file locally, preserving an existing configuration if you have one:

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

Use an IANA timezone such as `Europe/Dublin` or `America/New_York`, not a fixed
UTC offset. Choose yours rather than copying the default blindly. Do not use
Garmin or Grafana credentials here: this is the InfluxDB reader account.

If multiple accounts/devices share the database, set exact-match source tags.
The optional upstream `User_ID` uses the actual display name, not necessarily
an email. Inspect your own schema rather than guessing tag values. Mixed
sources are rejected instead of averaged together. Leave tags empty for a
single-source database. All metrics must identify the same source.

Source filters are sent in GET query URLs. If a tag contains a personal display
name, InfluxDB or reverse-proxy access logs may retain it. Restrict log access
and retention, and redact query strings where appropriate. Passwords are sent
in the Authorization header, not the URL.

## 4. Install and Enable

Review the source first: Omarchy plugins run unsandboxed with your user access.
Add without automatic enable so you can check the connection first:

```bash
omarchy plugin add https://github.com/glavman/omarchy-garmin-glance.git
```

If asked to enable immediately, choose no. Public clone access needs no GitHub
credentials.

Run the diagnostic against the installed code:

```bash
python3 "$HOME/.config/omarchy/plugins/io.github.glavman.garmin-glance/backend.py" doctor
```

Expected: `status: "ok"` and `error: null`, or `partial` for missing/stale
measurements. Doctor deliberately returns null metric values to avoid exposing
health data; those nulls do **not** mean its query returned no values. An error
such as `auth_error` or `network_error` must be resolved before expecting data.

```bash
omarchy plugin enable io.github.glavman.garmin-glance
```

Click the `BB` bar item. Configure the bar metric and optional Grafana dashboard
URL through Omarchy bar settings. If the widget doesn't appear, check
`omarchy plugin list`, then restart the shell if needed.

Developers using a separate checkout may run `python3 install.py` from that
checkout instead. This creates a copied installation, not a Git-managed one.
Use the same installation method for later updates: `omarchy plugin update` for
Git-managed installs, or update the checkout and rerun `python3 install.py` for
copied installs. Run `omarchy restart shell` afterward.

## 5. Verify and Troubleshoot

```bash
omarchy-shell garmin-glance status
```

After opening the panel, expect `demo: false`, no error, and `chartsLoaded: true`.
`partial` is not always a connection problem: the watch may not provide HRV or
may not have synced recently. Older values are visibly marked stale.

| Symptom | Check |
|---|---|
| Connection refused | InfluxDB service, loopback port mapping, endpoint and firewall |
| `auth_error` | InfluxDB reader credentials, database grant and auth setting |
| `invalid_config` | Valid JSON, allowed fields, timezone, owner and mode 0600 |
| `ambiguous_source` | Actual source tags and whether multiple devices/accounts are mixed |
| Empty Body Battery | Upstream stress fetching, watch support and latest Garmin sync |
| Everything old | Collector health and watch upload; database reachability alone is insufficient |
| Plugin still shows demo | Set `demoMode` false in bar settings |
| Code updated but UI unchanged | Restart the Omarchy shell |

For a no-backend visual check, enable `demoMode` in bar settings. It uses only
synthetic values, never contacts InfluxDB, and does not overwrite live caches.
After changing connection source or timezone, restart the shell to clear its
in-memory data. Details on controls, freshness, updates and removal are in the
[README](../README.md).
