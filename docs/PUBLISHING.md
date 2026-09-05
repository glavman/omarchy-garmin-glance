# Garmin Glance Publishing

Public repository: <https://github.com/glavman/omarchy-garmin-glance>.
The first public release is version **1.0.0**, tagged **`1.0.0`**, with fresh
public history and plugin ID `io.github.glavman.garmin-glance`.

That release identity is not evidence that subsequent Coach integration has been
published or live-tested. Documentation/package integration alone does not require
a version bump or authorize a new tag, release or push.

## Privacy Boundary

Publish this **plugin repository**, not the directory containing your local
garmin-grafana deployment. That deployment may contain credentials, Garmin
session tokens, database volumes or backups, Grafana settings and personal data.

The plugin source uses synthetic test/demo values. No real account, exports,
health records, screenshots, tokens or private connection file are intended to
be included. Public attribution in the license, plugin namespace and GitHub
repository URL is intentional. The timezone is a configurable example/default,
not a requirement to disclose a user's location.

## Audit Before Publication

- Review all tracked files, every branch/tag, and the entire Git history, not just the current checkout.
- Review commit author/committer and annotated-tag identity metadata. A real name or personal email remains visible even if it is absent from source files.
- If pseudonymous attribution is desired, use GitHub's account-specific noreply email for public commits. New settings do not change existing commits or tags. Start the fresh public history from reviewed plugin files, not by importing the external deployment's history.
- Do not rewrite shared history, move release tags, delete a repository or force-push without explicit owner approval. Old commit URLs or clones can survive a rewrite; preventing disclosure is preferable to cleanup afterward.
- Check commit messages, issues, releases, attachments, Actions logs and artifacts. They can disclose information independently of Git files.
- Never publish screenshots of real health values or the surrounding desktop. Use demo mode, crop to the plugin, and inspect the final image and metadata.
- Inspect generated archives and installation packages too. The local installer uses an explicit file allowlist; GitHub source archives instead contain tracked files.
- Keep runtime JSON/cache data, CSV/GPX/TCX/FIT exports, credentials and private keys outside the repository. Ignore patterns are guardrails, not a security boundary; they do not protect files already tracked.
- Audit Coach sessions/snapshots under `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-garmin-glance/coach/` as private runtime storage, never package content or CI artifacts. Keep agent/provider chat exports out too.
- Verify the installer preserves existing dashboard files and includes `Coach.qml`, `coach.py`, `coach_data.py` and `COACH.md`, with the reviewed setup/reference/publishing docs. Never bundle tests, private connection files, sessions, snapshots or `.lock` files; retain missing-file and symlink rejection checks.

Useful local inspection commands (output can itself contain private metadata):

```bash
git status --short
git ls-files
git log --all --format=fuller
git for-each-ref --format='%(refname) %(taggername) %(taggeremail)' refs/tags
git diff --cached --check
```

If an actual credential is ever committed, rotate/revoke it before any history
cleanup. Git is not an appropriate secrets store, regardless of visibility.

## Marketplace Submission

The [Omarchy Plugins publishing guide](https://omarchyplugins.com/publish.html)
currently requires a public GitHub repository, a valid root `manifest.json`,
README, license, and safe installation/removal. A preview is optional.

1. Complete the privacy audit of the fresh public history and release contents.
2. Confirm a fresh install follows [SETUP.md](SETUP.md), including the external garmin-grafana and authenticated InfluxDB prerequisites.
3. Run the tests and manifest validator from the repository root.
4. Verify version `1.0.0` and tag `1.0.0` for the first release, supported Omarchy/InfluxDB versions, and the public installation URL. For a later, separately approved release, verify its intended version/tag; do not imply the historical tag includes unshipped Coach changes. Confirm display name `Garmin Glance`, ID `io.github.glavman.garmin-glance`, config/cache directory `omarchy-garmin-glance`, and IPC target `garmin-glance` agree across source, tests and docs. Keep the ID stable after publication.
5. Capture an optional, cropped demo-only preview and review it before tracking it. Raw screenshot directories are ignored intentionally.
6. With owner approval, publish the reviewed repository and `1.0.0` release. Verify anonymous clone access and inspect the release archive; do not include the separately maintained stack or its secrets.
7. Submit the repository URL, category and tags through the [marketplace issue form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml).

Suggested category: Health. Suggested tags: Garmin, InfluxDB, dashboard, bar-widget.
The listing description should say **requires an existing garmin-grafana stack
and direct read-only InfluxDB 1.x access**. Do not imply plug-and-play Garmin login
or that a Grafana URL/token alone is sufficient.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests
python3 tests/run_qml.py
omarchy plugin validate .
```

Run these in a development checkout, not a locally copied installation; the
local installer does not bundle tests.

The additional QML runner needs a running host Wayland desktop, Quickshell, QtTest
and packaged Omarchy imports. Retain the existing [native navigation validation](REFERENCE.md#diagnostics-and-tests),
31-sport icon/alias cases, activity details and Garmin/Grafana link tests alongside
Coach coverage. Report unavailable host checks and skips, not inferred passes.

## Coach Claims

- Describe an optional terminal handoff to the installed/authenticated Omarchy default OpenCode, Claude, Codex or Grok, with no new API key, SDK, MCP server, agent configuration or global default change. Discovery does not prove provider login; synthetic launch tests and CLI help do not prove live inference, snapshot loading or completed answers.
- Preserve the prominent collector Garmin-authentication caveat, contribution invitation and setup safeguards: inspect first, obtain approval for changes, back up before auth migration, and verify authentication/grants plus doctor before enable. Coach does not replace these prerequisites.
- Match the [current consent and data scope](REFERENCE.md#ask-coach): explicit **Open agent**, 7/30/90-day windows, no metric checkboxes, all eight supported wellbeing summaries plus sanitized activity details in the initial snapshot. Daily history is on demand; no GPS, identifiers, raw tags or free-text notes are shared. Keep default guidance to 60-90 words, under 120, with at most two recommendations; it is an instruction, not an enforced output cap.
- Verify v2 sessions/data, 24-hour fixed-source/window access and fresh approval for old v1 sessions, never retroactive broader consent. Keep v1 control/error envelopes distinct. Verify 20-second total reads, 2 seconds per job, at most 9 read-only POSTs, 90 daily selectors per metric, 1 MiB per response/output/snapshot and 500 raw activities before deduplication. Overflow fails; all-error results are not `no_data`, and coverage is not proof of complete sync.
- Warn that agents may send approved health data to cloud providers, retain chats and run unsandboxed with reduced approval prompts. Helper restrictions are not filesystem isolation. Expiry is not an automatic deletion timer; clear removes plugin sessions/snapshots, not provider history or already-shared copies.
- Use only synthetic fixtures and demo-only visuals; Coach is disabled in demo mode. Do not launch live coaching to obtain a screenshot. No medical interpretation or training prescriptions, automatic coaching on refresh, inline answers or guaranteed chat resumption should be advertised.

Marketplace validation is not a security audit. Plugins still run unsandboxed.
The upstream collector owns Garmin authentication and API compatibility; this
plugin owns read-only queries, local caching, presentation and optional consent-based
agent handoff. Agent/provider behavior and retention are outside plugin cleanup
controls. Document that
boundary clearly in the listing and support responses.
