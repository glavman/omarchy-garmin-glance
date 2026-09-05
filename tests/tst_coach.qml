import QtQuick
import QtTest
import qs.Ui as Ui
import ".." as Garmin

TestCase {
  id: test
  name: "Coach"
  when: windowShown
  visible: true
  width: 360; height: 800

  Component { id: realService; Garmin.Service {} }
  property var workerUnderTest: null
  property string syntheticOutput: ""
  property int syntheticExit: 0
  property bool syntheticChunks: false
  property bool syntheticDelay: false
  SignalSpy { id: scrollRequests; target: coach; signalName: "scrollRequested" }
  QtObject {
    id: syntheticShell
    property var shellConfig: ({plugins: [{demoMode: false}]})
  }
  QtObject {
    id: syntheticRegistry
    function findEntryLocation(config, id) { return {found: true, kind: "plugin", index: 0} }
  }
  Connections {
    target: test.workerUnderTest
    function onCommandChanged() {
      var worker = test.workerUnderTest
      if (worker.command.length !== 3 || !worker.command[1].endsWith("/coach.py")) return
      // Replace the helper before Process.running is set; no settings, data or agent is accessed.
      var script = "import json,sys,time; "
        + (worker.command[2] === "launch" ? "request=json.load(sys.stdin); assert request == "
          + JSON.stringify({intent: "question", days: 7, stepGoal: 9000, agent: "grok"}) + "; " : "")
        + (test.syntheticDelay ? "time.sleep(2); " : "")
        + "s=" + JSON.stringify(test.syntheticOutput) + "; "
        + (test.syntheticChunks ? "sys.stdout.write(s[:12]); sys.stdout.flush(); time.sleep(0.03); sys.stdout.write(s[12:]); " : "sys.stdout.write(s); ")
        + "sys.stderr.write('UNTRUSTED STDERR'); sys.exit(" + test.syntheticExit + ")"
      worker.command = ["/usr/bin/python3", "-c", script]
    }
  }

  QtObject {
    id: service
    property bool demoMode: false
    property var payload: null
    property bool busy: false
    property real now: Date.now()
    property string message: ""
    property var grafanaCalls: []
    property var activityCalls: []
    property int refreshes: 0
    function openGrafana(context) { grafanaCalls = grafanaCalls.concat([context === undefined ? null : context]) }
    function openActivity(connectId) { activityCalls = activityCalls.concat([connectId]) }
    function refresh(charts) { refreshes++ }
    function ensureCharts() {}
    property bool coachBusy: false
    property string coachAgent: ""
    property string coachMessage: ""
    property int checks: 0
    property int launches: 0
    property int clears: 0
    property var request: null
    function checkCoach() { checks++; coachAgent = ""; coachBusy = true }
    function launchCoach(intent, days, stepGoal, agent) {
      launches++
      request = {intent: intent, days: days, stepGoal: stepGoal, agent: agent}
      coachBusy = true
    }
    function clearCoach() { clears++; coachBusy = true }
  }
  Ui.PanelKeyCatcher {
    id: keys
    anchors.fill: parent
    blocked: coach.expanded || coach.activeFocus
    property int chartMoves: 0
    property int textKeys: 0
    onMoveRequested: chartMoves++
    onTextKey: textKeys++
    Garmin.Coach { id: coach; width: test.width; service: service; stepGoal: 9000 }
  }

  function init() {
    service.demoMode = false
    service.coachBusy = false
    service.coachAgent = ""
    service.coachMessage = ""
    service.checks = 0; service.launches = 0; service.clears = 0; service.request = null
    service.payload = null; service.grafanaCalls = []; service.activityCalls = []; service.refreshes = 0
    syntheticDelay = false
    coach.dismiss()
    keys.chartMoves = 0; keys.textKeys = 0
    scrollRequests.clear()
  }
  function ready() {
    coach.open()
    service.coachAgent = "codex"
    service.coachBusy = false
    coach.chooseIntent("day")
  }
  function test_demand_and_consent() {
    compare(service.checks, 0)
    verify(!coach.expanded)
    verify(!coach.canOpen)
    coach.open()
    compare(service.checks, 1)
    verify(coach.expanded)
    coach.launch()
    compare(service.launches, 0)
    service.coachAgent = "opencode"
    service.coachBusy = false
    verify(!coach.canOpen)
    coach.chooseIntent("question")
    verify(coach.canOpen)
    compare(service.launches, 0, "Discovery and selections never launch automatically")
    coach.launch()
    compare(service.launches, 1)
    compare(service.request, {intent: "question", days: 7, stepGoal: 9000, agent: "opencode"})
    verify(!coach.canOpen)
    coach.launch()
    coach.chooseIntent("week")
    compare(service.launches, 1)
    compare(coach.intent, "question")
    verify(!findChild(coach, "coachLaunch").enabled)
    verify(!findChild(coach, "coachDays_30").enabled)
  }
  function test_async_check_preserves_selection() {
    ready()
    coach.days = 90
    coach.chooseIntent("week")
    service.checkCoach()
    service.coachAgent = "claude"
    service.coachBusy = false
    compare(coach.days, 90)
    compare(coach.intent, "week")
    compare(service.launches, 0)
    coach.launch()
    compare(service.request.agent, "claude")
  }
  function test_unconfirmed_and_invalid_agent() {
    ready()
    service.coachAgent = ""
    verify(!coach.canOpen)
    coach.launch()
    compare(service.launches, 0)
    service.coachAgent = "unknown"
    verify(!coach.canOpen)
    coach.launch()
    compare(service.launches, 0)
  }
  function test_grok_and_history_windows() {
    ready()
    service.coachAgent = "grok"
    verify(findChild(coach, "coachAgent").text.indexOf("Grok") >= 0)
    for (var days of [7, 30, 90]) {
      findChild(coach, "coachDays_" + days).clicked()
      compare(coach.days, days)
      verify(coach.canOpen)
      compare(service.launches, 0)
    }
    findChild(coach, "coachLaunch").clicked()
    compare(service.request, {intent: "day", days: 90, stepGoal: 9000, agent: "grok"})
  }
  function test_clear_confirmation() {
    ready()
    coach.clearFiles()
    compare(service.clears, 0)
    findChild(coach, "coachClear").clicked()
    verify(coach.confirmingClear)
    verify(!coach.canOpen)
    compare(service.clears, 0)
    coach.clearFiles()
    compare(service.clears, 1)
    coach.clearFiles()
    compare(service.clears, 1)
  }
  function test_demo_blocks_every_action() {
    ready()
    service.demoMode = true
    verify(!coach.expanded)
    verify(!findChild(coach, "coachEntry").enabled)
    coach.open()
    coach.launch()
    coach.confirmingClear = true
    coach.clearFiles()
    compare(service.checks, 1)
    compare(service.launches, 0)
    compare(service.clears, 0)
  }
  function test_cancel_and_keyboard() {
    ready()
    var windowButton = findChild(coach, "coachDays_30")
    windowButton.forceActiveFocus()
    tryCompare(windowButton, "activeFocus", true)
    keyClick(Qt.Key_Space)
    compare(coach.days, 30)
    keyClick(Qt.Key_Right)
    keyClick(Qt.Key_S)
    compare(keys.chartMoves, 0)
    compare(keys.textKeys, 0)
    keyClick(Qt.Key_Down)
    keyClick(Qt.Key_Up)
    keyClick(Qt.Key_PageDown)
    keyClick(Qt.Key_PageUp)
    compare(scrollRequests.count, 4)
    for (var k = 0; k < 4; k++) {
      compare(scrollRequests.signalArguments[k][0], k % 2 === 0 ? 1 : -1)
      compare(scrollRequests.signalArguments[k][1], k >= 2)
    }
    compare(keys.chartMoves, 0)
    keyClick(Qt.Key_Tab)
    verify(!windowButton.activeFocus, "Tab moves to another coach control")
    keyClick(Qt.Key_Escape)
    verify(!coach.expanded)
    compare(coach.intent, "")
    compare(service.launches, 0)
    coach.open()
    compare(coach.intent, "")
    compare(coach.days, 7)
  }
  function test_small_width() {
    ready()
    coach.width = 180
    wait(0)
    var button = findChild(coach, "coachLaunch")
    verify(button.width <= coach.width)
    verify(findChild(coach, "coachAgent").width <= coach.width)
    verify(findChild(coach, "coachAgent").height > 20)
    coach.width = test.width
  }

  function test_worker_stream_isolation() {
    workerUnderTest = null
    var real = createTemporaryObject(realService, test)
    verify(real !== null)
    // Stop backend startup and polling synchronously, before the event loop can run them.
    for (var i = 0; i < real.data.length; i++) {
      var object = real.data[i]
      if (typeof object.stop === "function") object.stop()
      if (typeof object.write === "function" && !workerUnderTest) workerUnderTest = object
    }
    verify(workerUnderTest !== null)
    real.payload = {schemaVersion: 1, status: "ok"}
    var checked = '{"schemaVersion":1,"status":"ok","error":null,"agent":"grok"}'
    var ok = '{"schemaVersion":1,"status":"ok","error":null}'
    var cases = [
      {output: checked, agent: "grok"},
      {output: checked, agent: "grok"},
      {output: "", error: "invalid_response"},
      {output: checked, agent: "grok", chunks: true},
      {output: ok, launch: true},
      {output: ok, launch: true},
      {output: "", launch: true, error: "invalid_response"},
      {output: ok, launch: true, chunks: true},
      {output: ok + "\n" + ok, launch: true, error: "invalid_response"},
      {output: " ", error: "invalid_response"},
      {output: checked, exitCode: 1, error: "launch_failed"},
      {output: new Array(6000).join("x"), error: "response_too_large"},
      {output: "", error: "invalid_response"},
      {output: checked + "\n", agent: "grok"},
      {output: checked + "\n", agent: "grok"}
    ]
    for (var c = 0; c < cases.length; c++) {
      var row = cases[c]
      syntheticOutput = row.output
      syntheticExit = row.exitCode || 0
      syntheticChunks = row.chunks === true
      if (row.launch) real.coachAgent = "grok"
      verify(row.launch ? real.launchCoach("question", 7, 9000, "grok") : real.checkCoach())
      tryCompare(real, "coachBusy", false, 3000)
      compare(real.coachOutput, "", "response buffer cleared after stream " + c)
      if (row.error) compare(real.coachMessage, real.coachError(row.error), "stream case " + c)
      else if (row.agent) compare(real.coachAgent, row.agent, "stream case " + c)
      else compare(real.coachMessage, "Agent launch requested. Agent readiness, data loading and answer completion are not confirmed.")
      verify(real.coachMessage.indexOf("UNTRUSTED") < 0)
    }
    real.coachAgent = "grok"
    verify(!real.launchCoach("question", 7, 9000, "unknown"))
    verify(!real.launchCoach("question", 7, 9000, "codex"))
    verify(!real.launchCoach("invalid", 7, 9000, "grok"))
    verify(!real.launchCoach("question", 14, 9000, "grok"))
    for (var goal of [0, -1, NaN, Infinity, "9000"])
      verify(!real.launchCoach("question", 7, goal, "grok"))
    syntheticDelay = true
    syntheticOutput = checked
    syntheticExit = 0
    syntheticChunks = false
    verify(real.checkCoach())
    tryVerify(function() { return workerUnderTest.processId > 0 })
    var watchdog = null
    for (var t = 0; t < real.data.length; t++)
      if (real.data[t].interval === 35000) watchdog = real.data[t]
    verify(watchdog !== null)
    watchdog.triggered()
    tryCompare(real, "coachBusy", false, 3000)
    compare(real.coachMessage, real.coachError("timeout"))
    compare(real.coachAgent, "")
    // Demo changes cancel only the coach worker and invalidate its consent/discovery state.
    real.manifest = {id: "synthetic"}
    real.pluginRegistry = syntheticRegistry
    syntheticShell.shellConfig = {plugins: [{demoMode: false}]}
    real.shell = syntheticShell
    verify(real.checkCoach())
    tryVerify(function() { return workerUnderTest.processId > 0 })
    syntheticShell.shellConfig = {plugins: [{demoMode: true}]}
    for (var s = 0; s < real.data.length; s++)
      if (typeof real.data[s].stop === "function") real.data[s].stop()
    tryCompare(real, "coachBusy", false, 3000)
    compare(real.coachMessage, "")
    compare(real.coachAgent, "")
    verify(!real.checkCoach()); verify(!real.clearCoach())
    verify(!real.launchCoach("question", 7, 9000, "grok"))
    compare(real.busy, false)
    workerUnderTest = null
  }

  function test_panel_keyboard_scroll() {
    var panelComponent = Qt.createComponent("../Panel.qml")
    if (panelComponent.status !== Component.Ready && panelComponent.errorString().indexOf("No PanelWindow backend loaded") >= 0) {
      skip("Panel integration requires a Quickshell window backend and host imports")
      return
    }
    compare(panelComponent.status, Component.Ready, panelComponent.errorString())
    var panel = createTemporaryObject(panelComponent, test, {service: service, settings: {stepGoal: 8500, watchModel: "Synthetic watch"}})
    verify(panel !== null)
    var panelKeys = findChild(panel, "garminPanelKeys")
    var viewport = findChild(panel, "garminPanelScroll")
    var panelCoach = findChild(panel, "garminPanelCoach")
    verify(panelKeys !== null && viewport !== null && panelCoach !== null)
    var headerSlot = findChild(panel, "coachHeaderSlot")
    verify(headerSlot !== null)
    compare(panelCoach.entryButton.parent, headerSlot)
    // Mount the real panel content in the test window, without opening a shell layer surface.
    var originalParent = panelKeys.parent
    panelKeys.parent = test
    tryVerify(function() { return Math.abs(headerSlot.x + headerSlot.width - headerSlot.parent.width) < 1 })
    compare(headerSlot.y, 0)
    compare(panelCoach.stepGoal, 8500)
    panel.settings = {stepGoal: -1}
    compare(panelCoach.stepGoal, 10000)
    panel.settings = {stepGoal: 8500}
    service.payload = {schemaVersion: 1,
      history: {steps: [{date: "2026-09-04", value: 5000}], sleep: [{date: "2026-09-04", value: 80}]},
      supplementalHistory: {sleepDuration: [{date: "2026-09-04", value: 28800}]},
      latestActivity: {id: "local-only", connectId: "9001", type: "running", maxHR: 150}}
    panel.setCursor("history", 0, false)
    var history = panel.cursorItem()
    panel.setCursor("secondaryHistory", 0, false)
    var secondary = panel.cursorItem()
    panel.setCursor("stress", 0, false)
    var overlay = panel.cursorItem()
    panel.setCursor("history", 0, false)
    panelCoach.open()
    service.coachAgent = "codex"
    service.coachBusy = false
    panelCoach.chooseIntent("day")
    wait(0)
    var windowButton = findChild(panelCoach, "coachDays_30")
    windowButton.forceActiveFocus()
    tryCompare(windowButton, "activeFocus", true)
    viewport.contentY = 0
    keyClick(Qt.Key_Down)
    verify(viewport.contentY > 0)
    keyClick(Qt.Key_Up)
    compare(viewport.contentY, 0)
    keyClick(Qt.Key_PageDown)
    verify(viewport.contentY > viewport.height / 2)
    keyClick(Qt.Key_PageUp)
    compare(viewport.contentY, 0)
    var chartCursors = [history.cursor, secondary.cursor, overlay.cursorTime]
    for (var key of [Qt.Key_Right, Qt.Key_Left, Qt.Key_J, Qt.Key_K, Qt.Key_H, Qt.Key_L,
                     Qt.Key_2, Qt.Key_B, Qt.Key_W, Qt.Key_A, Qt.Key_O, Qt.Key_G, Qt.Key_R]) keyClick(key)
    compare(panel.focusSection, "history")
    compare(panel.focusIndex, 0)
    compare(panel.contextSection, "history")
    compare(panel.historyKey, "steps")
    compare(history.cursor, chartCursors[0]); compare(secondary.cursor, chartCursors[1])
    verify(isNaN(overlay.cursorTime) && isNaN(chartCursors[2]))
    compare(service.grafanaCalls, []); compare(service.activityCalls, []); compare(service.refreshes, 0)
    compare(service.launches, 0)
    // Scroll also works if focus is on the key catcher rather than an enabled consent control.
    panelKeys.forceActiveFocus()
    keyClick(Qt.Key_Down)
    verify(viewport.contentY > 0)
    viewport.contentY = 0
    keyClick(Qt.Key_Up)
    compare(viewport.contentY, 0)
    viewport.contentY = viewport.contentHeight - viewport.height
    keyClick(Qt.Key_PageDown)
    compare(viewport.contentY, viewport.contentHeight - viewport.height)
    keyClick(Qt.Key_Escape)
    verify(!panelCoach.expanded)
    tryCompare(panelKeys, "activeFocus", true)
    verify(!panelKeys.blocked)
    // Normal dashboard navigation and provenance-gated actions resume after dismissal.
    keyClick(Qt.Key_Right)
    compare(history.cursor, 0)
    keyClick(Qt.Key_O)
    compare(service.grafanaCalls, [{key: "steps", kind: "history", date: "2026-09-04"}])
    keyClick(Qt.Key_2)
    compare(panel.historyKey, "sleep")
    keyClick(Qt.Key_Down)
    compare(panel.focusSection, "secondaryHistory")
    compare(secondary.samples[0].value, 8)
    keyClick(Qt.Key_A)
    compare(service.activityCalls, ["9001"])
    service.payload = Object.assign({}, service.payload, {latestActivity: {id: "9001", type: "running"}})
    keyClick(Qt.Key_A)
    compare(service.activityCalls, ["9001"], "Local id must never substitute for connectId")
    var items = []
    for (var n = 0; n < 23; n++) items.push({id: "local-" + n, connectId: String(1000 + n),
      time: "2026-09-05T12:00:00Z", date: "2026-09-05", type: "running",
      durationSeconds: 3600, distanceMeters: 1000, calories: 100})
    service.payload = Object.assign({}, service.payload, {activities: {
      startDate: "2026-08-30", endDate: "2026-09-05", from: Date.parse("2026-08-30T00:00:00Z"),
      to: Date.parse("2026-09-06T00:00:00Z"), items: items}, activitiesFetchedAt: "2026-09-05T12:00:00Z"})
    compare(panel.activitiesOverview.count, 23)
    compare(panel.visibleActivities.length, 10)
    compare(findChild(panelKeys, "activitiesTotals").text, "23 recorded / 23.00 h / 2300 kcal")
    keyClick(Qt.Key_W); keyClick(Qt.Key_Down)
    compare(panel.focusSection, "activities")
    keyClick(Qt.Key_Return)
    compare(service.activityCalls, ["9001", "1000"])
    panel.setCursor("activities", 10, false)
    keyClick(Qt.Key_Return)
    compare(panel.visibleActivities.length, 20)
    compare(panel.focusIndex, 10)
    keyClick(Qt.Key_O)
    compare(service.activityCalls, ["9001", "1000", "1010"])
    panel.setCursor("activities", 20, false)
    keyClick(Qt.Key_Space)
    compare(panel.visibleActivities.length, 23)
    verify(!panel.moreActivities)
    service.payload = Object.assign({}, service.payload, {activities: Object.assign({}, service.payload.activities, {items: []})})
    compare(panel.focusSection, "weekly")
    verify(!panel.canOpenContext)
    keyClick(Qt.Key_B)
    keyClick(Qt.Key_Right)
    verify(isFinite(overlay.cursorTime))
    // Exercise the real close lifecycle without opening a layer-shell surface.
    var popup = null
    for (var i = 0; i < panel.data.length; i++)
      if (typeof panel.data[i].fittedContentWidth === "function") popup = panel.data[i]
    verify(popup !== null)
    popup.open = false
    panel.controller.open = true
    keyClick(Qt.Key_C)
    service.coachBusy = false
    panelCoach.chooseIntent("week")
    panel.close()
    verify(!panelCoach.expanded)
    compare(panelCoach.intent, "")
    tryCompare(panelKeys, "activeFocus", true)
    panelKeys.parent = originalParent
    panel.destroy()
  }
}
