import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

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
  readonly property bool demoMode: settings.demoMode === true
  readonly property int refreshMinutes: Math.max(1, Math.min(60, Number(settings.refreshMinutes) || 5))

  function execute(command, charts) {
    accepted = false
    timedOut = false
    requestCharts = charts
    var args = ["/usr/bin/python3", decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, "")), command]
    if (charts) args.push("--charts")
    if (demoMode && command === "fetch") args.push("--demo")
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
    if (!payload || !payload.historyFetchedAt || now - Date.parse(payload.historyFetchedAt) > refreshMinutes * 60000)
      refresh(true)
  }
  function reset() {
    payload = null
    message = ""
    failures = 0
    pendingCharts = false
    initializing = !demoMode
    if (busy) { restartPending = true; worker.signal(9) }
    else execute(initializing ? "cache" : "fetch", true)
  }
  function openGrafana() {
    var url = String(settings.grafanaUrl || "http://127.0.0.1:3000")
    if (!/^https?:\/\/[^\s/@]+(?::[0-9]+)?(?:[/?#][^\s]*)?$/.test(url)) {
      message = "Set a valid http(s) Grafana URL in bar settings."
      return
    }
    Quickshell.execDetached(["/usr/bin/xdg-open", url])
  }
  onDemoModeChanged: if (shell) startup.restart()
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
          if (root.initializing && result.status === "error") return
          // Keep a usable in-memory snapshot if even the backend cache is unavailable.
          if (result.status !== "error" || !root.payload) root.payload = result
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
        root.message = root.timedOut ? "Database request timed out. Showing last available data." : "Data helper failed. Showing last available data."
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
      return JSON.stringify({version: "1.0.0", busy: root.busy, demo: root.demoMode,
        status: root.payload ? root.payload.status : "loading", error: root.payload ? root.payload.error : null,
        message: root.message, chartsLoaded: !!root.payload && !!root.payload.chartsFetchedAt,
        historyLoaded: !!root.payload && !!root.payload.historyFetchedAt,
        activityAvailable: !!root.payload && !!root.payload.latestActivity,
        activityError: root.payload ? root.payload.activityError : null,
        historyError: root.payload ? root.payload.historyError : null,
        wellnessError: root.payload ? root.payload.wellnessError : null,
        supplementalHistoryError: root.payload ? root.payload.supplementalHistoryError : null,
        stressError: root.payload ? root.payload.stressError : null})
    }
  }
}
