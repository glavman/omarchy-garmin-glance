import QtQuick
import QtTest

TestCase {
  id: test
  name: "Navigation"
  width: 500; height: 500
  visible: true
  when: windowShown
  property var panel
  property var catcher
  QtObject {
    id: bar
    property var directions: []
    property string position: "top"
    property color barForeground: "#ffffff"
    function switchPanelFrom(owner, direction) { directions = directions.concat([direction]); return true }
  }
  Item { id: viewport; width: 500; height: 360 }
  QtObject {
    id: service
    property bool demoMode: false
    property bool busy: false
    property real now: Date.parse("2026-09-05T12:00:00Z")
    property string message: ""
    property var calls: []
    property var activityCalls: []
    property int refreshes: 0
    property var payload: ({schemaVersion: 1,
      history: {sleep: [{date: "2026-09-04", value: 80}], hrv: [{date: "2026-09-04", value: 40}]},
      supplementalHistory: {sleepDuration: [{date: "2026-09-04", value: 28800}], restingHeartRate: [{date: "2026-09-04", value: 50}]},
      latestActivity: {id: "9001", connectId: "9001", type: "running", maxHR: 150}})
    function openActivity(connectId) { activityCalls = activityCalls.concat([connectId]) }
    function ensureCharts() {}
    function openGrafana(context) { calls = calls.concat([context === undefined ? null : context]) }
    function refresh(charts) { refreshes++ }
  }
  function initTestCase() {
    var component = Qt.createComponent("../Panel.qml")
    if (component.status === Component.Error) {
      var error = component.errorString()
      verify(/module .*not installed|plugin .*not found|No PanelWindow backend/.test(error), error)
      skip("Requires Omarchy qs imports and the Quickshell runtime: " + error)
      return
    }
    panel = component.createObject(test, {service: service})
    verify(panel !== null, component.errorString())
    // Mount the native catcher without opening a layer-shell window.
    for (var i = 0; i < panel.data.length; i++) {
      var item = panel.data[i]
      if (typeof item.fittedContentWidth === "function") {
        catcher = item.contentItem[0]
        catcher.parent = viewport
        break
      }
    }
    verify(!!catcher)
    wait(30)
  }
  function init() {
    if (!panel) { skip("Native panel runtime unavailable"); return }
    service.calls = []; service.activityCalls = []; service.refreshes = 0; service.demoMode = false; service.busy = false
    service.now = Date.parse("2026-09-05T12:00:00Z")
    service.payload = {schemaVersion: 1,
      history: {sleep: [{date: "2026-09-04", value: 80}], hrv: [{date: "2026-09-04", value: 40}]},
      supplementalHistory: {sleepDuration: [{date: "2026-09-04", value: 28800}], restingHeartRate: [{date: "2026-09-04", value: 50}]},
      latestActivity: {id: "9001", connectId: "9001", type: "running", maxHR: 150}}
    panel.service = service; panel.showDetails = false; panel.historyKey = "steps"
    panel.activityLimit = 10; viewport.width = 500
    mouseMove(test, test.width - 1, test.height - 1)
    panel.setCursor("stats", 0, false)
    catcher.forceActiveFocus()
  }
  function cleanupTestCase() { if (panel) panel.destroy() }
  function test_navigation_and_pairs() {
    for (var i = 1; i < 7; i++) { keyClick(Qt.Key_Down); compare(panel.focusIndex, i) }
    keyClick(Qt.Key_J); compare(panel.focusSection, "selector")
    keyClick(Qt.Key_L); compare(panel.focusIndex, 1)
    keyClick(Qt.Key_Return); compare(panel.historyKey, "sleep"); compare(panel.focusSection, "history")
    keyClick(Qt.Key_Right); compare(panel.grafanaContext.date, "2026-09-04")
    keyClick(Qt.Key_Down); compare(panel.focusSection, "secondaryHistory")
    compare(panel.grafanaContext.key, "sleepDuration")
    compare(panel.cursorItem().samples[0].value, 8)
    keyClick(Qt.Key_Right); compare(panel.grafanaContext.date, "2026-09-04")
    keyClick(Qt.Key_3); compare(panel.historyKey, "hrv"); compare(panel.focusSection, "history")
    keyClick(Qt.Key_Down); compare(panel.grafanaContext.key, "restingHeartRate")
    keyClick(Qt.Key_1); keyClick(Qt.Key_Down); compare(panel.focusSection, "stress")
    verify(service.calls.length === 0)
  }
  function test_context_and_single_activation() {
    for (var i = 0; i < panel.fields.length; i++) {
      panel.setCursor("stats", i, false)
      compare(panel.grafanaContext, {key: panel.fields[i].key, kind: "current", date: ""})
    }
    panel.setCursor("stats", 1, false)
    keyClick(Qt.Key_Return)
    compare(service.calls.length, 1)
    compare(service.calls[0], {key: "bodyBattery", kind: "current", date: ""})
    keyClick(Qt.Key_Space); compare(service.calls.length, 2)
    keyClick(Qt.Key_B); keyClick(Qt.Key_O)
    compare(service.calls[2], {key: "overlay", from: panel.cursorItem().startTime, to: panel.cursorItem().endTime})
    keyClick(Qt.Key_A); compare(service.activityCalls, ["9001"]); compare(service.calls.length, 3)
    keyClick(Qt.Key_G); compare(service.calls[3], null)
    panel.setCursor("selector", 4, false)
    compare(panel.grafanaContext, {key: "bodyBattery", kind: "history", date: ""})
    panel.setCursor("stats", 4, false)
    verify(panel.contextLabel.indexOf("related") >= 0)
    panel.setCursor("footer", 0, false)
    keyClick(Qt.Key_Return); compare(service.calls[4].key, "hrv")
    keyClick(Qt.Key_L); keyClick(Qt.Key_Return); compare(service.refreshes, 1)
    service.busy = true; keyClick(Qt.Key_R); keyClick(Qt.Key_Space); compare(service.refreshes, 1)
  }
  function test_details_hover_and_reveal() {
    keyClick(Qt.Key_D); verify(panel.showDetails); compare(panel.focusSection, "details"); compare(panel.focusIndex, 1)
    wait(30)
    var scroll = catcher.children[0]
    verify(scroll.contentY > 0)
    var y = scroll.contentY
    panel.setCursor("stats", 2, false)
    wait(30); compare(scroll.contentY, y)
    keyClick(Qt.Key_K); compare(panel.focusSection, "stats"); compare(panel.focusIndex, 1)
    wait(30); verify(scroll.contentY < y)
    keyClick(Qt.Key_D); verify(!panel.showDetails); compare(panel.focusIndex, 0)
  }
  function test_unavailable_actions() {
    service.demoMode = true
    keyClick(Qt.Key_A); keyClick(Qt.Key_O); keyClick(Qt.Key_G); keyClick(Qt.Key_Return)
    compare(service.calls.length, 0)
    compare(service.activityCalls.length, 0)
    panel.service = null
    keyClick(Qt.Key_A); keyClick(Qt.Key_O); keyClick(Qt.Key_G); keyClick(Qt.Key_R)
    compare(service.calls.length, 0); compare(service.refreshes, 0)
    compare(service.activityCalls.length, 0)
  }
  function test_hover_focus_and_gps() {
    panel.setCursor("stats", 0, true)
    wait(150)
    var row = panel.cursorItem(), scroll = catcher.children[0]
    var y = scroll.contentY
    mouseMove(row, 10, row.height / 2)
    compare(panel.focusSection, "stats"); compare(panel.focusIndex, 0)
    compare(scroll.contentY, y)
    keyClick(Qt.Key_2); wait(150)
    var chart = panel.cursorItem()
    mouseClick(chart, chart.width / 2, chart.height / 2)
    verify(catcher.activeFocus); verify(!chart.activeFocus)
    keyClick(Qt.Key_B); wait(150)
    chart = panel.cursorItem()
    mouseClick(chart, chart.width / 2, chart.height / 2)
    verify(catcher.activeFocus); verify(!chart.activeFocus)
    var original = service.payload
    service.payload = Object.assign({}, original, {latestActivity: {type: "running", gpsSelector: "synthetic-activity", durationSeconds: 60}})
    panel.setCursor("footer", 3, false)
    keyClick(Qt.Key_Return); compare(service.calls[0], {key: "activityGps"})
    service.payload = original
    compare(panel.focusIndex, 2)
  }
  function test_narrow_context_button() {
    viewport.width = 240
    panel.setCursor("stress", 0, false)
    panel.setCursor("footer", 0, false)
    wait(30)
    var button = panel.cursorItem()
    verify(button.width <= viewport.width)
    verify(button.height > 0)
    viewport.width = 500
  }
  function activityBundle(count) {
    var items = []
    for (var i = 0; i < count; i++) items.push({id: String(1000 + i), connectId: String(1000 + i),
      time: new Date(Date.parse("2026-09-05T12:00:00Z") - i * 60000).toISOString(),
      date: "2026-09-05", type: i % 2 ? "trail_running" : "running",
      durationSeconds: 3600, distanceMeters: 1000, calories: 100})
    return {startDate: "2026-08-30", endDate: "2026-09-05",
      from: Date.parse("2026-08-30T00:00:00Z"), to: Date.parse("2026-09-06T00:00:00Z"), items: items}
  }
  function setActivities(bundle, error) {
    service.payload = Object.assign({}, service.payload, {activities: bundle,
      activitiesFetchedAt: "2026-09-05T12:00:00Z", activitiesError: error || null})
  }
  function test_activity_totals_and_dates() {
    var bundle = activityBundle(23)
    bundle.items[0].durationSeconds = null; bundle.items[0].calories = null
    bundle.items[1].distanceMeters = null
    setActivities(bundle)
    compare(panel.activitiesOverview.count, 23)
    compare(panel.visibleActivities.length, 10)
    compare(panel.activitiesOverview.types.length, 2)
    compare(panel.activitiesOverview.types[0].type, "running")
    compare(panel.activitiesOverview.types[0].count, 12)
    compare(panel.activitiesOverview.types[1].type, "trail_running")
    compare(panel.activityTotal(panel.activitiesOverview.duration, 23, "h"), "22.00 h (22/23 known)")
    compare(panel.activityTotal(panel.activitiesOverview.calories, 23, "kcal"), "2200 kcal (22/23 known)")
    compare(panel.activityTotal(panel.activitiesOverview.types[1].distance, 11, "km"), "10.00 km (10/11 known)")
    var totals = findChild(catcher, "activitiesTotals")
    verify(!!totals); compare(totals.text, "23 recorded / 22.00 h (22/23 known) / 2200 kcal (22/23 known)")
    verify(totals.text.indexOf("km") < 0)
    keyClick(Qt.Key_W); compare(panel.focusSection, "weekly")
    compare(panel.canOpenContext, false)
    keyClick(Qt.Key_O); compare(service.calls.length, 0); compare(service.activityCalls.length, 0)
    compare(panel.activitiesDateLabel, "2026-08-30 to 2026-09-05 / 7 days")
    service.now += 86400000
    verify(panel.activitiesCached)
    compare(panel.activitiesDateLabel, "2026-08-30 to 2026-09-05 / 7 days")
    service.now -= 86400000
  }
  function test_activity_states() {
    setActivities(null)
    compare(panel.activitiesOverview, null); verify(panel.activitiesStatus.indexOf("Waiting") >= 0)
    compare(findChild(catcher, "activitiesTotals").text, "-- recorded / -- h / -- kcal")
    service.busy = true; verify(panel.activitiesStatus.indexOf("Refreshing") >= 0)
    setActivities(null, "timeout"); verify(panel.activitiesStatus.indexOf("unavailable") >= 0)
    service.busy = false
    setActivities(activityBundle(0))
    compare(panel.activitiesOverview.count, 0); verify(panel.activitiesStatus.indexOf("No recorded activities") >= 0)
    compare(findChild(catcher, "activitiesTotals").text, "0 recorded / 0.00 h / 0 kcal")
    verify(panel.sections.indexOf("activities") < 0)
    setActivities(activityBundle(0), "timeout")
    verify(panel.activitiesStatus.indexOf("cached results") >= 0)
    var bundle = activityBundle(1)
    bundle.items[0].durationSeconds = null; bundle.items[0].distanceMeters = null; bundle.items[0].calories = null
    setActivities(bundle)
    compare(findChild(catcher, "activitiesTotals").text, "1 recorded / -- h (0/1 known) / -- kcal (0/1 known)")
    compare(panel.activityTotal(panel.activitiesOverview.types[0].distance, 1, "km"), "-- km (0/1 known)")
    panel.setCursor("activities", 0, false); compare(panel.cursorItem().values, "--")
  }
  function test_activity_row_actions() {
    var bundle = activityBundle(3)
    // Backend-local date is authoritative even when the timestamp has another date in UTC.
    bundle.items[0].date = "2026-09-04"
    setActivities(bundle)
    keyClick(Qt.Key_W); keyClick(Qt.Key_J)
    compare(panel.focusSection, "activities"); compare(panel.focusIndex, 0)
    compare(panel.cursorItem().modelData.id, "1000")
    compare(panel.cursorItem().description, "2026-09-04 / Running")
    compare(panel.cursorItem().values, "1 h / 1.00 km / 100 kcal")
    keyClick(Qt.Key_Return); compare(service.activityCalls, ["1000"])
    keyClick(Qt.Key_J); keyClick(Qt.Key_O); compare(service.activityCalls, ["1000", "1001"])
    keyClick(Qt.Key_J); wait(150)
    var row = panel.cursorItem()
    mouseClick(row, row.width / 2, row.height / 2)
    compare(service.activityCalls, ["1000", "1001", "1002"])
    verify(catcher.activeFocus)
    panel.setCursor("footer", 0, true); wait(30)
    compare(panel.cursorItem().tooltipText, "Open activity in Garmin Connect (O)")
    keyClick(Qt.Key_Return); compare(service.activityCalls[3], "1002")
    compare(service.calls.length, 0)
    keyClick(Qt.Key_A); compare(service.activityCalls[4], "9001")
    panel.setCursor("footer", 3, false)
    compare(panel.cursorItem().text, "Activity in Grafana")
    keyClick(Qt.Key_Return); compare(service.calls, [{key: "activity"}])
  }
  function test_activity_paging_and_shrink() {
    setActivities(activityBundle(23))
    keyClick(Qt.Key_W); keyClick(Qt.Key_J)
    for (var i = 0; i < 10; i++) keyClick(Qt.Key_J)
    compare(panel.focusIndex, 10); compare(panel.cursorItem().text, "Show more (10)")
    compare(panel.canOpenContext, false)
    keyClick(Qt.Key_O); compare(service.activityCalls.length, 0)
    keyClick(Qt.Key_Return)
    compare(panel.visibleActivities.length, 20); compare(panel.focusIndex, 10)
    compare(panel.cursorItem().modelData.id, "1010")
    compare(panel.activitiesOverview.count, 23)
    panel.setCursor("activities", 20, true); keyClick(Qt.Key_Space)
    compare(panel.visibleActivities.length, 23); compare(panel.focusIndex, 20); verify(!panel.moreActivities)
    panel.setCursor("activities", 22, true); wait(150)
    var scroll = catcher.children[0], row = panel.cursorItem()
    var position = row.mapToItem(scroll, 0, 0)
    verify(position.y >= -1); verify(position.y + row.height <= scroll.height + 1)
    panel.setCursor("footer", 0, false)
    setActivities(activityBundle(2))
    compare(panel.contextIndex, 1); compare(panel.contextActivity.id, "1001")
    keyClick(Qt.Key_O); compare(service.activityCalls, ["1001"])
    panel.setCursor("activities", 1, true)
    setActivities(activityBundle(1)); compare(panel.focusIndex, 0); compare(panel.contextIndex, 0)
    setActivities(activityBundle(0)); compare(panel.focusSection, "weekly"); compare(panel.contextSection, "weekly")
    compare(panel.canOpenContext, false)
    setActivities(activityBundle(23)); panel.activityLimit = 20
    panel.setCursor("activities", 19, false); panel.activityLimit = 10
    compare(panel.focusIndex, 10); compare(panel.contextIndex, 10); compare(panel.canOpenContext, false)
    panel.setCursor("activity", 0, false); keyClick(Qt.Key_K)
    compare(panel.focusSection, "activities"); compare(panel.focusIndex, 10)
  }
  function test_activity_hover_and_disabled_ids() {
    setActivities(activityBundle(3))
    wait(150)
    panel.setCursor("activities", 2, true); wait(150)
    panel.setCursor("activities", 1, false)
    var row = panel.cursorItem(), scroll = catcher.children[0], y = scroll.contentY
    panel.setCursor("activities", 2, false)
    mouseMove(test, test.width - 1, test.height - 1)
    wait(150)
    mouseMove(row, row.width / 2, row.height / 2)
    tryCompare(panel, "focusIndex", 1)
    compare(panel.focusIndex, 1); compare(panel.contextActivity.id, "1001"); compare(scroll.contentY, y)
    keyClick(Qt.Key_O); compare(service.activityCalls, ["1001"])
    service.activityCalls = []
    var ids = [undefined, null, "", "not-an-id", "12/34", 9001]
    for (var i = 0; i < ids.length; i++) {
      service.payload = Object.assign({}, service.payload, {latestActivity: {id: "9001", connectId: ids[i], type: "running"}})
      keyClick(Qt.Key_A); verify(!panel.canOpenContext)
      panel.setCursor("footer", 0, false); verify(!panel.cursorItem().enabled)
      keyClick(Qt.Key_Return); keyClick(Qt.Key_O)
      var bundle = activityBundle(1)
      bundle.items[0].connectId = ids[i]
      setActivities(bundle)
      panel.setCursor("activities", 0, false); verify(!panel.canOpenContext)
      keyClick(Qt.Key_Return); keyClick(Qt.Key_O)
    }
    compare(service.activityCalls.length, 0); compare(service.calls.length, 0)
    setActivities(activityBundle(3))
    service.demoMode = true
    panel.setCursor("activities", 0, false); keyClick(Qt.Key_O); keyClick(Qt.Key_Return)
    verify(!panel.canOpenContext); compare(service.activityCalls.length, 0)
  }
  function test_activity_narrow_and_full_count() {
    viewport.width = 240
    setActivities(activityBundle(500))
    compare(panel.activitiesOverview.count, 500)
    compare(panel.activitiesOverview.duration.value, 500 * 3600)
    compare(panel.visibleActivities.length, 10)
    panel.setCursor("activities", 0, true); wait(150)
    var row = panel.cursorItem()
    compare(row.width, 240)
    verify(row.height > 0)
    panel.setCursor("footer", 0, true); wait(30)
    var button = panel.cursorItem()
    verify(button.width <= viewport.width)
    compare(button.tooltipText, "Open activity in Garmin Connect (O)")
    for (var i = 1; i < 50; i++) panel.showMoreActivities(false)
    compare(panel.visibleActivities.length, 500); verify(!panel.moreActivities)
    compare(panel.activitiesOverview.count, 500)
    wait(150)
    panel.setCursor("activities", 499, true); wait(150)
    panel.setCursor("activities", 499, true); keyClick(Qt.Key_Return)
    compare(service.activityCalls, ["1499"])
    keyClick(Qt.Key_J); compare(panel.focusSection, "activity")
    keyClick(Qt.Key_K); compare(panel.focusSection, "activities"); compare(panel.focusIndex, 499)
  }
  function test_activity_id_without_connect_provenance() {
    var bundle = activityBundle(2)
    delete bundle.items[0].connectId
    setActivities(bundle)
    service.payload = Object.assign({}, service.payload, {latestActivity: bundle.items[0]})
    compare(panel.activitiesOverview.count, 2)
    compare(panel.visibleActivities.length, 2)
    compare(findChild(catcher, "activitiesTotals").text, "2 recorded / 2.00 h / 200 kcal")
    keyClick(Qt.Key_A); verify(!panel.canOpenContext)
    keyClick(Qt.Key_Return); keyClick(Qt.Key_O)
    panel.setCursor("footer", 0, false); verify(!panel.cursorItem().enabled)
    keyClick(Qt.Key_Return)
    panel.setCursor("activities", 0, true); wait(150)
    var row = panel.cursorItem()
    compare(row.modelData.id, "1000"); verify(!panel.canOpenContext)
    mouseClick(row, row.width / 2, row.height / 2)
    keyClick(Qt.Key_Return); keyClick(Qt.Key_O)
    panel.setCursor("footer", 0, false); verify(!panel.cursorItem().enabled)
    keyClick(Qt.Key_Return)
    compare(service.activityCalls.length, 0); compare(service.calls.length, 0)
    panel.setCursor("activities", 1, true); keyClick(Qt.Key_Return)
    compare(service.activityCalls, ["1001"])
  }
  function test_tab_and_escape() {
    bar.directions = []; panel.bar = bar
    keyClick(Qt.Key_Tab); keyClick(Qt.Key_Tab, Qt.ShiftModifier)
    compare(bar.directions, [1, -1])
    panel.bar = null
    var closed = 0
    function onClose() { closed++ }
    catcher.closeRequested.connect(onClose)
    keyClick(Qt.Key_Escape)
    compare(closed, 1)
    catcher.closeRequested.disconnect(onClose)
  }
}
