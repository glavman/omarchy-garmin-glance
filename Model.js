function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  var date = new Date(value + "T00:00:00Z")
  return isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function validTime(value) {
  return typeof value === "string"
    && /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value)
    && validDate(value.slice(0, 10)) && isFinite(Date.parse(value))
}

function validValue(key, value) {
  return value === null || (typeof value === "number" && isFinite(value) && value >= 0
    && (["bodyBattery", "sleep"].indexOf(key) < 0 || value <= 100))
}

function valid(data) {
  if (!data || data.schemaVersion !== 1 || ["ok", "partial", "error", "cached", "demo"].indexOf(data.status) < 0
      || !data.metrics || !data.charts || !validTime(data.fetchedAt)
      || typeof data.timezone !== "string" || !data.timezone
      || (data.chartsFetchedAt !== null && !validTime(data.chartsFetchedAt))) return false
  var names = ["bodyBattery", "steps", "sleep", "hrv"]
  var units = ["score", "steps", "score", "ms"]
  for (var i = 0; i < names.length; i++) {
    var metric = data.metrics[names[i]]
    if (!metric || metric.unit !== units[i] || !validValue(names[i], metric.value)
        || ["fresh", "stale", "missing"].indexOf(metric.state) < 0
        || (metric.time !== null && !validTime(metric.time))
        || (metric.date !== null && !validDate(metric.date))
        || (metric.value === null ? metric.state !== "missing" || metric.expiresAt !== null
            : metric.state === "missing" || !validTime(metric.time) || !validDate(metric.date)
              || !validTime(metric.expiresAt) || Date.parse(metric.expiresAt) <= Date.parse(metric.time))) return false
  }
  var keys = ["bodyBattery", "steps", "sleep"]
  for (var j = 0; j < keys.length; j++) {
    var points = data.charts[keys[j]]
    if (!Array.isArray(points) || points.length > (j === 0 ? 2000 : 7)
        || (points.length && data.chartsFetchedAt === null)) return false
    for (var p = 0; p < points.length; p++)
      if (!points[p] || !validValue(keys[j], points[p].value)
          || !(j === 0 ? validTime(points[p].time) : validDate(points[p].date))) return false
  }
  return true
}

function format(metric) {
  if (!metric || metric.value === null || typeof metric.value !== "number" || !isFinite(metric.value)) return "--"
  return metric.unit === "steps" && metric.value >= 1000 ? (metric.value / 1000).toFixed(1) + "k" : String(Math.round(metric.value))
}

function stale(key, metric, now, fetchedAt) {
  if (!metric || metric.value === null || metric.state !== "fresh" || !isFinite(now)
      || !validTime(fetchedAt) || !validTime(metric.time) || !validTime(metric.expiresAt)
      || now < Date.parse(metric.time)) return true
  if (now - Date.parse(fetchedAt) > 3600000) return true
  // Steps expire at source-local midnight; age-based metrics include their deadline.
  return key === "steps" ? now >= Date.parse(metric.expiresAt) : now > Date.parse(metric.expiresAt)
}

function errorMessage(code) {
  var messages = {
    invalid_config: "Check the private connection.json file and its permissions.",
    auth_error: "Database credentials were rejected. Check the read-only account.",
    network_error: "Cannot reach InfluxDB. Check that the local stack is running.",
    timeout: "InfluxDB did not respond in time.",
    ambiguous_source: "Multiple sources found. Set account/device tags in connection.json.",
    cache_error: "Cannot access the private dashboard cache.",
    query_error: "A database query failed. Check the supported InfluxDB schema.",
    invalid_response: "The database returned unsupported data.",
    truncated_response: "Database results exceeded the supported size.",
    fetch_locked: "Another refresh is in progress.",
    cache_miss: "No cached data yet.",
    redirect_refused: "Database redirects are not allowed. Configure the final endpoint."
  }
  return code ? (messages[code] || "The database request failed.") : ""
}
