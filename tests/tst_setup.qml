import QtQuick
import QtQuick.Window
import QtTest
import "../Setup.js" as Guide

TestCase {
  id: test
  name: "Setup"
  when: windowShown
  visible: true
  width: 360; height: 800

  property var panel: null
  property var keys: null
  property var viewport: null
  property var setup: null
  property var originalParent: null
  QtObject {
    id: service
    property bool demoMode: true
    property bool requestedDemoMode: true
    property bool busy: false
    property real now: Date.parse("2026-09-05T12:00:00Z")
    property string message: ""
    property var payload: null
    property var calls: []
    property bool coachBusy: false
    property string coachAgent: ""
    property string coachMessage: ""
    function refresh(charts) { calls = calls.concat([{action: "refresh", charts: charts}]) }
    function ensureCharts() { calls = calls.concat([{action: "ensureCharts"}]) }
    function openGrafana(context) { calls = calls.concat([{action: "grafana"}]) }
    function openActivity(connectId) { calls = calls.concat([{action: "activity"}]) }
    function checkCoach() { calls = calls.concat([{action: "checkCoach"}]) }
    function launchCoach(intent, days, stepGoal, agent) { calls = calls.concat([{action: "launchCoach"}]) }
    function clearCoach() { calls = calls.concat([{action: "clearCoach"}]) }
  }
  SignalSpy { id: panelTabs; signalName: "tabRequested" }

  function init() {
    test.width = 360
    service.demoMode = true; service.requestedDemoMode = true; service.busy = false
    service.calls = []
    service.payload = {schemaVersion: 1,
      history: {steps: [{date: "2026-09-04", value: 5000}], sleep: [{date: "2026-09-04", value: 80}]},
      supplementalHistory: {sleepDuration: [{date: "2026-09-04", value: 28800}]},
      latestActivity: {id: "local-only", connectId: "9001", type: "running", maxHR: 150}}
    var component = Qt.createComponent("../Panel.qml")
    compare(component.status, Component.Ready, component.errorString())
    panel = createTemporaryObject(component, test, {service: service,
      settings: {watchModel: "Synthetic watch"}})
    verify(panel !== null)
    keys = findChild(panel, "garminPanelKeys")
    viewport = findChild(panel, "garminPanelScroll")
    setup = findChild(panel, "garminPanelSetup")
    verify(keys !== null && viewport !== null && setup !== null)
    // Mount real content without opening a shell layer surface or creating a real Service.
    originalParent = keys.parent
    keys.parent = test
    panelTabs.target = keys
    panelTabs.clear()
    keys.forceActiveFocus()
    tryCompare(keys, "activeFocus", true)
    wait(0)
  }

  function cleanup() {
    panelTabs.target = null
    if (keys && originalParent) keys.parent = originalParent
    panel = null; keys = null; viewport = null; setup = null; originalParent = null
    test.width = 360
  }

  function openSetup() {
    keys.forceActiveFocus()
    keyClick(Qt.Key_S)
    verify(setup.expanded)
    tryCompare(findChild(setup, "setupCopy"), "activeFocus", true)
    verify(keys.blocked)
    // Reparenting and expansion queue nested Column layouts; wait(0) can leave contentHeight at zero.
    verify(waitForPolish(test.Window.window), "Panel layout must settle before geometry assertions")
  }

  function textItems(item) {
    var result = []
    if (typeof item.text === "string" && typeof item.wrapMode !== "undefined") result.push(item)
    for (var child of item.children) result = result.concat(textItems(child))
    return result
  }

  function test_prompt_and_copy_feedback() {
    openSetup()
    var prompt = findChild(setup, "setupPrompt")
    var copy = findChild(setup, "setupCopy")
    compare(prompt.text, Guide.prompt)
    compare(prompt.textFormat, TextEdit.PlainText)
    verify(prompt.readOnly && prompt.selectByMouse)
    compare(copy.text, "Copy setup prompt")
    verify(copy.enabled && copy.focusable)
    // Exercise the result label, not TextEdit.copy(), which writes the desktop clipboard.
    setup.copied = true
    compare(copy.text, "Prompt copied")
    compare(prompt.text, Guide.prompt)
    setup.dismiss()
    verify(!setup.copied)
    compare(copy.text, "Copy setup prompt")
    setup.copied = true
    openSetup()
    verify(!setup.copied)
    compare(service.calls, [])
  }

  function test_entry_and_escape_return_focus() {
    var entry = findChild(setup, "setupEntry")
    verify(!setup.expanded)
    compare(entry.text, "Set up live data (S)")
    entry.clicked()
    verify(setup.expanded)
    compare(entry.text, "Close setup")
    entry.clicked()
    verify(!setup.expanded)
    tryCompare(keys, "activeFocus", true)
    openSetup()
    keyClick(Qt.Key_Escape)
    verify(!setup.expanded)
    tryCompare(keys, "activeFocus", true)
    verify(!keys.blocked)
    keyClick(Qt.Key_2)
    compare(panel.historyKey, "sleep")
    keyClick(Qt.Key_R)
    compare(service.calls, [{action: "refresh", charts: true}])
  }

  function test_no_automatic_actions() {
    verify(!setup.expanded)
    compare(service.calls, [])
    openSetup()
    compare(findChild(setup, "setupDocs").text, "Open setup guide")
    verify(findChild(setup, "setupDocs").enabled)
    verify(!findChild(keys, "coachEntry").enabled)
    wait(50)
    compare(service.calls, [])
    setup.dismiss()
    service.demoMode = false
    service.requestedDemoMode = false
    openSetup()
    wait(50)
    compare(service.calls, [], "Opening guidance must not query, discover or launch an agent")
  }

  function test_explicit_demo_notice() {
    openSetup()
    var notices = textItems(setup).filter(function(item) {
      return item.text.indexOf("Synthetic demo data is explicitly enabled") >= 0
    })
    compare(notices.length, 1)
    verify(notices[0].visible)
    service.requestedDemoMode = false
    verify(!notices[0].visible)
    service.requestedDemoMode = true
    service.demoMode = false
    verify(!notices[0].visible)
  }

  function test_refresh_action_and_availability() {
    openSetup()
    var refresh = findChild(setup, "setupRefresh")
    verify(refresh.enabled)
    refresh.forceActiveFocus()
    keyClick(Qt.Key_Return)
    compare(service.calls, [{action: "refresh", charts: true}])
    verify(setup.expanded)
    service.busy = true
    verify(!refresh.enabled)
    service.busy = false
    verify(refresh.enabled)
    panel.service = null
    verify(!refresh.enabled)
    compare(service.calls, [{action: "refresh", charts: true}])
  }

  function test_dashboard_keyboard_isolation_data() {
    return [{tag: "copy", target: "setupCopy"}, {tag: "prompt", target: "setupPrompt"},
      {tag: "catcher", target: "garminPanelKeys"}]
  }
  function test_dashboard_keyboard_isolation(row) {
    // Live fixture mode makes leaked Grafana/Coach shortcuts observable rather than demo-gated.
    service.demoMode = false
    panel.setCursor("history", 0, false)
    var history = panel.cursorItem()
    panel.setCursor("stress", 0, false)
    var overlay = panel.cursorItem()
    panel.setCursor("history", 0, false)
    openSetup()
    var target = row.target === "garminPanelKeys" ? keys : findChild(setup, row.target)
    target.forceActiveFocus()
    tryCompare(target, "activeFocus", true)
    var cursor = history.cursor, overlayCursor = overlay.cursorTime
    for (var key of [Qt.Key_Right, Qt.Key_Left, Qt.Key_J, Qt.Key_K, Qt.Key_H, Qt.Key_L,
                     Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4, Qt.Key_5, Qt.Key_B, Qt.Key_W,
                     Qt.Key_D, Qt.Key_A, Qt.Key_O, Qt.Key_G, Qt.Key_R, Qt.Key_C, Qt.Key_S]) keyClick(key)
    compare(panel.focusSection, "history"); compare(panel.focusIndex, 0)
    compare(panel.contextSection, "history"); compare(panel.contextIndex, 0)
    compare(panel.historyKey, "steps")
    verify(!panel.showDetails)
    compare(history.cursor, cursor)
    verify(isNaN(overlay.cursorTime) && isNaN(overlayCursor))
    compare(findChild(setup, "setupPrompt").text, Guide.prompt)
    verify(setup.expanded)
    compare(service.calls, [])
    keyClick(Qt.Key_Escape)
    verify(!setup.expanded)
    tryCompare(keys, "activeFocus", true)
    verify(!keys.blocked)
  }

  function test_tab_stays_in_setup_and_reveals_controls() {
    openSetup()
    var copy = findChild(setup, "setupCopy")
    var docs = findChild(setup, "setupDocs")
    var refresh = findChild(setup, "setupRefresh")
    keyClick(Qt.Key_Tab)
    tryCompare(docs, "activeFocus", true)
    keyClick(Qt.Key_Tab)
    tryCompare(refresh, "activeFocus", true)
    var top = refresh.mapToItem(viewport.contentItem, 0, 0).y
    verify(top >= viewport.contentY - 1)
    verify(top + refresh.height <= viewport.contentY + viewport.height + 1)
    keyClick(Qt.Key_Backtab, Qt.ShiftModifier)
    tryCompare(docs, "activeFocus", true)
    keyClick(Qt.Key_Backtab, Qt.ShiftModifier)
    tryCompare(copy, "activeFocus", true)
    compare(panelTabs.count, 0)
    compare(service.calls, [])
  }

  function test_keyboard_scrolling_data() {
    return [{tag: "control", catcher: false}, {tag: "catcher", catcher: true}]
  }
  function test_keyboard_scrolling(row) {
    openSetup()
    if (row.catcher) keys.forceActiveFocus()
    verify(viewport.contentHeight > viewport.height)
    viewport.contentY = 0
    keyClick(Qt.Key_Down)
    verify(viewport.contentY > 0)
    keyClick(Qt.Key_Up)
    compare(viewport.contentY, 0)
    keyClick(Qt.Key_PageDown)
    verify(viewport.contentY > viewport.height / 2)
    keyClick(Qt.Key_PageUp)
    compare(viewport.contentY, 0)
    keyClick(Qt.Key_Up)
    compare(viewport.contentY, 0)
    viewport.contentY = viewport.contentHeight - viewport.height
    keyClick(Qt.Key_PageDown)
    compare(viewport.contentY, viewport.contentHeight - viewport.height)
    compare(panel.focusSection, "stats")
    compare(panel.focusIndex, 0)
    compare(service.calls, [])
  }

  function test_narrow_prompt_wrapping() {
    openSetup()
    var prompt = findChild(setup, "setupPrompt")
    var wideHeight = prompt.height
    test.width = 180
    tryCompare(setup, "width", 180)
    tryVerify(function() { return prompt.height > wideHeight })
    compare(prompt.wrapMode, TextEdit.Wrap)
    verify(prompt.contentWidth <= prompt.width + 1)
    for (var item of textItems(setup)) {
      if (!item.visible || item.wrapMode === Text.NoWrap) continue
      verify(item.width <= setup.width + 1)
      verify(item.contentWidth <= item.width + 1, "Guide text must wrap within its width")
    }
    compare(viewport.contentWidth, viewport.width)
  }

  function test_narrow_button_labels_fit() {
    openSetup()
    test.width = 180
    tryCompare(setup, "width", 180)
    wait(0)
    for (var name of ["setupEntry", "setupCopy", "setupDocs", "setupRefresh"]) {
      var button = findChild(setup, name)
      verify(button.width <= setup.width)
      for (var label of textItems(button)) {
        if (!label.visible) continue
        var left = label.mapToItem(button, 0, 0).x
        verify(left >= 0 && left + label.width <= button.width + 1,
          name + " label must fit its narrow button")
      }
    }
  }

  function test_setup_and_coach_are_mutually_exclusive() {
    service.demoMode = false
    var coach = findChild(keys, "garminPanelCoach")
    keyClick(Qt.Key_C)
    verify(coach.expanded)
    compare(service.calls, [{action: "checkCoach"}])
    setup.open()
    verify(setup.expanded && !coach.expanded)
    tryCompare(findChild(setup, "setupCopy"), "activeFocus", true)
    setup.copied = true
    coach.open()
    verify(coach.expanded && !setup.expanded && !setup.copied)
    compare(service.calls, [{action: "checkCoach"}, {action: "checkCoach"}])
    keyClick(Qt.Key_Escape)
    tryCompare(keys, "activeFocus", true)
    verify(!keys.blocked)
  }

  function test_panel_close_resets_setup() {
    var popup = null
    for (var item of panel.data)
      if (typeof item.fittedContentWidth === "function") popup = item
    verify(popup !== null)
    // Break the popup binding so only the controller lifecycle runs, not a layer surface.
    popup.open = false
    panel.controller.open = true
    openSetup()
    setup.copied = true
    panel.close()
    verify(!setup.expanded && !setup.copied)
    tryCompare(keys, "activeFocus", true)
    compare(service.calls, [{action: "ensureCharts"}])
  }
}
