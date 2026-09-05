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
    readonly property bool stale: Model.stale("steps", metric, now, fetchedAt)
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

  function test_clock_binding_and_dst_rollover() {
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
}
