# Contributing

Pull requests are welcome: fixes, features, documentation and tests. AI-assisted
contributions are welcome too; review the result and verify it before submitting.
For larger changes, open an issue first so we can agree on the direction.

## Develop

Fork the repository and work in a separate checkout, not the installed plugin
directory. Use Omarchy 4, Python 3.9+ and Qt 6 tooling. No pip packages are needed.

- `backend.py`: read-only InfluxDB queries, source validation and private cache.
- `Model.js`: payload validation, formatting and activity summaries.
- `Panel.qml`, `Chart.qml`, `StressChart.qml`: dashboard and native navigation.
- `Service.qml`, `Grafana.js`: refresh lifecycle and browser links.
- `tests/`: synthetic backend, model, link and navigation checks.

Tests do not require a live Garmin stack. Use fabricated fixtures and demo mode
for UI work. See the [reference](docs/REFERENCE.md) for data semantics and the
[setup guide](docs/SETUP.md) if you need to test your own connection.

To try a reviewed build locally, run `python3 install.py` from your checkout,
then `omarchy restart shell`. This replaces the installed plugin with a copied
build, preserves a backup and enables it. It is not a Git-managed installation;
see [installation methods](docs/REFERENCE.md#install-and-update).

## Verify

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests
omarchy plugin validate .
git diff --check
```

For panel changes, also run the [native navigation tests](docs/REFERENCE.md#diagnostics-and-tests)
and check narrow layouts, mouse interaction and keyboard-only use. The offscreen
runner can skip native tests; report those skips rather than calling them passes.

## Keep It Safe

- Never include credentials, tokens, private connection files, real health data
  or unredacted logs in commits, issues or PRs. Use synthetic screenshots only.
- Keep database access read-only, queries bounded and source filtering intact.
  Missing values must not become zero; cached data must keep its original age.
- Do not add Garmin authentication to the plugin or change users' collectors,
  databases or Grafana dashboards as a side effect.
- Follow Omarchy's native styling and keyboard conventions. Never modify
  `/usr/share/omarchy/` for a plugin change.
- Add regression tests for changed behavior. Update documentation and the
  installer allowlist when introducing files needed by the installed plugin.

## Open A PR

Keep changes focused and target `main`. Explain what changed and why, link any
related issue, and list the checks you ran plus anything you could not verify.
For UI changes, describe the interaction or include a cropped demo screenshot.

Bug reports are welcome too. Include reproduction steps, expected and actual
behavior, and Omarchy/Quickshell versions. Do not paste live `fetch` or `cache`
output: it contains health data. Review even diagnostic output before sharing.
