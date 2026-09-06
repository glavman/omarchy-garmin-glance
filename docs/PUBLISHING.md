# Garmin Glance Publishing

Public repository: <https://github.com/glavman/omarchy-garmin-glance>.
The current source prepares version **1.1.0** for marketplace submission, with
plugin ID `io.github.glavman.garmin-glance`. The historical **`v1.0.0`** tag points
to the initial release, not the later activity, Coach or offline-onboarding work.
A source version is not evidence of publication or live testing. Creating a tag,
release, commit, push or submission requires separate owner approval.

## Privacy Boundary

Publish this **plugin repository**, not the directory containing your local
garmin-grafana deployment. That deployment may contain credentials, Garmin
session tokens, database volumes or backups, Grafana settings and personal data.

The plugin source uses synthetic test/demo values. No real account, exports,
health records, real-data screenshots, tokens or private connection file are
intended to be included. Reviewed synthetic-demo artwork is allowed. Public
attribution in the license, plugin namespace and GitHub
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
- Verify the local copy installer preserves existing dashboard files and includes `Coach.qml`, `coach.py`, `coach_data.py` and `COACH.md`, with the reviewed setup/reference/publishing docs. Its runtime package excludes tests and artwork; normal Git installs and source archives include tracked tests and reviewed artwork. Never bundle private connection files, sessions, snapshots or runtime `.lock` files; retain missing-file and symlink rejection checks.

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

The [Omarchy Plugins publishing guide](https://plugins.omarchy.org/publish.html)
and [submission contract](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md)
require a public GitHub repository, one valid root `manifest.json`, root README
with installation/removal instructions, license, documented dependencies, a unique
plugin ID, and safe installation/removal. A preview, release tag and hosted CI are
not mandatory. Submit an issue, not a hand-written registry pull request.

Listing metadata:

- Repository: `https://github.com/glavman/omarchy-garmin-glance`
- Category: **Widgets**
- Tags: **bar**, **quickshell**
- Optional missing-tag suggestion: **health** (not an actual tag until accepted)
- ID: `io.github.glavman.garmin-glance` (permanent; do not rename)

The manifest's `barWidget.category: "Health"` is a shell setting, not the
marketplace category. The marketplace reads name, author, version and description
from the manifest. Its summary must distinguish the working offline demo from
live data, which **requires an existing garmin-grafana stack and direct read-only
InfluxDB 1.x access**. A Grafana URL/token alone is insufficient.

Root `preview.png` is a cropped, metadata-stripped copy of the reviewed synthetic
dashboard screenshot, retaining the visible Demo label. README images under
`docs/screenshots/` are not automatically discovered as marketplace previews.
The marketplace generates card/detail images itself; inputs must be valid images
under 50 MiB and 40 megapixels. Inspect pixels and metadata after any replacement.

### Readiness Checks

1. Audit tracked files, history, public metadata and any release archive. Keep personal runtime data out of all test reports and artifacts.
2. On an isolated Omarchy desktop, test the standard install below without `install.py`. With no connection file, opening the watch must show labelled demo data, make no database requests and launch no agent.
3. Test click, Escape, shell summon/hide, narrow layouts, disable/re-enable, shell restart, update and removal. Confirm unrelated configuration survives and removal leaves private config/cache and the external stack as documented. Do not modify an existing user's installation just to run this checklist.
4. For live setup, follow [SETUP.md](SETUP.md): obtain approval to disable an already-enabled preview before preparing/replacing config, verify enforced authentication, non-admin READ-only grants and `doctor`, then enable. Invalid config and network/auth failures must not silently become demo data. Never use real health data in automated tests or public evidence.
5. Run the automated checks below and record the exact commit, Omarchy/Quickshell versions, results and skips. Synthetic helper tests do not prove a real add/update/remove lifecycle, live grants or provider inference.
6. Reconcile the intended version in `manifest.json`, installer output and IPC status. With owner approval, publish the tested changes; do not move `v1.0.0`. A new release/tag is optional and must not be presented as already published.
7. Validate the final public commit with the marketplace compatibility checker and static baseline. Address findings and document capabilities for maintainer review. Keep `main` stable while that exact snapshot awaits approval.
8. Complete the [submission draft](SUBMISSION.md), show its title and body to the owner, and obtain explicit confirmation of all five checklist statements before submitting through the [issue form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml). Do not pre-approve ownership or claim verification on the owner's behalf.

Standard installation in the isolated desktop:

```bash
omarchy plugin add https://github.com/glavman/omarchy-garmin-glance.git --enable
```

The normal installer does not execute `install.py` or provision the collector.
Request normal installation classification because offline preview works without
configuration; marketplace maintainers decide the classification. Dependencies and
capabilities belong in the README and submission notes, not invented manifest
`permissions` or `dependencies` fields. Plugins remain unsandboxed.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests/tst_model.qml
python3 tests/run_qml.py
omarchy plugin validate .
git diff --check
```

Run these in a development checkout, not a locally copied installation; the
local installer does not bundle tests.

The offscreen command checks only the model; plain `qmltestrunner -input tests`
cannot load all suites. The full QML runner needs a running host Wayland desktop, Quickshell, QtTest
and packaged Omarchy imports. Retain the existing [native navigation validation](REFERENCE.md#diagnostics-and-tests),
31-sport icon/alias cases, activity details and Garmin/Grafana link tests alongside
Coach coverage. Report unavailable host checks and skips, not inferred passes.

### Marketplace Preflight And Updates

From a separately reviewed marketplace checkout with Node.js 24+ and its locked
dependencies installed, these official interfaces inspect the public default
branch, not unpublished local edits. Use a private temporary directory for reports:

```bash
REPORT_DIR=$(mktemp -d)
VALIDATION_METADATA_PATH="$REPORT_DIR/validation.json" \
  node scripts/validate-submission.mjs \
  --repo=https://github.com/glavman/omarchy-garmin-glance
node scripts/security-baseline.mjs \
  --metadata="$REPORT_DIR/validation.json" --json="$REPORT_DIR/baseline.json"
```

Inspect the JSON outcome, not just the exit code. A completed scan can report
`review-required` or `needs-fixes` with exit zero. Setup/installer files and
privilege references can require review even when standard installation does not
execute a custom installer. Never suppress or fabricate baseline evidence.

The [security policy](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md)
requires exact-commit evidence and explicit maintainer approval. Approval applies
to a snapshot, not all future changes or a security guarantee. Per the
[verification rules](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/VERIFICATION.md),
later upstream commits can show **Update unverified**. Request verification and
publication of each newer intended snapshot using the marketplace's Plugin
verification form. Omarchy install/update currently follows upstream HEAD rather
than pinning to the marketplace's verified SHA.

### Readiness Record (2026-09-06)

Local candidate: uncommitted 1.1.0 changes based on
`3a77f6aeeb112f373d30f1881d98cc60274d2929`. This is not a published or verified
1.1.0 snapshot. Host: Omarchy 4.0.2-1, Quickshell 0.3.1.

| Check | Result and scope |
| --- | --- |
| Python suite | Final local candidate rerun: 261 passed |
| Offscreen model | 1,430 passed, no failures or skips |
| Full native QML | Final local candidate rerun on an awake desktop: 1,582 passed, no failures or skips. Earlier locked/DPMS-off rendering failures are resolved on the awake desktop |
| Manifest / QML lint / whitespace | `omarchy plugin validate .`, `qmllint` on entry/panel/setup/Coach files, and `git diff --check` passed |
| Local marketplace artifacts | Genuine manifest validator and preview processor accepted 1.1.0 and the 926 x 1184 preview; PNG contains no text/EXIF metadata |
| Submission parser | Unchecked draft rejected as intended; checked in-memory syntax fixture accepted. No owner confirmation or submission performed |
| Public compatibility | Passed for remote `3a77f6a`, which does not include these local changes |
| Public static baseline | Complete `review-required`, no findings, `installer` and `privilege` capabilities, for remote `3a77f6a` only |
| Local advisory detectors | No findings in 20 root text files; same capabilities. Not a canonical or complete snapshot baseline |
| Disposable VM lifecycle | Passed official add, historical fast-forward update, candidate validation/enable, demo, click/Escape, summon/hide, disable/re-enable, restart, invalid-config refusal and removal/retention checks. See scope below |

Marketplace preflight used source
`72c3d5bb773c86936caa8469426a8384047e1c13`. The privilege evidence matches the
warning against plugin sudo/Docker access, not a privileged invocation; the
reported capability remains subject to maintainer review.

The disposable VM used the official checksum-verified Omarchy 4.0.2 ISO, 4 vCPUs,
6 GiB RAM and a 40 GiB sparse disk. Installation and testing were offline, with no
NIC, shared directories, clipboard or forwarded credentials. It was cleanly shut
down and its disk integrity check passed. The guest ran Omarchy 4.0.2-1,
Quickshell 0.3.1 and Hyprland 0.56.2.

Official add used a guest-local clone of public history; update fast-forwarded
`b2fbfc4` to `3a77f6a`. The unpublished 1.1.0 candidate was transferred as an
explicitly allowlisted, hashed read-only media snapshot and overlaid while
disabled. This verifies candidate runtime behavior, not published 1.1.0 Git
distribution. A read-only directory mode inherited from the transfer media
initially prevented removal; correcting that guest fixture's owner permissions
allowed official removal to pass. Synthetic config/cache bytes survived removal,
and unrelated shell settings matched the pre-enable baseline.

No Coach action or provider handoff was invoked and no Coach helper/session was
observed. A broad no-agent-process assertion did encounter a transient Codex
process matching the stock agent-usage probe; its parent provenance was not
captured. Do not claim that no agent process ran anywhere in the guest. With no
NIC, network access was impossible, but this is not proof that no request was
attempted. Narrow-layout checks passed in the isolated QML suite, not at alternate
VM display resolutions.

Outstanding gates before submission:

- Repeat Git add/update against the final published candidate; the VM's local public-history clone and file overlay did not test HTTPS distribution of 1.1.0.
- Publish only with owner approval, then rerun exact-commit marketplace checks on the final public HEAD. Local validation cannot confer snapshot verification.
- Review the completed issue with the owner and explicitly confirm all five submission statements before sending.

No real database grants, health records or provider inference were exercised.
The host's installed plugin was not replaced, enabled/disabled, removed or
restarted. Lifecycle commands and the full test desktop ran only inside the VM;
the native QML tests used temporary test windows on the host.

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
