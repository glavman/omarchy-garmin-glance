import QtQuick
import QtTest
import "../Model.js" as Model

TestCase {
  name: "Model"

  QtObject {
    id: clocked
    property var metric: null
    property real now: 0
    property string fetchedAt: ""
    property string key: "steps"
    readonly property bool stale: Model.stale(key, metric, now, fetchedAt)
  }

  function fixture() {
    var data = {
      schemaVersion: 1, status: "ok", error: null,
      fetchedAt: "2026-09-05T10:00:00Z", timezone: "Europe/Dublin",
      chartsFetchedAt: "2026-09-05T10:00:00Z", metrics: {},
      charts: {bodyBattery: [{time: "2026-09-05T10:00:00Z", value: 0}],
        steps: [{date: "2026-09-05", value: 123456}], sleep: [{date: "2026-09-05", value: null}]}
    }
    var units = {bodyBattery: "score", steps: "steps", sleep: "score", hrv: "ms"}
    var deadlines = {bodyBattery: "2026-09-05T12:00:00Z", steps: "2026-09-05T23:00:00Z",
      sleep: "2026-09-06T22:00:00Z", hrv: "2026-09-06T22:00:00Z"}
    for (var key in units)
      data.metrics[key] = {value: 0, time: data.fetchedAt, date: "2026-09-05", state: "fresh",
        unit: units[key], expiresAt: deadlines[key]}
    return data
  }

  function test_valid() {
    var data = fixture()
    verify(Model.valid(data))
    data.metrics.bodyBattery.value = 100
    data.metrics.sleep.value = 100
    data.metrics.steps.value = 1e13
    data.metrics.hrv.value = 1e13
    data.metrics.hrv.time = "2026-09-05T11:00:00.123456+01:00"
    verify(Model.valid(data))
    data.metrics.steps = {value: null, time: null, date: null, state: "missing", unit: "steps", expiresAt: null}
    verify(Model.valid(data))
    data.metrics.steps.time = data.fetchedAt
    data.metrics.steps.date = "2026-09-05"
    verify(Model.valid(data), "Missing values may retain a valid sample timestamp")
    data.charts = {bodyBattery: [], steps: [], sleep: []}
    data.chartsFetchedAt = null
    verify(Model.valid(data))
  }

  function test_invalid_data() {
    var rows = []
    var keys = ["bodyBattery", "steps", "sleep", "hrv"]
    for (var k = 0; k < keys.length; k++) {
      var key = keys[k]
      var fields = {
        value: [-1, NaN, Infinity, -Infinity, "0", true, {}, undefined],
        unit: [null, "", "wrong", 1, undefined],
        time: [null, 0, {}, "2026-09-05", "2026-09-05T10:00:00", "2026-02-30T10:00:00Z", "2026-09-05T24:00:00Z", undefined],
        date: [null, 20260905, {}, "2026-9-5", "2026-02-30", undefined],
        expiresAt: [null, 0, "invalid", "2026-09-05T10:00:00Z", "2026-09-04T10:00:00Z", undefined],
        state: ["missing", "invalid", null, undefined]
      }
      if (key === "bodyBattery" || key === "sleep") fields.value.push(101)
      for (var field in fields)
        for (var i = 0; i < fields[field].length; i++)
          rows.push({tag: key + "-" + field + "-" + i, section: "metrics", key: key, field: field, value: fields[field][i]})
    }
    for (var c = 0; c < 3; c++) {
      var chart = keys[c]
      var axis = c === 0 ? "time" : "date"
      var coordinates = [null, 123, {}, [], "invalid", undefined,
        c === 0 ? "2026-09-05" : "2026-09-05T10:00:00Z",
        c === 0 ? "2026-02-30T10:00:00Z" : "2026-02-30"]
      for (var a = 0; a < coordinates.length; a++)
        rows.push({tag: chart + "-axis-" + a, section: "charts", key: chart, field: axis, value: coordinates[a]})
      var values = [-1, NaN, Infinity, "0", false, undefined]
      if (chart !== "steps") values.push(101)
      for (var v = 0; v < values.length; v++)
        rows.push({tag: chart + "-chart-value-" + v, section: "charts", key: chart, field: "value", value: values[v]})
    }
    for (var f = 0; f < 2; f++) {
      var name = f === 0 ? "fetchedAt" : "chartsFetchedAt"
      var times = [123, {}, "yesterday", "2026-09-05", "2026-09-05T10:00:00", "2026-09-05T10:60:00Z", undefined]
      if (f === 0) times.push(null)
      for (var t = 0; t < times.length; t++)
        rows.push({tag: name + "-" + t, section: "root", field: name, value: times[t]})
    }
    return rows
  }

  function test_invalid(row) {
    var data = fixture()
    var target = row.section === "root" ? data : row.section === "metrics" ? data.metrics[row.key] : data.charts[row.key][0]
    target[row.field] = row.value
    verify(!Model.valid(data))
  }

  function test_missing_and_chart_contract() {
    var data = fixture()
    data.metrics.steps.value = null
    verify(!Model.valid(data))
    data.metrics.steps.state = "missing"
    verify(!Model.valid(data), "Missing values must not have an expiry")
    data.metrics.steps.expiresAt = null
    verify(Model.valid(data))
    data.chartsFetchedAt = null
    verify(!Model.valid(data), "Nonempty charts need a fetch timestamp")
    data = fixture()
    data.charts.steps = new Array(8).fill({date: "2026-09-05", value: 0})
    verify(!Model.valid(data))
    data = fixture()
    data.charts.bodyBattery = new Array(2001).fill({time: data.fetchedAt, value: 0})
    verify(!Model.valid(data))
    verify(!Model.valid(null))
    verify(!Model.valid({}))
  }

  function test_stale_data() {
    return [
      {tag: "battery-deadline", key: "bodyBattery", now: "2026-09-05T12:00:00Z", expected: false},
      {tag: "battery-expired", key: "bodyBattery", now: "2026-09-05T12:00:00.001Z", expected: true},
      {tag: "steps-before-midnight", key: "steps", now: "2026-09-05T22:59:59.999Z", expected: false},
      {tag: "steps-source-midnight", key: "steps", now: "2026-09-05T23:00:00Z", expected: true},
      {tag: "sleep-deadline", key: "sleep", now: "2026-09-06T22:00:00Z", expected: false},
      {tag: "sleep-expired", key: "sleep", now: "2026-09-06T22:00:00.001Z", expected: true},
      {tag: "hrv-expired", key: "hrv", now: "2026-09-06T22:00:00.001Z", expected: true}
    ]
  }

  function test_stale(row) {
    var metric = fixture().metrics[row.key]
    compare(Model.stale(row.key, metric, Date.parse(row.now), row.now), row.expected)
  }

  function test_stale_cache_and_missing() {
    var data = fixture()
    var now = Date.parse(data.fetchedAt)
    compare(Model.stale("steps", data.metrics.steps, now + 3600000, data.fetchedAt), false)
    compare(Model.stale("steps", data.metrics.steps, now + 3600001, data.fetchedAt), true)
    compare(Model.stale("steps", data.metrics.steps, now - 1, data.fetchedAt), true)
    compare(Model.stale("steps", null, now, data.fetchedAt), true)
    data.metrics.steps.expiresAt = null
    compare(Model.stale("steps", data.metrics.steps, now, data.fetchedAt), true)
    data = fixture()
    data.metrics.steps.state = "stale"
    compare(Model.stale("steps", data.metrics.steps, now, data.fetchedAt), true)
  }

  function test_clock_binding_and_dst_rollover_data() {
    return [{tag: "steps", key: "steps"}, {tag: "resting-heart-rate", key: "restingHeartRate"},
      {tag: "readiness", key: "trainingReadiness"}]
  }

  function test_clock_binding_and_dst_rollover(row) {
    clocked.key = row.key
    var cases = [
      {time: "2026-03-29T00:00:00Z", date: "2026-03-29", expiresAt: "2026-03-29T23:00:00Z"},
      {time: "2026-10-24T23:00:00Z", date: "2026-10-25", expiresAt: "2026-10-26T00:00:00Z"}
    ]
    for (var i = 0; i < cases.length; i++) {
      var sample = cases[i]
      clocked.metric = {value: 0, unit: "steps", state: "fresh", time: sample.time,
        date: sample.date, expiresAt: sample.expiresAt}
      clocked.now = Date.parse(sample.expiresAt) - 1
      clocked.fetchedAt = new Date(clocked.now).toISOString()
      compare(clocked.stale, false)
      clocked.now += 1
      compare(clocked.stale, true)
      compare(clocked.metric.state, "fresh", "Only the clock changed, not the payload")
    }
  }

  function test_format() {
    compare(Model.format(null), "--")
    compare(Model.format({value: null}), "--")
    compare(Model.format({value: NaN}), "--")
    compare(Model.format({value: Infinity}), "--")
    compare(Model.format({value: "0"}), "--")
    compare(Model.format({value: 0, unit: "score"}), "0")
    compare(Model.format({value: 0, unit: "steps"}), "0")
    compare(Model.format({value: 999, unit: "steps"}), "999")
    compare(Model.format({value: 1000, unit: "steps"}), "1.0k")
    compare(Model.format({value: 123456, unit: "steps"}), "123.5k")
    compare(Model.format({value: 48.6, unit: "ms"}), "49")
  }

  function test_error_sanitization() {
    compare(Model.errorMessage("private raw server error"), "The database request failed.")
    compare(Model.errorMessage(null), "")
  }

  function test_watch_identity() {
    var data = fixture()
    compare(Model.watchDevice(data, "").known, false)
    data.device = {name: "Forerunner 965", source: "Device"}
    verify(Model.valid(data))
    compare(Model.watchDevice(data, "").name, "Forerunner 965")
    compare(Model.watchDevice(data, "Venu Sq 2").source, "Model set in settings")
    data.status = "demo"
    compare(Model.watchDevice(data, "private real watch").name, "Forerunner 965")
    compare(Model.watchDevice(data, "").source, "Synthetic device")
    compare(Model.watchDevice(null, "private real watch", true).name, "Garmin watch")
    compare(Model.watchDevice({status: "error"}, "private real watch", true).source, "Synthetic device")
    data.device.name = "x".repeat(79) + "\ud83d\udc1f"
    verify(Model.valid(data), "Length is measured in Unicode code points, like the backend")
    var invalid = ["", "Unknown", "garmin", "x".repeat(81), "watch\n", "watch\u007f", "watch\u202e"]
    for (var i = 0; i < invalid.length; i++) {
      data.device.name = invalid[i]
      verify(!Model.valid(data))
      compare(Model.deviceName(invalid[i]), "")
    }
    data.device = {name: "Forerunner 965", source: "untrusted"}
    verify(!Model.valid(data))
    data.device = null
    verify(Model.valid(data))
  }

  function test_watch_styles_data() {
    return [
      {tag: "sport", name: "Garmin Forerunner 965", style: "round"},
      {tag: "old-square", name: "Forerunner 35", style: "square"},
      {tag: "not-35", name: "Forerunner 350", style: "round"},
      {tag: "accent", name: "f\u00e9nix 7X Pro", style: "rugged"},
      {tag: "outdoor", name: "Instinct 2", style: "rugged"},
      {tag: "square", name: "Venu Sq 2", style: "square"},
      {tag: "band", name: "vivosmart 5", style: "slim"},
      {tag: "hybrid", name: "vivomove Trend", style: "hybrid"},
      {tag: "lily", name: "Lily 2", style: "round"},
      {tag: "unknown", name: "My watch", style: "generic"}
    ]
  }

  function test_watch_styles(row) {
    compare(Model.watchStyle(row.name), row.style)
  }

  function extrasFixture() {
    var data = fixture()
    data.history = {bodyBattery: [], steps: [], sleep: [], hrv: []}
    data.historyFetchedAt = data.fetchedAt
    for (var key in data.history)
      for (var day = 29; day <= 31; day++)
        data.history[key].push({date: "2026-08-" + day, value: day === 30 ? null : 0})
    data.latestActivity = {time: "2026-09-04T09:00:00Z", type: "trail_running",
      durationSeconds: 4320, distanceMeters: 12345, calories: 450, bmrCalories: 50}
    data.activityFetchedAt = data.fetchedAt
    data.activityError = null
    data.historyError = null
    return data
  }

  function test_optional_contract() {
    verify(Model.valid(fixture()), "Old persisted payloads remain accepted")
    var data = extrasFixture()
    verify(Model.valid(data))
    data.latestActivity = {time: data.fetchedAt, type: "Running"}
    verify(Model.valid(data), "Activity numbers may be omitted")
    var fields = ["durationSeconds", "distanceMeters", "calories", "bmrCalories", "averageHR", "maxHR",
      "movingDuration", "averageSpeed", "maxSpeed", "elevationGain", "elevationLoss",
      "aerobicTrainingEffect", "anaerobicTrainingEffect", "activityTrainingLoad"]
    for (var i = 0; i < fields.length; i++) data.latestActivity[fields[i]] = null
    verify(Model.valid(data), "Activity numbers may be null")
    for (var j = 0; j < fields.length; j++) data.latestActivity[fields[j]] = 0
    verify(Model.valid(data), "Zero is a valid measurement")
    data.latestActivity = null
    data.activityFetchedAt = null
    data.history = {bodyBattery: [], steps: [], sleep: [], hrv: []}
    data.historyFetchedAt = null
    verify(Model.valid(data))
    var codes = ["query_error", "invalid_response", "truncated_response", "ambiguous_source",
      "source_unavailable", "timeout", "network_error", "auth_error", "http_error",
      "redirect_refused", "response_too_large"]
    for (var c = 0; c < codes.length; c++) {
      data.activityError = codes[c]
      data.historyError = codes[c]
      verify(Model.valid(data), codes[c])
    }
    data = extrasFixture()
    for (var key in data.history)
      data.history[key] = new Array(7).fill({date: "2026-09-04", value: key === "steps" || key === "hrv" ? 10000 : 100})
    verify(Model.valid(data), "Up to seven daily values, with metric-specific bounds")
  }

  function test_invalid_extras_data() {
    var rows = []
    var root = {
      history: [null, [], "history", {}],
      latestActivity: [false, [], "running", {}],
      historyFetchedAt: [null, undefined, 123, "2026-09-05", "invalid"],
      activityFetchedAt: [null, undefined, 123, "2026-09-05", "invalid"],
      activityError: [false, 1, {}, "", "private server error", "cache_miss"],
      historyError: [false, 1, {}, "", "private server error", "cache_miss"]
    }
    for (var field in root)
      for (var r = 0; r < root[field].length; r++)
        rows.push({tag: field + r, section: "root", field: field, value: root[field][r]})
    var activity = {
      type: [null, undefined, 1, "", " ", "No Activity", "x".repeat(81), "run\n", "run\u202e"],
      time: [null, undefined, 1, "invalid", "2026-02-30T10:00:00Z"]
    }
    var numbers = ["durationSeconds", "distanceMeters", "calories", "bmrCalories", "averageHR", "maxHR",
      "movingDuration", "averageSpeed", "maxSpeed", "elevationGain", "elevationLoss",
      "aerobicTrainingEffect", "anaerobicTrainingEffect", "activityTrainingLoad"]
    for (var n = 0; n < numbers.length; n++) activity[numbers[n]] = [-1, NaN, Infinity, -Infinity, true, "0", {}]
    for (var a in activity)
      for (var v = 0; v < activity[a].length; v++)
        rows.push({tag: "activity-" + a + v, section: "activity", field: a, value: activity[a][v]})
    var keys = ["bodyBattery", "steps", "sleep", "hrv"]
    for (var k = 0; k < keys.length; k++) {
      var bad = [undefined, null, {}, new Array(8).fill({date: "2026-09-04", value: 0}),
        [null], [{date: "2026-02-30", value: 0}], [{date: "2026-09-04T10:00:00Z", value: 0}]]
      var values = [undefined, -1, Infinity, NaN, true, "0"]
      if (keys[k] === "bodyBattery" || keys[k] === "sleep") values.push(101)
      for (var p = 0; p < values.length; p++) bad.push([{date: "2026-09-04", value: values[p]}])
      for (var b = 0; b < bad.length; b++)
        rows.push({tag: "history-" + keys[k] + b, section: "history", field: keys[k], value: bad[b]})
    }
    return rows
  }

  function test_invalid_extras(row) {
    var data = extrasFixture()
    var target = row.section === "root" ? data : row.section === "activity" ? data.latestActivity : data.history
    target[row.field] = row.value
    verify(!Model.valid(data))
  }

  function wellnessFixture() {
    var data = extrasFixture()
    data.wellness = {}
    data.supplementalHistory = {}
    var units = {sleepDuration: "seconds", restingHeartRate: "bpm", trainingReadiness: "score", stress: "score"}
    for (var key in units) {
      data.wellness[key] = {value: 0, unit: units[key], state: "fresh", time: data.fetchedAt,
        date: "2026-09-05", expiresAt: "2026-09-05T23:00:00Z"}
      data.supplementalHistory[key] = [{date: "2026-09-04", value: 0}, {date: "2026-09-03", value: null}]
    }
    data.stressSeries = [{time: data.fetchedAt, value: 0}, {time: data.fetchedAt, value: null}]
    data.wellnessFetchedAt = data.fetchedAt
    data.supplementalHistoryFetchedAt = data.fetchedAt
    data.stressFetchedAt = data.fetchedAt
    data.wellnessError = null
    data.supplementalHistoryError = null
    data.stressError = null
    return data
  }

  function test_wellness_contract() {
    verify(Model.valid(fixture()), "Old caches without any optional bundles remain valid")
    var data = wellnessFixture()
    verify(Model.valid(data))
    for (var key in data.wellness) {
      var value = key === "stress" || key === "trainingReadiness" ? 100 : 10000
      data.wellness[key].value = value
      data.supplementalHistory[key] = new Array(7).fill({date: "2026-09-04", value: value})
    }
    data.stressSeries = new Array(2000).fill({time: data.fetchedAt, value: 100})
    verify(Model.valid(data), "Supplemental ranges and array limits match the existing metric contract")
    var codes = ["query_error", "invalid_response", "truncated_response", "ambiguous_source",
      "source_unavailable", "timeout", "network_error", "auth_error", "http_error",
      "redirect_refused", "response_too_large"]
    for (var c = 0; c < codes.length; c++) {
      data.wellnessError = data.supplementalHistoryError = data.stressError = codes[c]
      verify(Model.valid(data), codes[c])
    }
    for (var missing in data.wellness) {
      data.wellness[missing].value = null
      data.wellness[missing].state = "missing"
      data.wellness[missing].expiresAt = null
      data.supplementalHistory[missing] = []
    }
    data.stressSeries = []
    data.wellnessFetchedAt = data.supplementalHistoryFetchedAt = data.stressFetchedAt = null
    verify(Model.valid(data), "Missing wellness samples may retain valid time and date")
    for (var empty in data.wellness) {
      data.wellness[empty].time = null
      data.wellness[empty].date = null
    }
    verify(Model.valid(data), "Entirely empty optional bundles need no fetch timestamp")
    var kinds = ["wellness", "supplementalHistory", "stress"]
    for (var i = 0; i < kinds.length; i++) {
      var independent = fixture()
      var bundle = kinds[i] === "stress" ? "stressSeries" : kinds[i]
      independent[bundle] = data[bundle]
      verify(Model.valid(independent), "Bundles are independently optional")
    }
  }

  function test_invalid_wellness_data() {
    var rows = []
    var keys = ["sleepDuration", "restingHeartRate", "trainingReadiness", "stress"]
    // Run the same malformed metric cases against both core and wellness metrics.
    var core = test_invalid_data()
    var coreKeys = ["steps", "hrv", "sleep", "bodyBattery"]
    for (var r = 0; r < core.length; r++) {
      var sample = core[r]
      if (sample.section !== "metrics") continue
      var key = keys[coreKeys.indexOf(sample.key)]
      rows.push({tag: "metric-" + sample.tag, section: "wellness", key: key,
        field: sample.field, value: sample.value})
    }
    for (var k = 0; k < keys.length; k++) {
      var bad = [undefined, null, {}, new Array(8).fill({date: "2026-09-04", value: 0}),
        [null], [{date: "2026-02-30", value: 0}], [{date: "2026-09-04T10:00:00Z", value: 0}]]
      var values = [undefined, -1, Infinity, NaN, true, "0"]
      if (k >= 2) values.push(101)
      for (var v = 0; v < values.length; v++) bad.push([{date: "2026-09-04", value: values[v]}])
      for (var b = 0; b < bad.length; b++)
        rows.push({tag: "history-" + keys[k] + b, section: "supplementalHistory", field: keys[k], value: bad[b]})
      rows.push({tag: "missing-metric-" + k, section: "wellness", field: keys[k], value: undefined})
    }
    var root = {
      wellness: [null, [], "wellness", {}], supplementalHistory: [null, [], "history", {}],
      wellnessFetchedAt: [null, undefined, 123, "2026-09-05", "invalid"],
      supplementalHistoryFetchedAt: [null, undefined, 123, "2026-09-05", "invalid"],
      stressFetchedAt: [null, undefined, 123, "2026-09-05", "invalid"],
      stressSeries: [null, {}, "stress", [null], new Array(2001).fill({time: "2026-09-05T10:00:00Z", value: 0})]
    }
    var kinds = ["wellness", "supplementalHistory", "stress"]
    for (var e = 0; e < kinds.length; e++)
      root[kinds[e] + "Error"] = [false, 1, {}, "", "private error", "cache_miss"]
    for (var field in root)
      for (var i = 0; i < root[field].length; i++)
        rows.push({tag: field + i, section: "root", field: field, value: root[field][i]})
    var stress = {value: [-1, 101, NaN, Infinity, "0", true, undefined],
      time: [null, undefined, 123, "invalid", "2026-02-30T10:00:00Z"]}
    for (var pointField in stress)
      for (var p = 0; p < stress[pointField].length; p++)
        rows.push({tag: "stress-" + pointField + p, section: "stressSeries", field: pointField, value: stress[pointField][p]})
    return rows
  }

  function test_invalid_wellness(row) {
    var data = wellnessFixture()
    var target = row.section === "root" ? data : row.section === "stressSeries" ? data.stressSeries[0]
      : row.key ? data.wellness[row.key] : data[row.section]
    target[row.field] = row.value
    verify(!Model.valid(data))
  }

  function test_wellness_freshness() {
    var data = wellnessFixture()
    for (var key in data.wellness) {
      var metric = data.wellness[key]
      var deadline = Date.parse(metric.expiresAt)
      compare(Model.stale(key, metric, deadline - 1, metric.expiresAt), false)
      compare(Model.stale(key, metric, deadline, metric.expiresAt),
        key === "restingHeartRate" || key === "trainingReadiness")
      compare(Model.stale(key, metric, deadline + 1, metric.expiresAt), true)
    }
  }

  function test_sleep_duration() {
    compare(Model.sleepDuration(27720), "7h 42m")
    compare(Model.sleepDuration(0), "0h 0m")
    compare(Model.sleepDuration(29), "0h 0m")
    compare(Model.sleepDuration(30), "0h 1m")
    compare(Model.sleepDuration(3569), "0h 59m")
    compare(Model.sleepDuration(3570), "1h 0m")
    var invalid = [null, undefined, -1, NaN, Infinity, "0", true]
    for (var i = 0; i < invalid.length; i++) compare(Model.sleepDuration(invalid[i]), "--")
  }

  function test_activity_performance() {
    var paceTypes = ["running", "walking", "hiking", "swimming", "rowing"]
    var expected = ["8:20 /km", "8:20 /km", "8:20 /km", "0:50 /100m", "4:10 /500m"]
    for (var p = 0; p < paceTypes.length; p++)
      compare(Model.activityPerformance({type: paceTypes[p], averageSpeed: 2, maxSpeed: 3}), expected[p])
    compare(Model.activityPerformance({type: "running", averageSpeed: 1000 / 299.6}), "5:00 /km")
    compare(Model.activityPerformance({type: "swimming", averageSpeed: 100 / 119.6}), "2:00 /100m")
    var speedTypes = ["cycling", "mountain_biking", "windsurfing", "skiing"]
    for (var s = 0; s < speedTypes.length; s++) {
      compare(Model.activityPerformance({type: speedTypes[s], averageSpeed: 10, maxSpeed: 12.345}),
        "Avg 36.0 km/h - Max 44.4 km/h")
      compare(Model.activityPerformance({type: speedTypes[s], averageSpeed: 10}), "Avg 36.0 km/h")
      compare(Model.activityPerformance({type: speedTypes[s], maxSpeed: 10}), "Max 36.0 km/h")
    }
    compare(Model.activityPerformance(null), "")
    compare(Model.activityPerformance(undefined), "")
    compare(Model.activityPerformance({type: "strength", averageSpeed: 2}), "")
    compare(Model.activityPerformance({type: "unknown", averageSpeed: 2}), "")
    var invalid = [null, undefined, 0, -1, NaN, Infinity, "2", true, 1e308, 1e-308, 1000]
    var types = paceTypes.concat(speedTypes)
    for (var t = 0; t < types.length; t++)
      for (var i = 0; i < invalid.length; i++)
        compare(Model.activityPerformance({type: types[t], averageSpeed: invalid[i], maxSpeed: invalid[i]}), "")
  }

  function test_activity_details() {
    compare(Model.activityDetails(null), [])
    compare(Model.activityDetails(undefined), [])
    compare(Model.activityDetails({averageHR: 142, calories: 300}), [], "Compact-panel fields are not repeated")
    var activity = {movingDuration: 4320, maxHR: 168.4, elevationGain: 123.6, elevationLoss: 100,
      aerobicTrainingEffect: 3.2, anaerobicTrainingEffect: 0, activityTrainingLoad: 85}
    compare(Model.activityDetails(activity), [
      {label: "Moving time", value: "1 h 12 min"}, {label: "Max HR", value: "168 bpm"},
      {label: "Elevation gain", value: "124 m"}, {label: "Elevation loss", value: "100 m"},
      {label: "Aerobic effect", value: "3.2"}, {label: "Anaerobic effect", value: "0.0"},
      {label: "Training load", value: "85"}])
    for (var key in activity) activity[key] = 0
    compare(Model.activityDetails(activity), [
      {label: "Moving time", value: "0 min"}, {label: "Max HR", value: "0 bpm"},
      {label: "Elevation gain", value: "0 m"}, {label: "Elevation loss", value: "0 m"},
      {label: "Aerobic effect", value: "0.0"}, {label: "Anaerobic effect", value: "0.0"},
      {label: "Training load", value: "0"}])
    var invalid = [null, undefined, -1, NaN, Infinity, "0", true]
    for (var i = 0; i < invalid.length; i++) {
      for (var field in activity) activity[field] = invalid[i]
      compare(Model.activityDetails(activity), [])
    }
    compare(Model.activityDetails({anaerobicTrainingEffect: 0}), [{label: "Anaerobic effect", value: "0.0"}])
  }

  function test_activity_kinds_data() {
    var groups = {
      running: ["Running", "trail_running", "treadmill_running", "indoor_running", "track_running", "virtual_run"],
      cycling: ["Cycling", "indoor_cycling", "gravel_cycling", "road_biking", "virtual_ride", "e_bike_fitness"],
      mountainBiking: ["mountain_biking", "mountainBiking", "e_bike_mountain"],
      windsurfing: ["wind_kite_surfing", "windsurfing", "kite_surfing"],
      rowing: ["rowing", "indoor_rowing"], strength: ["strength_training", "weightlifting"],
      walking: ["walking", "casual_walking"], hiking: ["hiking", "mountaineering"],
      swimming: ["swimming", "lap_swimming", "open_water_swimming"],
      skiing: ["skiing", "alpine_skiing", "cross_country_skiing", "snowboarding"],
      yoga: ["yoga", "pilates"], paddling: ["paddling", "stand_up_paddleboarding", "kayaking", "kayaking_v2", "canoeing"],
      cardio: ["cardio", "fitness_equipment", "elliptical", "hiit"],
      generic: [null, undefined, "", "new_unknown_sport", "toString", "__proto__", 42]
    }
    var rows = []
    for (var kind in groups)
      for (var i = 0; i < groups[kind].length; i++)
        rows.push({tag: kind + i, type: groups[kind][i], kind: kind})
    return rows
  }

  function test_activity_kinds(row) {
    compare(Model.activityKind(row.type), row.kind)
    var distance = Model.activityDistance({type: row.type, distanceMeters: 1234})
    compare(distance, ["strength", "yoga", "cardio", "generic"].indexOf(row.kind) >= 0 ? "" : "1.2 km")
  }

  function test_activity_formatting() {
    compare(Model.activityKind(" Indoor Cycling "), "cycling")
    compare(Model.activityName("trail_running"), "Trail Running")
    compare(Model.activityName("wind_kite_surfing"), "Wind Kite Surfing")
    compare(Model.activityName("  NEW_unknown_SPORT  "), "New Unknown Sport")
    compare(Model.activityName(null), "Activity")
    compare(Model.duration(2700), "45 min")
    compare(Model.duration(4320), "1 h 12 min")
    compare(Model.duration(3600), "1 h")
    compare(Model.duration(0), "0 min")
    compare(Model.duration(59), "1 min")
    compare(Model.activityDistance({type: "running", distanceMeters: 999}), "999 m")
    compare(Model.activityDistance({type: "running", distanceMeters: 1000}), "1.0 km")
    compare(Model.activityDistance(null), "")
    var missing = [null, undefined, NaN, Infinity, -1, "100", true]
    for (var i = 0; i < missing.length; i++) {
      compare(Model.duration(missing[i]), "--")
      compare(Model.activityDistance({type: "running", distanceMeters: missing[i]}), "")
    }
    compare(Model.activityDistance({type: "running", distanceMeters: 0}), "")
    compare(Model.activitySummary(null), "--")
    compare(Model.activitySummary(undefined), "--")
    compare(Model.activitySummary(extrasFixture().latestActivity), "Trail Running - 1 h 12 min - 12.3 km")
    compare(Model.activitySummary({type: "strength_training", durationSeconds: 2700, distanceMeters: 100}),
      "Strength Training - 45 min")
    compare(Model.activitySummary({type: "yoga"}), "Yoga - --")
  }

  function test_numeric_and_average() {
    var invalid = [null, undefined, "0", true, {}, NaN, Infinity, -Infinity, -1]
    for (var i = 0; i < invalid.length; i++) compare(Model.numeric(invalid[i]), "--")
    compare(Model.numeric(0), "0")
    compare(Model.numeric(48.6), "49")
    compare(Model.numeric(123456), "123456")
    compare(Model.numeric(1e21), "1000000000000000000000")
    compare(Model.numeric(1.23e22), "12300000000000000000000")
    compare(Model.average(null), {value: null, count: 0})
    compare(Model.average([]), {value: null, count: 0})
    compare(Model.average([{value: null}, {}]), {value: null, count: 0})
    compare(Model.average([{value: 0}, {value: 10}, {value: null}, {}, null, {value: 20}, {value: null}]),
      {value: 10, count: 3})
    compare(Model.average([{value: 0}]), {value: 0, count: 1})
    compare(Model.average([{value: 1}, {value: 2}]), {value: 1.5, count: 2})
    compare(Model.average([{value: NaN}, {value: -1}, {value: "5"}, {value: Infinity}]), {value: null, count: 0})
    compare(Model.average([{value: 1e308}, {value: 1e308}]), {value: 1e308, count: 2})
  }

  function test_tooltip() {
    var data = extrasFixture()
    data.metrics.steps.value = 4321
    data.metrics.bodyBattery.value = 73
    data.metrics.sleep.value = 82
    data.device = {name: "Private watch", source: "Device"}
    var now = Date.parse(data.fetchedAt)
    var expected = "Steps today: 4321\nBody battery: 73\nSleep score: 82\nLatest activity: Trail Running - 1 h 12 min - 12.3 km"
    compare(Model.tooltip(data, now), expected)
    data.status = "demo"
    compare(Model.tooltip(data, now), "Demo data\n" + expected)
    data.status = "ok"
    var cached = expected + " (cached)"
    data.activityError = "query_error"
    compare(Model.tooltip(data, now), cached)
    data.activityError = null
    data.status = "cached"
    compare(Model.tooltip(data, now), cached)
    data.status = "ok"
    data.activityFetchedAt = "2026-09-05T09:00:00Z"
    compare(Model.tooltip(data, now), expected, "Exactly one hour is not expired")
    compare(Model.tooltip(data, now + 1), cached)
    data.activityFetchedAt = null
    compare(Model.tooltip(data, now), cached)
    data = fixture()
    data.metrics.steps.value = 9999
    data.metrics.steps.date = "2026-09-04"
    data.metrics.steps.time = "2026-09-04T10:00:00Z"
    data.metrics.steps.expiresAt = "2026-09-04T23:00:00Z"
    compare(Model.tooltip(data, now), "Steps today: --\nBody battery: 0\nSleep score: 0\nLatest activity: --")
    data.metrics.bodyBattery.state = "stale"
    data.metrics.sleep.state = "stale"
    compare(Model.tooltip(data, now), "Steps today: --\nBody battery: 0 (stale)\nSleep score: 0 (stale)\nLatest activity: --")
    compare(Model.tooltip(null, now), "Steps today: --\nBody battery: --\nSleep score: --\nLatest activity: --")
    data = fixture()
    compare(Model.tooltip(data, now + 3600001),
      "Steps today: --\nBody battery: 0 (stale)\nSleep score: 0 (stale)\nLatest activity: --")
  }
}
