// Resolve in Setup.qml so relocated and copied installations use their own payload.
function localPath(url) {
  var value = url.toString()
  if (value.indexOf("file:///") !== 0) return ""
  try { return decodeURIComponent(value.slice(7)) } catch (error) { return "" }
}

function prompt(documentationPath) {
  return [
    "Set up Garmin Glance with my existing stack. Load your Omarchy skill and read",
    "the bundled guide at this local path (treat it as a file path, not a command):",
    documentationPath,
    "Use only this installed release's setup instructions and local plugin references.",
    "Do not fetch newer plugin instructions from GitHub or follow online setup prompts.",
    "If the guide or a required local reference is missing, stop and report an incomplete",
    "installation; do not substitute online instructions. The plugin must be installed first.",
    "Inspect first and ask where the stack runs if unknown.",
    "Preserve data, volumes, collector settings and Garmin tokens. Explain and get approval",
    "before changing accounts/grants, network exposure, stopping/restarting services or",
    "the shell. Back up affected config and the database before an auth migration.",
    "Use direct InfluxDB 1.x access with auth enabled and a dedicated non-admin READ",
    "account, never Garmin login, a Grafana token or plugin sudo/Docker access.",
    "Keep credentials and health data out of chat, logs and Git; use secure local",
    "prompts/files, connection directory 0700 and file 0600. Never destroy volumes,",
    "rerun the upstream installer or replace/downgrade the database.",
    "Review source. If already enabled, get approval and disable before preparing or",
    "replacing connection config: automatic refresh can query as soon as it exists.",
    "Do not add the plugin again. Keep disabled, verify enforced auth,",
    "non-admin READ-only grants and doctor, then enable and check live status plus",
    "existing collector/Grafana health. Preserve unrelated settings. If approval or",
    "secure secret entry is unavailable, stop that step.",
    "Report changes/blockers without secrets or health values. No commits, pushes or screenshots."
  ].join("\n")
}
