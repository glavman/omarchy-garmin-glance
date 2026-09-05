# Garmin Glance Publishing

Public repository: <https://github.com/glavman/omarchy-garmin-glance>.
The first public release is version **1.0.0**, tagged **`1.0.0`**, with fresh
public history and plugin ID `io.github.glavman.garmin-glance`.

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
4. Verify version `1.0.0` and tag `1.0.0`, supported Omarchy/InfluxDB versions, and the public installation URL. Confirm display name `Garmin Glance`, ID `io.github.glavman.garmin-glance`, config/cache directory `omarchy-garmin-glance`, and IPC target `garmin-glance` agree across source, tests and docs. Keep the ID stable after publication.
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
omarchy plugin validate .
```

Run these in a development checkout, not a locally copied installation; the
local installer does not bundle tests.

Marketplace validation is not a security audit. Plugins still run unsandboxed.
The upstream collector owns Garmin authentication and API compatibility; this
plugin owns read-only queries, local caching and presentation. Document that
boundary clearly in the listing and support responses.
