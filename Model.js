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
    && (["bodyBattery", "sleep", "trainingReadiness", "stress"].indexOf(key) < 0 || value <= 100))
}

function validBounds(point) {
  return (point.from === undefined && point.to === undefined)
    || (typeof point.from === "number" && typeof point.to === "number"
      && isFinite(point.from) && isFinite(point.to) && point.from < point.to
      && isFinite(new Date(point.from).getTime()) && isFinite(new Date(point.to).getTime()))
}

function validMetric(key, metric, unit) {
  return !!metric && typeof metric === "object" && !Array.isArray(metric)
    && metric.unit === unit && validValue(key, metric.value)
    && ["fresh", "stale", "missing"].indexOf(metric.state) >= 0
    && (metric.time === null || validTime(metric.time))
    && (metric.date === null || validDate(metric.date))
    && validBounds(metric)
    && (metric.value === null ? metric.state === "missing" && metric.expiresAt === null
        : metric.state !== "missing" && validTime(metric.time) && validDate(metric.date)
          && validTime(metric.expiresAt) && Date.parse(metric.expiresAt) > Date.parse(metric.time))
}

function validActivityId(value) {
  return typeof value === "string" && /^[0-9]{1,32}$/.test(value)
}

function activityUrl(id) {
  return validActivityId(id) ? "https://connect.garmin.com/modern/activity/" + id : ""
}

function validActivities(bundle) {
  if (bundle === undefined || bundle === null) return true
  if (typeof bundle !== "object" || Array.isArray(bundle)
      || !validDate(bundle.startDate) || !validDate(bundle.endDate)
      || Date.parse(bundle.endDate) - Date.parse(bundle.startDate) !== 6 * 86400000
      || bundle.from === undefined || bundle.to === undefined || !validBounds(bundle)
      || !Array.isArray(bundle.items) || bundle.items.length > 500) return false
  var ids = Object.create(null)
  var fields = ["durationSeconds", "distanceMeters", "calories"]
  for (var i = 0; i < bundle.items.length; i++) {
    var item = bundle.items[i]
    if (!item || typeof item !== "object" || Array.isArray(item)
        || !validActivityId(item.id) || ids[item.id] || !validTime(item.time)
        || (item.connectId !== undefined && (!validActivityId(item.connectId) || item.connectId !== item.id))
        || Date.parse(item.time) < bundle.from || Date.parse(item.time) >= bundle.to
        || !validDate(item.date) || item.date < bundle.startDate || item.date > bundle.endDate
        || typeof item.type !== "string" || !item.type.trim() || item.type.trim() === "No Activity") return false
    var type = item.type.replace(/[\ud800-\udbff][\udc00-\udfff]/g, "x")
    if (type.length > 80
        || /[\x00-\x1f\x7f-\x9f\u00a0\u00ad\u061c\u1680\u180e\u2000-\u200f\u2028-\u202f\u205f-\u206f\u3000\ud800-\uf8ff\ufeff\ufff9-\ufffb\ufffe\uffff]/.test(type)
        || /\udb40[\udc00-\udc7f]|[\udb80-\udbff][\udc00-\udfff]/.test(item.type)) return false
    for (var f = 0; f < fields.length; f++)
      if (!validValue(fields[f], item[fields[f]])) return false
    ids[item.id] = true
  }
  return true
}

function valid(data) {
  if (!data || data.schemaVersion !== 1 || ["ok", "partial", "error", "cached", "demo"].indexOf(data.status) < 0
      || !data.metrics || !data.charts || !validTime(data.fetchedAt)
      || typeof data.timezone !== "string" || !data.timezone
      || (data.chartsFetchedAt !== null && !validTime(data.chartsFetchedAt))) return false
  if (data.device !== undefined && data.device !== null
      && (!deviceName(data.device.name) || ["Device", "demo"].indexOf(data.device.source) < 0)) return false
  if (data.sourceDate !== undefined && !validDate(data.sourceDate)) return false
  if (data.sourceDayStart !== undefined && !validTime(data.sourceDayStart)) return false
  if (data.sourceDayEnd !== undefined && !validTime(data.sourceDayEnd)) return false
  var names = ["bodyBattery", "steps", "sleep", "hrv"]
  var units = ["score", "steps", "score", "ms"]
  for (var i = 0; i < names.length; i++)
    if (!validMetric(names[i], data.metrics[names[i]], units[i])) return false
  var wellness = ["sleepDuration", "restingHeartRate", "trainingReadiness", "stress"]
  var wellnessUnits = ["seconds", "bpm", "score", "score"]
  if (data.wellness !== undefined) {
    if (!data.wellness || typeof data.wellness !== "object" || Array.isArray(data.wellness)) return false
    for (var w = 0; w < wellness.length; w++) {
      var metric = data.wellness[wellness[w]]
      if (!validMetric(wellness[w], metric, wellnessUnits[w])
          || (metric.value !== null && !validTime(data.wellnessFetchedAt))) return false
    }
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
  var errors = ["query_error", "invalid_response", "truncated_response", "ambiguous_source",
    "source_unavailable", "timeout", "network_error", "auth_error", "http_error",
    "redirect_refused", "response_too_large"]
  var bundles = ["activity", "activities", "history", "wellness", "supplementalHistory", "stress"]
  for (var e = 0; e < bundles.length; e++) {
    var kind = bundles[e]
    var fetched = data[kind + "FetchedAt"]
    var error = data[kind + "Error"]
    if (fetched !== undefined && fetched !== null && !validTime(fetched)) return false
    if (error !== undefined && error !== null && errors.indexOf(error) < 0) return false
  }
  if (!validActivities(data.activities)
      || (data.activities !== undefined && data.activities !== null && !validTime(data.activitiesFetchedAt))) return false
  var histories = ["history", "supplementalHistory"]
  for (var b = 0; b < histories.length; b++) {
    var bundle = data[histories[b]]
    if (bundle === undefined) continue
    if (!bundle || typeof bundle !== "object" || Array.isArray(bundle)) return false
    var historyKeys = b === 0 ? names : wellness
    for (var h = 0; h < historyKeys.length; h++) {
      var history = bundle[historyKeys[h]]
      if (!Array.isArray(history) || history.length > 7
          || (history.length && !validTime(data[histories[b] + "FetchedAt"]))) return false
      for (var d = 0; d < history.length; d++)
        if (!history[d] || !validDate(history[d].date) || !validValue(historyKeys[h], history[d].value)
            || !validBounds(history[d])) return false
    }
  }
  if (data.stressSeries !== undefined) {
    var stress = data.stressSeries
    if (!Array.isArray(stress) || stress.length > 2000
        || (stress.length && !validTime(data.stressFetchedAt))) return false
    for (var s = 0; s < stress.length; s++)
      if (!stress[s] || !validTime(stress[s].time) || !validValue("stress", stress[s].value)) return false
  }
  var activity = data.latestActivity
  if (activity !== undefined && activity !== null) {
    if (activity.id !== undefined && !validActivityId(activity.id)) return false
    if (activity.connectId !== undefined && (!validActivityId(activity.connectId) || activity.connectId !== activity.id)) return false
    if (typeof activity !== "object" || Array.isArray(activity) || !validTime(activity.time)
        || !validTime(data.activityFetchedAt) || typeof activity.type !== "string"
        || !activity.type.trim() || activity.type.trim() === "No Activity"
        || activity.type.replace(/[\ud800-\udbff][\udc00-\udfff]/g, "x").length > 80
        || /[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f]/.test(activity.type)) return false
    var selectors = ["selector", "gpsSelector"]
    for (var g = 0; g < selectors.length; g++) {
      var selector = activity[selectors[g]]
      if (selector === undefined) continue
      if (typeof selector !== "string" || !selector.trim()
          || selector.replace(/[\ud800-\udbff][\udc00-\udfff]/g, "x").length > 256
          || /[\x00-\x1f\x7f-\x9f\u00a0\u00ad\u1680\u2000-\u200f\u2028-\u202f\u205f-\u206f\u3000\ud800-\uf8ff\ufeff\ufff9-\ufffb\ufffe\uffff]/.test(
            selector.replace(/[\ud800-\udbff][\udc00-\udfff]/g, "x"))) return false
    }
    var fields = ["durationSeconds", "distanceMeters", "calories", "bmrCalories", "averageHR", "maxHR",
      "movingDuration", "averageSpeed", "maxSpeed", "elevationGain", "elevationLoss",
      "aerobicTrainingEffect", "anaerobicTrainingEffect", "activityTrainingLoad"]
    for (var a = 0; a < fields.length; a++)
      if (activity[fields[a]] !== undefined && !validValue(fields[a], activity[fields[a]])) return false
  }
  return true
}

function format(metric) {
  if (!metric || metric.value === null || typeof metric.value !== "number" || !isFinite(metric.value)) return "--"
  return metric.unit === "steps" && metric.value >= 1000 ? (metric.value / 1000).toFixed(1) + "k" : String(Math.round(metric.value))
}

function deviceName(value) {
  if (typeof value !== "string" || /[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u206f]/.test(value)) return ""
  var name = value.trim()
  var length = name.replace(/[\ud800-\udbff][\udc00-\udfff]/g, "x").length
  return length > 80 || /^(unknown|garmin)$/i.test(name) ? "" : name
}

function watchDevice(payload, override, demoMode) {
  // Demo must never borrow the real watch's configured identity.
  var demo = demoMode || (payload && payload.status === "demo")
  var configured = demo ? "" : deviceName(override)
  var reported = payload && payload.device ? deviceName(payload.device.name) : ""
  return {name: configured || reported || "Garmin watch",
    source: demo ? "Synthetic device" : configured ? "Model set in settings" : reported ? "Reported by collector" : "Model unavailable",
    known: !!(configured || reported)}
}

function watchStyle(name) {
  var model = name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  if (/\b(venu\s+sq(?:\b|\d)|forerunner\s+(?:30|35)(?:\b|\D))/.test(model)) return "square"
  if (/\b(vivosmart|vivofit)\b/.test(model)) return "slim"
  if (/\b(fenix|epix|enduro|instinct|tactix|quatix|descent|marq)\b/.test(model)) return "rugged"
  if (/\bvivomove\b/.test(model)) return "hybrid"
  if (/\b(forerunner|venu|vivoactive|lily)\b/.test(model)) return "round"
  return "generic"
}

function activityKind(type) {
  var key = typeof type === "string" ? type.trim().toLowerCase().replace(/[\s-]+/g, "_") : ""
  if (/^(mountain_biking|mountainbiking|mountain_cycling|e_bike_mountain|bmx)$/.test(key)) return "mountainBiking"
  if (/^(wind_kite_surfing|windsurfing|wind_surfing|kitesurfing|kite_surfing)$/.test(key)) return "windsurfing"
  if (/^(running|trail_running|treadmill_running|indoor_running|track_running|street_running|ultra_run|virtual_run)$/.test(key)) return "running"
  if (/^(cycling|biking|road_biking|road_cycling|indoor_cycling|gravel_cycling|virtual_ride|e_bike_fitness|cyclocross|recumbent_cycling|hand_cycling|track_cycling)$/.test(key)) return "cycling"
  if (/^(rowing|indoor_rowing)$/.test(key)) return "rowing"
  if (/^(strength|strength_training|weight_training|weightlifting)$/.test(key)) return "strength"
  if (/^(walking|casual_walking|speed_walking|indoor_walking)$/.test(key)) return "walking"
  if (/^(hiking|mountaineering)$/.test(key)) return "hiking"
  if (/^(swimming|lap_swimming|open_water_swimming|pool_swimming)$/.test(key)) return "swimming"
  if (/^(skiing|alpine_skiing|backcountry_skiing|resort_skiing|cross_country_skiing|skate_skiing|snowboarding|resort_snowboarding|backcountry_snowboarding)$/.test(key)) return "skiing"
  if (/^(yoga|pilates)$/.test(key)) return "yoga"
  if (/^(paddling|stand_up_paddleboarding|stand_up_paddle_boarding|kayaking|kayaking_v2|canoeing)$/.test(key)) return "paddling"
  if (/^(cardio|fitness_equipment|elliptical|stair_climbing|floor_climbing|hiit|indoor_cardio)$/.test(key)) return "cardio"
  return "generic"
}

function activityIconKind(type) {
  // Icon distinctions must not change the sport families used for metrics.
  var key = typeof type === "string" ? type.trim().toLowerCase().replace(/[\s-]+/g, "_") : ""
  if (/^(trail_running|ultra_run)$/.test(key)) return "trailRunning"
  if (/^(treadmill|treadmill_running|indoor_running)$/.test(key)) return "treadmill"
  if (/^(indoor_cycling|virtual_ride)$/.test(key)) return "indoorCycling"
  if (key === "open_water_swimming") return "openWaterSwimming"
  if (key === "indoor_rowing") return "indoorRowing"
  if (key === "pilates") return "pilates"
  if (key === "elliptical") return "elliptical"
  if (/^(stair_climbing|floor_climbing|stair_stepper)$/.test(key)) return "stairClimbing"
  if (/^(hiit|high_intensity_interval_training)$/.test(key)) return "hiit"
  if (/^(snowboarding|resort_snowboarding|backcountry_snowboarding)$/.test(key)) return "snowboarding"
  if (/^(cross_country_skiing|skate_skiing|xc_classic_skiing|xc_skate_skiing)$/.test(key)) return "crossCountrySkiing"
  if (/^(kayaking|kayaking_v2)$/.test(key)) return "kayaking"
  if (/^(paddleboarding|stand_up_paddleboarding|stand_up_paddle_boarding)$/.test(key)) return "paddleboarding"
  if (key === "tennis") return "tennis"
  if (key === "golf") return "golf"
  if (key === "soccer") return "soccer"
  if (key === "basketball") return "basketball"
  if (key === "surfing") return "surfing"
  return activityKind(type)
}

function activityName(type) {
  if (typeof type !== "string" || !type.trim()) return "Activity"
  return type.trim().replace(/[_-]+/g, " ").replace(/\s+/g, " ").toLowerCase()
    .replace(/\b\w/g, function(letter) { return letter.toUpperCase() })
}

function activitiesOverview(bundle) {
  if (bundle === undefined || bundle === null) return null
  var result = {count: bundle.items.length, duration: {value: 0, knownCount: 0},
    calories: {value: 0, knownCount: 0}, types: []}
  var groups = Object.create(null)
  var totals = [result.duration, result.calories]
  for (var i = 0; i < bundle.items.length; i++) {
    var item = bundle.items[i]
    var group = groups[item.type]
    if (!group) {
      group = {type: item.type, count: 0, duration: {value: 0, knownCount: 0},
        distance: {value: 0, knownCount: 0}}
      groups[item.type] = group
      result.types.push(group)
      totals.push(group.duration, group.distance)
    }
    group.count++
    var targets = [result.duration, result.calories, group.duration, group.distance]
    var values = [item.durationSeconds, item.calories, item.durationSeconds, item.distanceMeters]
    for (var v = 0; v < values.length; v++) {
      if (typeof values[v] !== "number" || !isFinite(values[v]) || values[v] < 0) continue
      targets[v].value += values[v]
      targets[v].knownCount++
    }
  }
  // Keep overflow unknown, without losing how many measurements contributed.
  for (var t = 0; t < totals.length; t++)
    if ((result.count && !totals[t].knownCount) || !isFinite(totals[t].value)) totals[t].value = null
  result.types.sort(function(a, b) {
    return b.count - a.count || (a.type < b.type ? -1 : a.type > b.type ? 1 : 0)
  })
  return result
}

function numeric(value) {
  if (typeof value !== "number" || !isFinite(value) || value < 0) return "--"
  var text = String(Math.round(value))
  // Large finite numbers must still be plain integers, not scientific notation.
  var parts = text.split("e+")
  if (parts.length === 2) {
    var digits = parts[0].replace(".", "")
    return digits + "0".repeat(Number(parts[1]) + 1 - digits.length)
  }
  return text
}

function duration(seconds) {
  if (numeric(seconds) === "--") return "--"
  var minutes = Math.round(seconds / 60)
  return minutes < 60 ? numeric(minutes) + " min"
    : numeric(Math.floor(minutes / 60)) + " h" + (minutes % 60 ? " " + numeric(minutes % 60) + " min" : "")
}

function sleepDuration(seconds) {
  if (numeric(seconds) === "--") return "--"
  var minutes = Math.round(seconds / 60)
  return numeric(Math.floor(minutes / 60)) + "h " + numeric(minutes % 60) + "m"
}

function activityPerformance(activity) {
  if (!activity) return ""
  var kind = activityKind(activity.type)
  var speed = activity.averageSpeed
  if (["running", "walking", "hiking", "swimming", "rowing"].indexOf(kind) >= 0) {
    if (typeof speed !== "number" || !isFinite(speed) || speed <= 0 || speed > 100) return ""
    var distance = kind === "swimming" ? 100 : kind === "rowing" ? 500 : 1000
    var seconds = Math.round(distance / speed)
    // Bound the display, not the stored measurement: corrupt speeds must not produce giant or zero paces.
    if (seconds < 1 || seconds > 5999) return ""
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0")
      + (distance === 1000 ? " /km" : " /" + distance + "m")
  }
  if (["cycling", "mountainBiking", "windsurfing", "skiing"].indexOf(kind) < 0) return ""
  var parts = []
  var fields = ["averageSpeed", "maxSpeed"]
  for (var i = 0; i < fields.length; i++) {
    speed = activity[fields[i]]
    if (typeof speed !== "number" || !isFinite(speed) || speed <= 0 || speed > 100) continue
    var kmh = (speed * 3.6).toFixed(1)
    if (Number(kmh) > 0) parts.push((i === 0 ? "Avg " : "Max ") + kmh + " km/h")
  }
  return parts.join(" - ")
}

function activityDetails(activity) {
  var rows = []
  if (!activity) return rows
  var fields = ["movingDuration", "maxHR", "elevationGain", "elevationLoss",
    "aerobicTrainingEffect", "anaerobicTrainingEffect", "activityTrainingLoad"]
  var labels = ["Moving time", "Max HR", "Elevation gain", "Elevation loss",
    "Aerobic effect", "Anaerobic effect", "Training load"]
  for (var i = 0; i < fields.length; i++) {
    var value = activity[fields[i]]
    if (numeric(value) === "--") continue
    var text = i === 0 ? duration(value) : i === 4 || i === 5 ? value.toFixed(1) : numeric(value)
    if (i === 1) text += " bpm"
    if (i === 2 || i === 3) text += " m"
    rows.push({label: labels[i], value: text})
  }
  return rows
}

function activityDistance(activity) {
  if (!activity || ["running", "cycling", "mountainBiking", "windsurfing", "rowing", "walking",
      "hiking", "swimming", "skiing", "paddling"].indexOf(activityKind(activity.type)) < 0
      || numeric(activity.distanceMeters) === "--" || activity.distanceMeters <= 0) return ""
  return activity.distanceMeters >= 1000 ? (activity.distanceMeters / 1000).toFixed(1) + " km"
    : numeric(activity.distanceMeters) + " m"
}

function activitySummary(activity) {
  if (!activity) return "--"
  var distance = activityDistance(activity)
  return activityName(activity.type) + " - " + duration(activity.durationSeconds) + (distance ? " - " + distance : "")
}

function average(points) {
  var value = null
  var count = 0
  if (Array.isArray(points)) {
    for (var i = 0; i < points.length; i++) {
      if (!points[i] || numeric(points[i].value) === "--") continue
      count++
      value = count === 1 ? points[i].value : value + (points[i].value - value) / count
    }
  }
  return {value: value, count: count}
}

function tooltip(payload, now) {
  var metrics = payload && payload.metrics ? payload.metrics : {}
  var fetchedAt = payload ? payload.fetchedAt : null
  var rows = []
  if (payload && payload.status === "demo") rows.push("Demo data")
  var keys = ["steps", "bodyBattery", "sleep"]
  var labels = ["Steps today", "Body battery", "Sleep score"]
  for (var i = 0; i < keys.length; i++) {
    var metric = metrics[keys[i]]
    var value = numeric(metric ? metric.value : null)
    var expired = stale(keys[i], metric, now, fetchedAt)
    if (keys[i] === "steps" && expired) value = "--"
    rows.push(labels[i] + ": " + value + (keys[i] !== "steps" && value !== "--" && expired ? " (stale)" : ""))
  }
  var activity = payload ? payload.latestActivity : null
  var cached = activity && (payload.activityError || payload.status === "cached"
    || !validTime(payload.activityFetchedAt) || !isFinite(now)
    || now - Date.parse(payload.activityFetchedAt) > 3600000)
  rows.push("Latest activity: " + activitySummary(activity) + (cached ? " (cached)" : ""))
  return rows.join("\n")
}

function stale(key, metric, now, fetchedAt) {
  if (!metric || metric.value === null || metric.state !== "fresh" || !isFinite(now)
      || !validTime(fetchedAt) || !validTime(metric.time) || !validTime(metric.expiresAt)
      || now < Date.parse(metric.time)) return true
  if (now - Date.parse(fetchedAt) > 3600000) return true
  // Daily metrics expire at source-local midnight; age-based metrics include their deadline.
  return ["steps", "restingHeartRate", "trainingReadiness"].indexOf(key) >= 0
    ? now >= Date.parse(metric.expiresAt) : now > Date.parse(metric.expiresAt)
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
