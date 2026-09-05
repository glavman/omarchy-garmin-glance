import QtQuick
import QtTest
import "../Grafana.js" as Grafana

TestCase {
  name: "Grafana"

  function fixture() {
    var data = {timezone: "Europe/Dublin", metrics: {}, wellness: {}, history: {}, supplementalHistory: {},
      latestActivity: {time: "2026-09-04T10:00:00+01:00", durationSeconds: 4320, selector: "summary-only", gpsSelector: "synthetic"}}
    var keys = ["steps", "sleep", "sleepDuration", "hrv", "restingHeartRate", "stress", "bodyBattery"]
    for (var i = 0; i < keys.length; i++) {
      var wellness = ["sleepDuration", "restingHeartRate", "stress"].indexOf(keys[i]) >= 0
      data[wellness ? "wellness" : "metrics"][keys[i]] = {
        date: "2026-09-04", value: 0, from: 1788476400000 + i, to: 1788562800000 + i}
      data[wellness ? "supplementalHistory" : "history"][keys[i]] = [
        {date: "2026-09-04", value: 0, from: 1788476400000 + i, to: 1788562800000 + i},
        {date: "2026-09-02", value: null, from: 1788303600000 + i, to: 1788390000000 + i},
        {date: "2026-09-03", value: 10, from: 1788390000000 + i, to: 1788476400000 + i}]
    }
    return data
  }

  function params(result) {
    compare(result.error, "")
    verify(result.url.length > 0)
    var output = {}
    var query = result.url.split("#")[0].split("?")[1].split("&")
    for (var i = 0; i < query.length; i++) {
      var pair = query[i].split("=")
      var key = decodeURIComponent(pair[0])
      verify(output[key] === undefined, "No duplicate query keys: " + key)
      output[key] = decodeURIComponent(pair.slice(1).join("="))
    }
    return output
  }

  function rejected(result, refresh) {
    compare(result.url, "")
    verify(typeof result.error === "string" && result.error.length > 0)
    if (refresh) verify(result.error.indexOf("Refresh ") === 0)
    verify(result.error.indexOf("SECRET") < 0)
  }

  function test_routing_data() {
    var keys = ["steps", "sleep", "sleepDuration", "hrv", "restingHeartRate", "stress", "bodyBattery"]
    var current = [30, 12, 32, 11, 28, 29, 29]
    var history = [1, 12, 32, 11, 11, 51, 66]
    var rows = []
    for (var i = 0; i < keys.length; i++) {
      rows.push({tag: keys[i] + "-current", key: keys[i], kind: "current", date: "", panel: current[i], index: i})
      rows.push({tag: keys[i] + "-history", key: keys[i], kind: "history", date: "", panel: history[i], index: i})
      rows.push({tag: keys[i] + "-selected", key: keys[i], kind: "history", date: "2026-09-02", panel: history[i], index: i})
    }
    return rows
  }

  function test_routing(row) {
    var result = Grafana.build("http://localhost:3000", fixture(), {key: row.key, kind: row.kind, date: row.date})
    verify(result.url.indexOf("http://localhost:3000/d/feiibsx498gsgb/garmin-stats?") === 0)
    var query = params(result)
    compare(query.viewPanel, "panel-" + row.panel)
    compare(query.from, String((row.kind === "current" ? 1788476400000 : 1788303600000) + row.index))
    compare(query.to, String((row.date ? 1788390000000 : 1788562800000) + row.index - 1))
    compare(query.timezone, "Europe/Dublin")
    compare(query["var-TimeZone"], "Europe/Dublin")
    verify(query["var-ActivityGPS"] === undefined)
  }

  function test_generic_and_paths_data() {
    return [
      {tag: "root", base: "http://localhost:3000", path: "/d/feiibsx498gsgb/garmin-stats"},
      {tag: "slash", base: "http://127.0.0.1:1/", path: "/d/feiibsx498gsgb/garmin-stats"},
      {tag: "prefix", base: "https://grafana.example/proxy/grafana", path: "/proxy/grafana/d/feiibsx498gsgb/garmin-stats"},
      {tag: "prefix-slash", base: "https://grafana.example/proxy/grafana/", path: "/proxy/grafana/d/feiibsx498gsgb/garmin-stats"},
      {tag: "dashboard", base: "https://grafana.example/d/other_UID/custom-slug", path: "/d/other_UID/custom-slug"},
      {tag: "proxy-dashboard", base: "https://grafana.example/proxy/d/UID/custom/", path: "/proxy/d/UID/custom/"},
      {tag: "unicode-path", base: "https://grafana.example/caf\u00e9/d/UID/%E2%98%83", path: "/caf\u00e9/d/UID/%E2%98%83"},
      {tag: "ipv6", base: "http://[::1]:3000/", path: "/d/feiibsx498gsgb/garmin-stats"},
      {tag: "ipv6-full", base: "http://[2001:db8:0:1:2:3:4:5]:65535", path: "/d/feiibsx498gsgb/garmin-stats"},
      {tag: "ipv6-ipv4", base: "http://[::ffff:192.0.2.1]", path: "/d/feiibsx498gsgb/garmin-stats"},
      {tag: "case", base: "HTTPS://Grafana.Example.", path: "/d/feiibsx498gsgb/garmin-stats"}
    ]
  }

  function test_generic_and_paths(row) {
    var base = row.base + "?orgId=2&x=a%20b&x=%26&flag#keep%20me"
    compare(Grafana.build(base), {url: base, error: ""})
    compare(Grafana.build(base, {invalid: true}), {url: base, error: ""})
    var result = Grafana.build(base, fixture(), {key: "steps", kind: "current"})
    compare(result.error, "")
    verify(result.url.indexOf(row.path + "?orgId=2&x=a%20b&x=%26&flag&from=") >= 0)
    verify(result.url.endsWith("#keep%20me"))
  }

  function test_other_routes() {
    var paths = ["/d", "/d/UID", "/d/UID/slug/extra", "/d/UID!/slug", "/d-solo/UID/slug",
      "/dashboard/db/stats", "/proxy/explore", "/dashboards", "/login", "/api/search",
      "/proxy//grafana", "/proxy/../grafana", "/%2e/grafana", "/proxy%2fgrafana", "/%2F%2Fevil.example"]
    for (var i = 0; i < paths.length; i++) {
      var base = "https://grafana.example" + paths[i]
      compare(Grafana.build(base), {url: base, error: ""}, "Generic links retain shipped routes")
      rejected(Grafana.build(base, fixture(), {key: "steps", kind: "current"}))
    }
  }

  function test_owned_query_keys() {
    var owned = ["var-ActivityGPS", "time", "time.window", "from", "to", "viewPanel", "panelId", "timezone", "var-TimeZone"]
    var query = ["orgId=7", "keep=%2b+%26%3D", "var-Other=SECRET"]
    for (var i = 0; i < owned.length; i++) {
      query.push(owned[i] + "=old", owned[i] + "=stale")
      query.push("%" + owned[i].charCodeAt(0).toString(16) + owned[i].slice(1) + "=encoded")
    }
    var base = "https://grafana.example/proxy/d/UID/slug?" + query.join("&") + "#anchor?from=keep"
    compare(Grafana.build(base), {url: base, error: ""})
    var result = Grafana.build(base, fixture(), {key: "steps", kind: "current"})
    var parsed = params(result)
    compare(parsed.orgId, "7")
    compare(parsed.keep, "++&=")
    compare(parsed["var-Other"], "SECRET")
    verify(result.url.indexOf("keep=%2b+%26%3D") >= 0)
    verify(result.url.endsWith("#anchor?from=keep"))
    compare(Object.keys(parsed).length, 8)
    verify(parsed.time === undefined && parsed["time.window"] === undefined && parsed.panelId === undefined)
    verify(parsed["var-ActivityGPS"] === undefined)
  }

  function test_absolute_bounds_and_gaps() {
    var data = fixture()
    var ranges = [[0, 1], [-1000, 0], [1774742400000, 1774825200000], [1792882800000, 1792972800000]]
    // Dublin's spring day is 23 hours; its autumn day is 25 hours.
    compare(ranges[2][1] - ranges[2][0], 23 * 3600000)
    compare(ranges[3][1] - ranges[3][0], 25 * 3600000)
    for (var i = 0; i < ranges.length; i++) {
      data.metrics.steps = {value: null, date: "2026-09-04", from: ranges[i][0], to: ranges[i][1]}
      var query = params(Grafana.build("http://localhost", data, {key: "steps", kind: "current", date: "2026-09-05"}))
      compare(query.from, String(ranges[i][0]), "Current ignores selected date and uses the metric's own bounds")
      compare(query.to, String(ranges[i][1] - 1))
      query = params(Grafana.build("http://localhost", data, {key: "overlay", from: ranges[i][0], to: ranges[i][1]}))
      compare(query.viewPanel, "panel-29")
      compare(query.from, String(ranges[i][0]))
      compare(query.to, String(ranges[i][1] - 1))
    }
    data.history.steps[0].value = null
    var full = params(Grafana.build("http://localhost", data, {key: "steps", kind: "history", date: ""}))
    compare(full.from, "1788303600000")
    compare(full.to, "1788562799999", "Both null-valued ends remain in the full range")
    rejected(Grafana.build("http://localhost", data, {key: "steps", kind: "history", date: "2026-09-01"}), true)
    delete data.history.steps[0].from
    rejected(Grafana.build("http://localhost", data, {key: "steps", kind: "history"}), true)
    compare(params(Grafana.build("http://localhost", data,
      {key: "steps", kind: "history", date: "2026-09-02"})).from, "1788303600000")
  }

  function test_missing_metadata_and_bad_bounds() {
    var bad = [[undefined, undefined], [null, null], [0, undefined], [undefined, 1], [null, 1],
      [0, null], ["0", 1], [0, "1"], [false, 1], [0, true], [NaN, 1], [0, Infinity],
      [-Infinity, 0], [1, 1], [2, 1], [0.5, 2], [0, 1.5], [-8640000000000001, 0], [0, 8640000000000001]]
    var contexts = test_routing_data()
    for (var c = 0; c < contexts.length; c++) {
      var context = contexts[c]
      var wellness = ["sleepDuration", "restingHeartRate", "stress"].indexOf(context.key) >= 0
      for (var i = 0; i < bad.length; i++) {
        var data = fixture()
        var point = context.kind === "current" ? data[wellness ? "wellness" : "metrics"][context.key]
          : data[wellness ? "supplementalHistory" : "history"][context.key][context.date ? 1 : 0]
        point.from = bad[i][0]
        point.to = bad[i][1]
        data.sourceDayStart = "2026-09-05T00:00:00Z"
        data.sourceDayEnd = "2026-09-06T00:00:00Z"
        rejected(Grafana.build("http://localhost", data, context), true)
      }
    }
    for (var b = 0; b < bad.length; b++)
      rejected(Grafana.build("http://localhost", fixture(), {key: "overlay", from: bad[b][0], to: bad[b][1]}), true)
  }

  function test_history_dst_and_pair_independence() {
    var data = fixture()
    data.history.sleep = [{date: "2026-03-29", value: null, from: 1774742400000, to: 1774825200000}]
    data.supplementalHistory.sleepDuration = [{date: "2026-10-25", value: 0, from: 1792882800000, to: 1792972800000}]
    var sleep = params(Grafana.build("http://localhost", data, {key: "sleep", kind: "history", date: "2026-03-29"}))
    compare(sleep.from, "1774742400000")
    compare(sleep.to, "1774825199999")
    var duration = params(Grafana.build("http://localhost", data,
      {key: "sleepDuration", kind: "history", date: "2026-10-25"}))
    compare(duration.from, "1792882800000")
    compare(duration.to, "1792972799999")
    rejected(Grafana.build("http://localhost", data,
      {key: "sleepDuration", kind: "history", date: "2026-03-29"}), true)
    data.history.hrv = []
    rejected(Grafana.build("http://localhost", data, {key: "hrv", kind: "history"}), true)
    compare(params(Grafana.build("http://localhost", data,
      {key: "restingHeartRate", kind: "history"})).viewPanel, "panel-11")
  }

  function test_activities() {
    var data = fixture()
    var before = JSON.stringify(data)
    var start = Date.parse(data.latestActivity.time)
    var summary = params(Grafana.build("http://localhost", data, {key: "activity"}))
    var gps = params(Grafana.build("http://localhost", data, {key: "activityGps"}))
    verify(summary.viewPanel === undefined, "Activity opens all dashboard stats, not the Recent Activity table")
    compare(gps.viewPanel, "panel-50")
    compare(summary.from, String(start - 60000))
    compare(summary.to, String(start + 4320000 + 60000 - 1))
    compare(gps.from, summary.from)
    compare(gps.to, summary.to)
    verify(summary["var-ActivityGPS"] === undefined)
    compare(gps["var-ActivityGPS"], "synthetic")
    compare(JSON.stringify(data), before, "Builder does not mutate payload")
    data.status = "demo"
    compare(Grafana.build("http://localhost", data, {key: "activityGps"}).error, "", "Demo policy belongs in Service")
    data.latestActivity.type = "strength_training"
    compare(Grafana.build("http://localhost", data, {key: "activityGps"}).error, "", "Selector does not promise GPS data")
    data.latestActivity.durationSeconds = 0.123
    compare(params(Grafana.build("http://localhost", data, {key: "activityGps"})).to, String(start + 123 + 59999))
    var missing = [undefined, null, 0, -1, NaN, Infinity, "4320", true, {}]
    for (var i = 0; i < missing.length; i++) {
      data.latestActivity.durationSeconds = missing[i]
      summary = params(Grafana.build("http://localhost", data, {key: "activity"}))
      compare(summary.from, String(start - 60000))
      compare(summary.to, String(start + 59999))
      rejected(Grafana.build("http://localhost", data, {key: "activityGps"}), true)
    }
    data.latestActivity.durationSeconds = 1e308
    rejected(Grafana.build("http://localhost", data, {key: "activity"}), true)
  }

  function test_selectors() {
    var data = fixture()
    var selectors = ["  Morning run & walk / #123?x=1+2%20  ", "caf\u00e9 \u96ea \ud83d\udc1f", "https://SECRET.example/d/other",
      "x".repeat(256), "x".repeat(255) + "\ud83d\udc1f"]
    for (var i = 0; i < selectors.length; i++) {
      data.latestActivity.gpsSelector = selectors[i]
      var result = Grafana.build("http://localhost?var-ActivityGPS=old", data, {key: "activityGps"})
      compare(params(result)["var-ActivityGPS"], selectors[i])
      verify(result.url.indexOf("var-ActivityGPS=" + encodeURIComponent(selectors[i])) >= 0)
      verify(result.url.indexOf("http://localhost/d/") === 0)
    }
    var invalid = [undefined, null, 1, true, {}, [], "", "   ", "x".repeat(257), "\ud800", "\udfff",
      "SECRET\n", "SECRET\u007f", "SECRET\u0085", "SECRET\u202e", "SECRET\u200b", "SECRET\ue000"]
    for (var v = 0; v < invalid.length; v++) {
      data.latestActivity.gpsSelector = invalid[v]
      rejected(Grafana.build("http://localhost", data, {key: "activityGps"}), true)
      compare(Grafana.build("http://localhost", data, {key: "activity"}).error, "", "Summary needs no selector")
    }
  }

  function test_bad_urls_data() {
    var urls = [undefined, null, true, 1, {}, [], "", "localhost:3000", "ftp://localhost", "javascript:SECRET",
      "https:///path", "https://", "https://user:SECRET@host", "https://SECRET@host", "https://host:SECRET",
      "https://host:", "https://host:0", "https://host:65536", "https://host:-1", "https://host:1.5",
      "https://host:80:90", "https://[::1", "https://::1", "https://[hello]", "https://[1:2:3]",
      "https://[1:2:3:4:5:6:7:8:9]", "https://[1:2:3:4:5:6:7:8::]", "https://[1::2::3]", "https://[:::1]",
      "https://[::ffff:999.0.0.1]", "https://[fe80::1%25eth0]", "https://256.1.1.1", "https://127.1",
      "https://-host", "https://host-", "https://a..b", "https://host_foo", "https://%68ost",
      "https://host/SECRET\\path", " https://host", "https://host/SECRET\n", "https://host/a b",
      "https://host/a\u0085", "https://host/%00", "https://host/%5c", "https://host/%",
      "https://host/?x=%ZZ", "https://host/#%E0%A4", "https://host/\ud800", "https://host/?x=\udfff",
      "https://host/%ED%A0%80", "https://host/%ED%A0%BD%ED%B0%9F", "https://host/%C0%AF",
      "https://host/%E0%80%AF", "https://host/%F4%90%80%80", "https://host/%80",
      "https://" + "x".repeat(64) + ".example", "https://host/" + "x".repeat(8192)]
    return urls.map(function(url, index) { return {tag: "url-" + index, url: url} })
  }

  function test_bad_urls(row) {
    rejected(Grafana.build(row.url))
    rejected(Grafana.build(row.url, fixture(), {key: "activityGps"}))
    compare(Grafana.build(row.url).error, "Set a valid http(s) Grafana URL in bar settings.")
  }

  function test_length_limit() {
    var base = "http://localhost/?keep="
    base += "x".repeat(8192 - base.length)
    compare(Grafana.build(base), {url: base, error: ""})
    rejected(Grafana.build(base + "x"))
    rejected(Grafana.build(base, fixture(), {key: "activityGps"}))
  }

  function test_malformed_inputs() {
    var contexts = [null, false, 0, "steps", [], {}, {key: "SECRET"}, {key: "__proto__", kind: "current"},
      {key: "toString", kind: "history"}, {key: "trainingReadiness", kind: "current"}, {key: "steps"},
      {key: "steps", kind: "SECRET"}, {key: "steps", kind: "history", date: null},
      {key: "steps", kind: "history", date: "2026-02-30"}, {key: "steps", kind: "history", date: "2026-9-4"},
      {key: "steps", kind: "history", date: "SECRET\ud800"}]
    for (var c = 0; c < contexts.length; c++) rejected(Grafana.build("http://localhost", fixture(), contexts[c]))
    var invalid = [undefined, null, false, 0, "SECRET", [], {}]
    for (var i = 0; i < invalid.length; i++) {
      rejected(Grafana.build("http://localhost", invalid[i], {key: "steps", kind: "current"}), true)
      var data = fixture()
      data.metrics = data.wellness = data.history = data.supplementalHistory = invalid[i]
      var rows = test_routing_data()
      for (var r = 0; r < rows.length; r++) rejected(Grafana.build("http://localhost", data, rows[r]), true)
      data = fixture()
      data.latestActivity = invalid[i]
      rejected(Grafana.build("http://localhost", data, {key: "activity"}), true)
    }
    var times = [undefined, null, 0, "SECRET", "2026-09-04", "2026-09-04T10:00:00", "2026-02-30T10:00:00Z", "2026-09-04T24:00:00Z"]
    for (var t = 0; t < times.length; t++) {
      data = fixture()
      data.latestActivity.time = times[t]
      rejected(Grafana.build("http://localhost", data, {key: "activity"}), true)
    }
    var zones = [undefined, null, "", 0, {}, "SECRET&from=0", "Europe/SECRET\ud800", "x".repeat(129)]
    for (var z = 0; z < zones.length; z++) {
      data = fixture()
      data.timezone = zones[z]
      rejected(Grafana.build("http://localhost", data, {key: "activityGps"}), true)
    }
    data = fixture()
    data.timezone = "Etc/GMT+5"
    compare(params(Grafana.build("http://localhost", data, {key: "activity"}))["var-TimeZone"], "Etc/GMT+5")
    data.url = data.route = "https://SECRET.example/d/evil/route"
    var context = {key: "steps", kind: "current", url: data.url, route: data.route}
    var original = JSON.stringify(context)
    verify(Grafana.build("http://localhost", data, context).url.indexOf("http://localhost/d/feiibsx498gsgb/") === 0)
    compare(JSON.stringify(context), original)
  }
}
