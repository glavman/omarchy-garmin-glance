# Marketplace Submission Draft

Not submitted. Before sending, publish and validate the final reviewed commit,
complete the [publishing checklist](PUBLISHING.md), and show the issue to the owner.
The owner must explicitly confirm every checkbox, including rights to the source
and preview assets. Only then change all five to `[x]` and submit. Unchecked boxes
below are intentionally not submission-ready.

Title: **[Plugin]: Garmin Glance**

Use only the following six sections as the issue body, in this order:

### Repository URL

https://github.com/glavman/omarchy-garmin-glance

### Category

Widgets

### Tags

bar, quickshell

### Suggest a missing tag

health

### Maintainer notes

Native Omarchy bar widget and dashboard with a labelled offline synthetic demo.
Standard `omarchy plugin add` and enable work without a database connection file;
preview does not query a database or launch an agent. We request normal install
classification; the live connection is optional configuration after preview.

Requires Omarchy 4 and Python 3.9+ with timezone data; no pip packages. Live data
requires a separately managed garmin-grafana collector and direct InfluxDB 1.x
access with enforced authentication and a dedicated non-admin READ account. The
plugin does not authenticate to Garmin or query the Grafana HTTP API. Existing
enabled previews must be disabled before preparing connection config, then enabled
only after authentication, grants and diagnostic checks.

Local Python helpers read private configuration and write health-data caches and
optional coaching sessions. Browser links and copying the setup prompt require
explicit actions. Optional Coach hands selected-window health summaries and
sanitized activities to the user's existing agent only after disclosure and
approval; that agent can send data to cloud providers and remains unsandboxed.
Removal retains private configuration/cache and never stops the external collector
or deletes its database. These boundaries are documented in the README.

The repository includes a developer-only `install.py` and setup QML/JS; standard
Git installation does not execute that installer. Installer/setup capabilities
and privilege-related documentation may require static-baseline maintainer review.
Root preview artwork uses synthetic demo data, not personal records. This draft
does not assert a baseline pass or completed lifecycle/live-provider verification.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
