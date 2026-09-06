import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model
import "Grafana.js" as Grafana

Item {
  id: root
  property var shell: null
  property var manifest: null
  property var pluginRegistry: null
  property var payload: null
  property string message: ""
  property real now: Date.now()
  property bool pendingCharts: false
  property bool wantCharts: false
  property bool requestCharts: false
  property bool initializing: true
  property bool restartPending: false
  property bool accepted: false
  property bool timedOut: false
  property int failures: 0
  readonly property bool busy: worker.running
  readonly property var settings: {
    var config = shell ? shell.shellConfig : null
    if (!config || !manifest || !pluginRegistry) return ({})
    var loc = pluginRegistry.findEntryLocation(config, manifest.id)
    if (!loc.found) return ({})
    return loc.kind === "bar" ? config.bar.layout[loc.section][loc.index] : loc.kind === "plugin" ? config.plugins[loc.index] : ({})
  }
  readonly property bool requestedDemoMode: settings.demoMode === true
  readonly property bool demoMode: requestedDemoMode || (!!payload && payload.status === "demo")
  readonly property bool actionsBlocked: demoMode || !payload
  readonly property int refreshMinutes: Math.max(1, Math.min(60, Number(settings.refreshMinutes) || 5))

  property string coachOperation: ""
  property string coachAgent: ""
  property string coachMessage: ""
  property string coachInput: ""
  property var coachResult: null
  property string coachOutput: ""
  readonly property bool coachBusy: coachOperation !== "" || coachWorker.running

  function coachError(code) {
    switch (code) {
    case "agent_unavailable": return "The default agent is not available. Install it, then check again."
    case "agent_not_configured": return "Choose a default agent in Omarchy, then check again."
    case "agent_unsupported": return "The default agent is not supported. Choose OpenCode, Claude, Codex or Grok."
    case "agent_changed": return "The default agent changed. Check again and review consent before opening."
    case "source_changed": return "The data source changed. Review the connection and approve a new coaching session."
    case "launch_failed": return "The terminal launcher failed. Check your terminal and agent setup."
    case "invalid_arguments": return "The coaching request is invalid. Review your selections and try again."
    case "session_error": return "Coaching files could not be prepared or removed. Check local file permissions."
    case "session_limit": return "The coaching file limit was reached. Clear coaching files before trying again."
    case "session_busy": return "Another coaching request is active. Try again shortly."
    case "no_data": return "No supported wellbeing or activity data was found in this window. Check your connection or choose a longer window."
    case "data_unavailable": return "Coaching data could not be retrieved. Check the connection and try again."
    case "invalid_config": return "The data connection configuration is invalid. Check the plugin setup."
    case "auth_error": return "The data connection was not authorized. Check the plugin credentials."
    case "network_error": return "The data source could not be reached. Check the connection and try again."
    case "timeout": return "The coaching request timed out. No agent readiness or completion is confirmed."
    case "ambiguous_source": return "More than one data source matched. Configure a single source before trying again."
    case "truncated_response": return "The data response was incomplete. No coaching launch is confirmed."
    case "query_error": return "The coaching data query failed. Check the data source setup."
    case "invalid_response": return "The coaching helper returned an invalid response."
    case "response_too_large": return "The coaching response exceeded the size limit."
    default: return "The coaching request failed. No coaching launch is confirmed."
    }
  }
  function coachExecute(command, input) {
    if (actionsBlocked || coachBusy) return false
    coachOperation = command
    coachInput = input ? JSON.stringify(input) + "\n" : ""
    coachResult = null
    coachOutput = ""
    coachMessage = command === "check" ? "Checking the default agent locally..."
      : command === "clear" ? "Clearing plugin-owned coaching files..." : "Preparing data and requesting the terminal launcher..."
    coachWorker.command = ["/usr/bin/python3", decodeURIComponent(Qt.resolvedUrl("coach.py").toString().replace(/^file:\/\//, "")), command]
    coachWorker.stdinEnabled = command === "launch"
    coachWatchdog.restart()
    coachWorker.running = true
    return true
  }
  function checkCoach() {
    if (actionsBlocked || coachBusy) return false
    coachAgent = ""
    return coachExecute("check", null)
  }
  function launchCoach(intent, days, stepGoal, agent) {
    if (actionsBlocked || coachBusy || ["opencode", "claude", "codex", "grok"].indexOf(agent) < 0 || agent !== coachAgent
        || ["day", "week", "question"].indexOf(intent) < 0 || [7, 30, 90].indexOf(days) < 0
        || typeof stepGoal !== "number" || !isFinite(stepGoal) || stepGoal <= 0) return false
    return coachExecute("launch", {intent: intent, days: days, stepGoal: stepGoal, agent: agent})
  }
  function clearCoach() { return coachExecute("clear", null) }
  function finishCoach(exitCode, exitStatus) {
    if (!coachOperation) return
    coachWatchdog.stop()
    var operation = coachOperation
    var result = coachResult
    if (!result && !actionsBlocked) {
      try {
        var response = JSON.parse(coachOutput)
        if (response && response.schemaVersion === 1 && ["ok", "error"].indexOf(response.status) >= 0
            && (response.status === "ok" ? response.error === null : typeof response.error === "string" && response.error.length > 0)
            && (operation !== "check" || (typeof response.agent === "string"
                && (response.status === "ok" ? ["opencode", "claude", "codex", "grok"] : ["", "opencode", "claude", "codex", "grok"]).indexOf(response.agent) >= 0)))
          result = response
      } catch (error) { /* Only fixed contract errors reach the UI. */ }
    }
    coachOperation = ""
    coachInput = ""
    coachOutput = ""
    coachResult = null
    if (actionsBlocked) { coachAgent = ""; coachMessage = ""; return }
    if (operation === "check" || operation === "launch") coachAgent = ""
    if (!result) { coachMessage = coachError("invalid_response"); return }
    if (result.status === "error") { coachMessage = coachError(result.error); return }
    if (exitCode !== 0 || exitStatus !== 0) { coachMessage = coachError("launch_failed"); return }
    if (operation === "check") {
      coachAgent = result.agent
      coachMessage = "Default agent detected locally. No health data sent."
    } else if (operation === "clear") {
      coachMessage = "Plugin-owned coaching files cleared. Agent chat history was not deleted."
    } else {
      coachMessage = "Agent launch requested. Agent readiness, data loading and answer completion are not confirmed."
    }
  }
  Timer {
    id: coachWatchdog
    interval: 35000
    onTriggered: {
      root.coachResult = {status: "error", error: "timeout"}
      // Never signal PID 0 if process startup failed.
      if (coachWorker.processId > 0) coachWorker.signal(9)
      root.finishCoach(-1, 1)
    }
  }
  Process {
    id: coachWorker
    onStarted: {
      if (root.actionsBlocked || !root.coachOperation) { signal(9); return }
      if (root.coachOperation === "launch") {
        write(root.coachInput)
        root.coachInput = ""
        stdinEnabled = false // Flush the queued JSON, then deliver EOF to json.load(stdin).
      }
    }
    // No stderr parser: helper diagnostics are discarded, never displayed or logged here.
    stdout: SplitParser {
      // Empty delimiter delivers chunks without retaining a previous stream or an unbounded line.
      splitMarker: ""
      onRead: function(data) {
        if (!root.coachOperation || root.actionsBlocked) return
        if (root.coachOutput.length + data.length > 4096) {
          root.coachResult = {status: "error", error: "response_too_large"}
          if (coachWorker.processId > 0) coachWorker.signal(9)
          root.finishCoach(-1, 1)
        } else root.coachOutput += data
      }
    }
    onExited: function(exitCode, exitStatus) { root.finishCoach(exitCode, exitStatus) }
  }

  function execute(command, charts) {
    accepted = false
    timedOut = false
    requestCharts = charts
    var args = ["/usr/bin/python3", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, "")), command]
    if (charts) args.push("--charts")
    if (requestedDemoMode && command === "fetch") args.push("--demo")
    else if (command === "cache" || command === "fetch") args.push("--auto-demo")
    worker.command = args
    worker.running = true
  }
  function refresh(charts) {
    wantCharts = wantCharts || charts
    if (busy) { pendingCharts = pendingCharts || charts; return }
    execute("fetch", wantCharts)
  }
  function ensureCharts() {
    wantCharts = true
    if (busy && !requestCharts) { pendingCharts = true; return }
    if (!payload || !payload.historyFetchedAt || now - Date.parse(payload.historyFetchedAt) > refreshMinutes * 60000
        || !payload.activities || !payload.activitiesFetchedAt
        || now - Date.parse(payload.activitiesFetchedAt) > refreshMinutes * 60000 || now >= payload.activities.to)
      refresh(true)
  }
  function reset() {
    payload = null
    message = ""
    failures = 0
    pendingCharts = false
    initializing = !requestedDemoMode
    if (busy) { restartPending = true; worker.signal(9) }
    else execute(initializing ? "cache" : "fetch", true)
  }
  function openGrafana(context) {
    if (actionsBlocked) {
      message = demoMode ? "Grafana links are unavailable for demo data." : "Waiting for the data source before opening links."
      return
    }
    var link = Grafana.build(String(settings.grafanaUrl || "http://127.0.0.1:3000"), payload, context)
    if (link.error) { message = link.error; return }
    message = ""
    Quickshell.execDetached(["/usr/bin/xdg-open", link.url])
  }
  function openActivity(id) {
    if (actionsBlocked) {
      message = demoMode ? "Activity links are unavailable for demo data." : "Waiting for the data source before opening links."
      return
    }
    var url = Model.activityUrl(id)
    if (!url) { message = "This activity has no valid Garmin Connect ID. Refresh to try again."; return }
    message = ""
    Quickshell.execDetached(["/usr/bin/xdg-open", url])
  }
  onActionsBlockedChanged: {
    coachAgent = ""
    coachMessage = ""
    if (actionsBlocked && coachOperation) {
      if (coachWorker.processId > 0) coachWorker.signal(9)
      finishCoach(-1, 1)
    }
  }
  onRequestedDemoModeChanged: if (shell) startup.restart()
  Component.onCompleted: startup.start()
  Timer { id: startup; interval: 250; onTriggered: root.reset() }
  Timer { interval: 60000; running: true; repeat: true; onTriggered: root.now = Date.now() }
  Timer {
    interval: Math.min(3600000, root.refreshMinutes * 60000 * Math.pow(2, root.failures))
    running: !root.busy && !startup.running
    repeat: true
    onTriggered: root.refresh(root.wantCharts)
  }
  Timer {
    interval: 15000; running: root.busy
    onTriggered: { root.timedOut = true; worker.signal(9) }
  }
  Process {
    id: worker
    stdout: StdioCollector {
      onStreamFinished: {
        if (root.restartPending || root.timedOut) return
        try {
          if (text.length > 1048576) throw new Error("size")
          var result = JSON.parse(text)
          if (!Model.valid(result)) throw new Error("contract")
          root.accepted = true
          // Auto demo needs no immediate live retry; the normal refresh rechecks config.
          if (result.status === "demo") root.initializing = false
          if (root.initializing && result.status === "error") return
          // Keep a usable in-memory snapshot if even the backend cache is unavailable.
          // Synthetic values must never survive a failed transition to a real source.
          if (result.status !== "error" || !root.payload || root.payload.status === "demo") root.payload = result
          root.message = Model.errorMessage(result.error)
          root.failures = result.error ? Math.min(root.failures + 1, 4) : 0
        } catch (error) {
          root.message = "The data helper returned an invalid response."
        }
      }
    }
    onExited: {
      root.now = Date.now()
      if (root.restartPending) { root.restartPending = false; Qt.callLater(root.reset); return }
      if (!root.accepted && !root.initializing) {
        if (!root.requestedDemoMode && root.payload && root.payload.status === "demo") root.payload = null
        root.message = (root.timedOut ? "Database request timed out." : "Data helper failed.")
          + (root.payload ? " Showing last available data." : " No data available.")
        root.failures = Math.min(root.failures + 1, 4)
      }
      if (root.initializing) { root.initializing = false; Qt.callLater(function() { root.refresh(root.wantCharts) }) }
      else if (root.pendingCharts) { root.pendingCharts = false; Qt.callLater(function() { root.refresh(true) }) }
    }
  }
  IpcHandler {
    target: "garmin-glance"
    function refresh(): void { root.refresh(root.wantCharts) }
    function status(): string {
      return JSON.stringify({version: "1.1.0", busy: root.busy, demo: root.demoMode,
        status: root.payload ? root.payload.status : "loading", error: root.payload ? root.payload.error : null,
        message: root.message, chartsLoaded: !!root.payload && !!root.payload.chartsFetchedAt,
        historyLoaded: !!root.payload && !!root.payload.historyFetchedAt,
        activityAvailable: !!root.payload && !!root.payload.latestActivity,
        activitiesLoaded: !!root.payload && !!root.payload.activities,
        activitiesError: root.payload ? root.payload.activitiesError : null,
        activityError: root.payload ? root.payload.activityError : null,
        historyError: root.payload ? root.payload.historyError : null,
        wellnessError: root.payload ? root.payload.wellnessError : null,
        supplementalHistoryError: root.payload ? root.payload.supplementalHistoryError : null,
        stressError: root.payload ? root.payload.stressError : null})
    }
  }
}
