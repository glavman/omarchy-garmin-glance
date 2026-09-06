var documentationUrl = "https://github.com/glavman/omarchy-garmin-glance/blob/main/docs/SETUP.md"
var prompt = [
  "Set up Garmin Glance with my existing stack. Load your Omarchy skill and follow:",
  documentationUrl,
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
  "Add only if not installed, without enabling. Keep disabled, verify enforced auth,",
  "non-admin READ-only grants and doctor, then enable and check live status plus",
  "existing collector/Grafana health. Preserve unrelated settings. If approval or",
  "secure secret entry is unavailable, stop that step.",
  "Report changes/blockers without secrets or health values. No commits, pushes or screenshots."
].join("\n")
