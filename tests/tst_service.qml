import QtQuick
import QtTest
import ".." as Garmin
import "../Model.js" as Model

TestCase {
  id: test
  name: "Service"
  when: windowShown
  Component { id: serviceComponent; Garmin.Service {} }
  property var service: null
  property var worker: null
  property var coachWorker: null
  property var commands: []
  property var replies: []
  property int coachCommands: 0
  property bool delayCoach: false
  QtObject {
    id: shell
    property var shellConfig: ({plugins: [{demoMode: false, grafanaUrl: "invalid"}]})
  }
  QtObject {
    id: registry
    function findEntryLocation(config, id) { return {found: true, kind: "plugin", index: 0} }
  }
  Connections {
    target: test.worker
    function onCommandChanged() {
      var args = test.worker.command
      if (args.length < 3 || !args[1].endsWith("/backend.py")) return
      test.commands = test.commands.concat([Array.from(args).slice(2)])
      var reply = test.replies.length ? test.replies[0] : {text: "", exit: 1}
      test.replies = test.replies.slice(1)
      // Replace before running is set: never execute a real helper or read user config.
      test.worker.command = ["/usr/bin/python3", "-c", "import sys,time; "
        + (reply.delay ? "time.sleep(2); " : "") + "sys.stdout.write("
        + JSON.stringify(reply.text) + "); sys.exit(" + (reply.exit || 0) + ")"]
    }
  }
  Connections {
    target: test.coachWorker
    function onCommandChanged() {
      var args = test.coachWorker.command
      if (args.length < 3 || !args[1].endsWith("/coach.py")) return
      test.coachCommands++
      test.coachWorker.command = ["/usr/bin/python3", "-c",
        (test.delayCoach ? "import time; time.sleep(2); " : "")
        + "print('{\"schemaVersion\":1,\"status\":\"ok\",\"error\":null,\"agent\":\"grok\"}')"]
    }
  }
  function fixture(status, error) {
    var data = {schemaVersion: 1, status: status, error: error || null,
      fetchedAt: "2026-09-05T10:00:00Z", timezone: "UTC", chartsFetchedAt: null,
      metrics: {}, charts: {bodyBattery: [], steps: [], sleep: []}}
    var units = {bodyBattery: "score", steps: "steps", sleep: "score", hrv: "ms"}
    for (var key in units)
      data.metrics[key] = {value: null, time: null, date: null, state: "missing", unit: units[key], expiresAt: null}
    verify(Model.valid(data))
    return data
  }
  function enqueue(status, error) {
    replies = replies.concat([{text: JSON.stringify(fixture(status, error)), exit: status === "error" ? 1 : 0}])
  }
  function stopTimers() {
    for (var i = 0; i < service.data.length; i++)
      if (typeof service.data[i].stop === "function") service.data[i].stop()
  }
  function init() {
    commands = []; replies = []; coachCommands = 0; delayCoach = false
    shell.shellConfig = {plugins: [{demoMode: false, grafanaUrl: "invalid"}]}
    service = createTemporaryObject(serviceComponent, test, {shell: shell, manifest: {id: "synthetic"}, pluginRegistry: registry})
    verify(service !== null)
    stopTimers()
    for (var i = 0; i < service.data.length; i++) {
      var object = service.data[i]
      if (typeof object.write === "function") {
        if (!coachWorker) coachWorker = object
        else worker = object
      }
    }
    verify(worker !== null && coachWorker !== null)
  }
  function cleanup() {
    stopTimers()
    verify(!service.busy && !service.coachBusy)
    worker = null; coachWorker = null; service = null
  }
  function settled(count) {
    tryVerify(function() { return commands.length === count && !service.busy }, 3000)
    wait(350) // Cross the startup debounce to detect accidental mode-reset loops.
    compare(commands.length, count)
    verify(!service.busy)
  }
  function blocked() {
    verify(service.actionsBlocked)
    service.openGrafana()
    verify(/unavailable|Waiting/.test(service.message))
    service.openGrafana({key: "steps", kind: "metric"})
    verify(/unavailable|Waiting/.test(service.message))
    // Invalid ID also keeps a guard regression from opening an external browser.
    service.openActivity("invalid")
    verify(/unavailable|Waiting/.test(service.message))
    service.coachAgent = "grok"
    verify(!service.checkCoach())
    verify(!service.launchCoach("day", 7, 10000, "grok"))
    verify(!service.clearCoach())
    verify(!service.coachExecute("check", null))
    compare(coachCommands, 0)
  }
  function test_initial_and_auto_demo_guards_and_flags() {
    blocked()
    enqueue("demo")
    service.reset()
    settled(1)
    compare(commands[0], ["cache", "--charts", "--auto-demo"])
    compare(service.requestedDemoMode, false)
    compare(service.demoMode, true)
    compare(service.initializing, false)
    blocked()
    enqueue("demo")
    service.refresh(true)
    settled(2)
    compare(commands[1], ["fetch", "--charts", "--auto-demo"])
    compare(service.failures, 0)
  }
  function test_auto_demo_transitions_to_live_without_reset() {
    enqueue("demo")
    service.reset()
    settled(1)
    enqueue("ok")
    service.refresh(false)
    settled(2)
    compare(commands[1], ["fetch", "--auto-demo"])
    compare(service.demoMode, false)
    compare(service.actionsBlocked, false)
    compare(service.payload.status, "ok")
    verify(service.checkCoach())
    tryCompare(service, "coachBusy", false, 3000)
    compare(coachCommands, 1)
    compare(service.coachAgent, "grok")
  }
  function test_real_error_replaces_demo_but_preserves_live_snapshot() {
    enqueue("demo")
    service.reset()
    settled(1)
    enqueue("error", "auth_error")
    service.refresh(false)
    settled(2)
    compare(service.payload.status, "error")
    compare(service.payload.error, "auth_error")
    compare(service.demoMode, false)
    compare(service.message, Model.errorMessage("auth_error"))
    compare(service.failures, 1)
    enqueue("ok")
    service.refresh(false)
    settled(3)
    enqueue("error", "network_error")
    service.refresh(false)
    settled(4)
    compare(service.payload.status, "ok")
    compare(service.message, Model.errorMessage("network_error"))
  }
  function test_unusable_transition_discards_synthetic_payload() {
    for (var row of [{text: "not json"}, {text: ""}, {text: "", delay: true}]) {
      enqueue("demo")
      service.reset()
      settled(commands.length)
      replies = [row]
      service.refresh(false)
      if (row.delay) {
        tryVerify(function() { return worker.processId > 0 })
        for (var i = 0; i < service.data.length; i++)
          if (service.data[i].interval === 15000) service.data[i].triggered()
      }
      settled(commands.length)
      compare(service.payload, null)
      compare(service.demoMode, false)
      verify(service.message.indexOf("No data available") >= 0)
      blocked()
    }
  }
  function test_configured_startup_errors_are_not_demo() {
    enqueue("error", "invalid_config")
    enqueue("error", "invalid_config")
    service.reset()
    settled(2)
    compare(commands, [["cache", "--charts", "--auto-demo"], ["fetch", "--auto-demo"]])
    compare(service.payload.status, "error")
    compare(service.demoMode, false)
    compare(service.message, Model.errorMessage("invalid_config"))
  }
  function test_live_startup_then_auto_demo_cancels_coach() {
    enqueue("cached")
    enqueue("ok")
    service.reset()
    settled(2)
    compare(service.payload.status, "ok")
    delayCoach = true
    verify(service.checkCoach())
    tryVerify(function() { return coachWorker.processId > 0 })
    enqueue("demo")
    service.refresh(false)
    settled(3)
    tryCompare(service, "coachBusy", false, 3000)
    compare(service.coachAgent, "")
    compare(service.coachMessage, "")
    verify(service.actionsBlocked)
    verify(!service.checkCoach())
    compare(coachCommands, 1)
  }
  function test_requested_demo_and_switch_back_to_auto() {
    shell.shellConfig = {plugins: [{demoMode: true}]}
    stopTimers()
    enqueue("demo")
    service.reset()
    settled(1)
    compare(commands[0], ["fetch", "--charts", "--demo"])
    blocked()
    enqueue("demo")
    shell.shellConfig = {plugins: [{demoMode: false}]}
    settled(2)
    compare(commands[1], ["cache", "--charts", "--auto-demo"])
    compare(service.requestedDemoMode, false)
    compare(service.demoMode, true)
  }
}
