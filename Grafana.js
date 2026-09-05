function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  var date = new Date(value + "T00:00:00Z")
  return isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function validBounds(point) {
  return !!point && typeof point.from === "number" && typeof point.to === "number"
    && isFinite(point.from) && isFinite(point.to)
    && Math.floor(point.from) === point.from && Math.floor(point.to) === point.to
    && Math.abs(point.from) <= 8640000000000000 && Math.abs(point.to) <= 8640000000000000
    && point.from < point.to
}

function validIpv4(host) {
  var parts = host.split(".")
  return parts.length === 4 && parts.every(function(part) {
    return /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) <= 255
  })
}

function validIpv6(host) {
  if (host.indexOf(".") >= 0) {
    var last = host.lastIndexOf(":")
    if (!validIpv4(host.slice(last + 1))) return false
    host = host.slice(0, last + 1) + "0:0"
  }
  var halves = host.split("::")
  if (halves.length > 2) return false
  var parts = []
  for (var i = 0; i < halves.length; i++)
    if (halves[i]) parts = parts.concat(halves[i].split(":"))
  return (halves.length === 2 ? parts.length < 8 : parts.length === 8)
    && parts.every(function(part) { return /^[a-f0-9]{1,4}$/i.test(part) })
}

// Pure URL construction: no clock, network, configuration, or QML globals.
function build(baseUrl, payload, context) {
  var error = "Set a valid http(s) Grafana URL in bar settings."
  try {
    if (typeof baseUrl !== "string" || baseUrl.length > 8192
        || /[\s\x00-\x1f\x7f-\x9f\\]/.test(baseUrl)) throw new Error()
    // QML's decoder accepts UTF-8 surrogate encodings that browsers reject.
    encodeURIComponent(baseUrl)
    var decoded = decodeURIComponent(baseUrl)
    encodeURIComponent(decoded)
    if (/%ed%[ab][0-9a-f]%[89ab][0-9a-f]/i.test(baseUrl)
        || /[\x00-\x1f\x7f-\x9f\\]/.test(decoded)) throw new Error()
    var url = /^(https?:\/\/)([^/?#]+)([^?#]*)(\?[^#]*)?(#.*)?$/i.exec(baseUrl)
    if (!url) throw new Error()
    var authority = /^(\[[^\]]+\]|[^:]+)(?::([0-9]+))?$/.exec(url[2])
    if (!authority || /[@%]/.test(authority[1])) throw new Error()
    var host = authority[1]
    if (host[0] === "[") {
      if (!validIpv6(host.slice(1, -1))) throw new Error()
    } else {
      if (host.length > 253 || !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9.])?$/i.test(host)) throw new Error()
      var labels = host.replace(/\.$/, "").split(".")
      if (!labels.every(function(label) {
        return label.length <= 63 && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(label)
      })) throw new Error()
      if (/^[0-9.]+$/.test(host) && !validIpv4(host)) throw new Error()
    }
    if (authority[2] !== undefined && (Number(authority[2]) < 1 || Number(authority[2]) > 65535)) throw new Error()
    if (context === undefined) return {url: baseUrl, error: ""}

    error = "Use a Grafana base URL or a /d/UID/slug dashboard URL."
    var path = url[3]
    var segments = path.replace(/^\//, "").replace(/\/$/, "").split("/")
    if (path && path !== "/") {
      for (var s = 0; s < segments.length; s++) {
        segments[s] = decodeURIComponent(segments[s])
        if (!segments[s] || segments[s] === "." || segments[s] === ".."
            || /[/?#\\]/.test(segments[s])) throw new Error()
      }
      var dashboard = segments.indexOf("d")
      if (dashboard >= 0) {
        if (dashboard !== segments.length - 3 || !/^[a-z0-9_-]+$/i.test(segments[dashboard + 1])) throw new Error()
      } else {
        if (segments.some(function(segment) {
          return ["d-solo", "dashboard", "dashboards", "explore", "login", "api"].indexOf(segment) >= 0
        })) throw new Error()
        path = path.replace(/\/$/, "") + "/d/feiibsx498gsgb/garmin-stats"
      }
    } else path = "/d/feiibsx498gsgb/garmin-stats"

    error = "Choose a supported Grafana context."
    if (!context || typeof context !== "object" || Array.isArray(context)) throw new Error()
    var keys = ["steps", "sleep", "sleepDuration", "hrv", "restingHeartRate", "stress", "bodyBattery"]
    var key = context.key
    var index = keys.indexOf(key)
    if (index < 0 && ["overlay", "activity", "activityGps"].indexOf(key) < 0) throw new Error()
    if (index >= 0 && ["current", "history"].indexOf(context.kind) < 0) throw new Error()
    var selected = context.date === undefined ? "" : context.date
    if (index >= 0 && selected !== "" && !validDate(selected)) throw new Error()

    error = "Refresh Garmin data to load Grafana time bounds."
    if (!payload || typeof payload !== "object" || Array.isArray(payload)
        || typeof payload.timezone !== "string" || payload.timezone.length > 128
        || !/^[a-z0-9_+-]+(?:\/[a-z0-9_+-]+)*$/i.test(payload.timezone)) throw new Error()
    var range
    var panel
    var selector
    if (index >= 0) {
      var wellness = ["sleepDuration", "restingHeartRate", "stress"].indexOf(key) >= 0
      if (context.kind === "current") {
        panel = [30, 12, 32, 11, 28, 29, 29][index]
        var metrics = payload[wellness ? "wellness" : "metrics"]
        range = metrics && metrics[key]
      } else {
        panel = [1, 12, 32, 11, 11, 51, 66][index]
        var bundle = payload[wellness ? "supplementalHistory" : "history"]
        var points = bundle && bundle[key]
        if (!Array.isArray(points) || !points.length) throw new Error()
        range = {from: Infinity, to: -Infinity}
        var found = false
        for (var p = 0; p < points.length; p++) {
          var point = points[p]
          if (!point || !validDate(point.date)) throw new Error()
          if (selected && point.date !== selected) continue
          if (!validBounds(point)) throw new Error()
          found = true
          range.from = Math.min(range.from, point.from)
          range.to = Math.max(range.to, point.to)
        }
        if (!found) throw new Error()
      }
    } else if (key === "overlay") {
      panel = 29
      range = context
    } else {
      error = "Refresh Garmin data to load activity timing."
      var activity = payload.latestActivity
      if (!activity || typeof activity.time !== "string"
          || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(activity.time)
          || !validDate(activity.time.slice(0, 10))) throw new Error()
      var start = Date.parse(activity.time)
      var duration = activity.durationSeconds
      var hasDuration = typeof duration === "number" && isFinite(duration) && duration > 0
      if (key === "activityGps" && !hasDuration) throw new Error()
      range = {from: start - 60000, to: Math.ceil(start + (hasDuration ? duration * 1000 : 0)) + 60000}
      panel = key === "activityGps" ? 50 : null
      if (key === "activityGps") {
        error = "Refresh Garmin data to load the activity GPS selector."
        selector = activity.gpsSelector
        if (typeof selector !== "string" || !selector.trim()) throw new Error()
        var printable = selector.replace(/[\ud800-\udbff][\udc00-\udfff]/g, "x")
        if (printable.length > 256
            || /[\x00-\x1f\x7f-\x9f\u00a0\u00ad\u1680\u2000-\u200f\u2028-\u202f\u205f-\u206f\u3000\ud800-\uf8ff\ufeff\ufff9-\ufffb\ufffe\uffff]/.test(printable)) throw new Error()
      }
    }
    error = "Refresh Garmin data to load Grafana time bounds."
    if (!validBounds(range)) throw new Error()

    var owned = ["var-ActivityGPS", "time", "time.window", "from", "to", "viewPanel", "panelId", "timezone", "var-TimeZone"]
    var query = url[4] ? url[4].slice(1).split("&") : []
    query = query.filter(function(pair) {
      var name = decodeURIComponent(pair.split("=")[0].replace(/\+/g, " "))
      return owned.indexOf(name) < 0
    })
    // Backend bounds are exclusive; Grafana's absolute upper endpoint is inclusive.
    query.push("from=" + range.from, "to=" + (range.to - 1),
      "timezone=" + encodeURIComponent(payload.timezone), "var-TimeZone=" + encodeURIComponent(payload.timezone))
    if (panel !== null) query.push("viewPanel=panel-" + panel)
    if (selector !== undefined) query.push("var-ActivityGPS=" + encodeURIComponent(selector))
    error = "Set a valid http(s) Grafana URL in bar settings."
    var result = url[1] + url[2] + path + "?" + query.join("&") + (url[5] || "")
    if (result.length > 8192) throw new Error()
    return {url: result, error: ""}
  } catch (ignored) {
    return {url: "", error: error}
  }
}
