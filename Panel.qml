pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

Ui.Panel {
  id: root
  manageIpc: false
  property Item anchorItem: null
  property var hostWidget: null
  property var service: null
  property string historyKey: "steps"
  property int selectedChart: 0
  readonly property var payload: service && service.payload && service.payload.schemaVersion === 1 ? service.payload : ({})
  readonly property var metrics: payload.metrics || ({})
  readonly property var charts: payload.charts || ({})
  readonly property bool busy: !!service && service.busy
  readonly property real now: service ? service.now : Date.now()
  readonly property bool cachedReading: payload.status === "cached" || (!!payload.fetchedAt && now - Date.parse(payload.fetchedAt) > 3600000)
  readonly property bool staleSamples: {
    var names = ["bodyBattery", "steps", "sleep", "hrv"]
    for (var i = 0; i < names.length; i++)
      if (Model.stale(names[i], metrics[names[i]], now, payload.fetchedAt)) return true
    return false
  }
  readonly property real stepGoal: { var n = Number(setting("stepGoal", 10000)); return isFinite(n) && n > 0 ? n : 10000 }
  readonly property string statusText: {
    var parts = []
    if (service && service.demoMode) parts.push("DEMO / synthetic data")
    if (!service) parts.push("Service unavailable")
    else if (service.payload && service.payload.schemaVersion !== 1) parts.push("Unsupported data version")
    else if (payload.status === "error" || payload.error) parts.push("Connection / " + (Model.errorMessage(payload.error) || "unavailable"))
    else if (!payload.fetchedAt) parts.push("Waiting for first sync")
    if (payload.fetchedAt && (staleSamples || payload.status === "partial")) parts.push("Some samples are stale or unavailable")
    if (cachedReading) parts.push("Cached reading / not a live sync")
    if (busy) parts.push("Refreshing...")
    if (service && service.message) parts.push(service.message)
    return parts.length ? parts.join(" / ") : "Connected / latest available samples"
  }
  function stamp(value) {
    return value && isFinite(Date.parse(value)) ? Qt.formatDateTime(new Date(value), "yyyy-MM-dd HH:mm") + " local" : "not yet fetched"
  }
  function selectChart(index) {
    selectedChart = index
    var chart = index === 0 ? battery : history
    scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, chart.y))
  }
  onOpenedChanged: if (opened && service) service.ensureCharts()
  onServiceChanged: if (opened && service) service.ensureCharts()
  function switchPanel(direction) {
    return bar && typeof bar.switchPanelFrom === "function" ? bar.switchPanelFrom(hostWidget || root, direction) : false
  }

  Ui.KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem; bar: root.bar; owner: root.hostWidget || root
    open: root.opened; focusTarget: keys
    contentWidth: fittedContentWidth(Style.space(560))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(740))
    Ui.PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (dx) (root.selectedChart === 0 ? battery : history).moveCursor(dx)
        if (dy) scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, scroll.contentY + dy * Style.space(60)))
      }
      onTextKey: function(text) {
        var key = text.toLowerCase()
        if (key === "r" && root.service && !root.busy) root.service.refresh(true)
        if (key === "g" && root.service) root.service.openGrafana()
        if (key === "b") root.selectChart(0)
        if (key === "s") { root.historyKey = root.historyKey === "steps" ? "sleep" : "steps"; root.selectChart(1) }
      }
      Flickable {
        id: scroll
        anchors.fill: parent; clip: true
        contentWidth: width; contentHeight: content.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }
        Column {
          id: content
          width: scroll.width; spacing: Style.space(12)
          Text {
            text: "GARMIN GLANCE"; color: Color.accent; font.family: Style.font.family
            font.pixelSize: Math.max(13, Style.font.subtitle); font.letterSpacing: 2; font.bold: true
          }
          Text {
            width: parent.width; text: "Daily overview"; wrapMode: Text.Wrap
            color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(26, Style.font.displayLarge)
          }
          Flow {
            width: parent.width; spacing: Style.space(8)
            Ui.Button {
              text: root.busy ? "Refreshing..." : "Refresh"; enabled: !!root.service && !root.busy
              bordered: true; fontSize: Math.max(13, Style.font.body); tooltipText: "Refresh metrics and charts (R)"
              opacity: enabled ? 1 : 0.5; onClicked: root.service.refresh(true)
              Accessible.role: Accessible.Button; Accessible.name: "Refresh (R)"
            }
            Ui.Button {
              text: "Grafana"; enabled: !!root.service; bordered: true
              fontSize: Math.max(13, Style.font.body); tooltipText: "Open Grafana (G)"
              onClicked: root.service.openGrafana()
              Accessible.role: Accessible.Button; Accessible.name: "Open Grafana (G)"
            }
            Ui.PanelActionButton {
              iconText: "X"; tooltipText: "Close (Escape)"; size: Style.space(34); onClicked: root.close()
              Accessible.role: Accessible.Button; Accessible.name: "Close (Escape)"
            }
          }
          Text {
            width: parent.width; text: root.statusText; textFormat: Text.PlainText; wrapMode: Text.Wrap
            color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
          }
          Grid {
            id: cards
            width: parent.width; columns: width < Style.space(430) ? 1 : 2; spacing: Style.space(10)
            Repeater {
              model: [{key: "bodyBattery", title: "Body battery"}, {key: "steps", title: "Steps"}, {key: "sleep", title: "Sleep score"}, {key: "hrv", title: "Overnight HRV"}]
              MetricCard {
                required property var modelData
                width: (cards.width - (cards.columns - 1) * cards.spacing) / cards.columns
                title: modelData.title; metric: root.metrics[modelData.key] || null
                stale: Model.stale(modelData.key, metric, root.now, root.payload.fetchedAt)
                cachedReading: root.cachedReading
                detail: modelData.key === "steps" ? "Personal goal: " + root.stepGoal.toLocaleString(Qt.locale(), 'f', 0) : modelData.key === "bodyBattery" ? "Garmin scale / 0 to 100" : modelData.key === "sleep" ? "Latest recorded night" : "Overnight average"
              }
            }
          }
          Chart {
            id: battery
            width: parent.width; title: "Body battery / last 24 hours"; intraday: true
            samples: root.charts.bodyBattery || []; endTime: root.now
            selected: root.selectedChart === 0; onActivated: root.selectedChart = 0
          }
          Flow {
            width: parent.width; spacing: Style.space(8)
            Repeater {
              model: [{key: "steps", title: "Steps / 7 days"}, {key: "sleep", title: "Sleep / 7 days"}]
              Ui.Button {
                required property var modelData
                text: modelData.title; selected: root.historyKey === modelData.key
                fontSize: Math.max(13, Style.font.body); bordered: true; tooltipText: "Switch history (S); body battery (B)"
                onClicked: { root.historyKey = modelData.key; root.selectChart(1) }
                Accessible.role: Accessible.Button; Accessible.name: text
              }
            }
          }
          Chart {
            id: history
            width: parent.width; title: root.historyKey === "steps" ? "Daily steps" : "Nightly sleep score"
            samples: root.charts[root.historyKey] || []; ceiling: root.historyKey === "steps" ? 0 : 100
            unit: root.historyKey === "steps" ? "steps" : "score"
            selected: root.selectedChart === 1; onActivated: root.selectedChart = 1
          }
          Text {
            width: parent.width
            text: "Database read: " + root.stamp(root.payload.fetchedAt) + "\nCharts: " + root.stamp(root.payload.chartsFetchedAt)
              + (root.payload.chartsFetchedAt && root.now - Date.parse(root.payload.chartsFetchedAt) > 3600000 ? " (over 1 hour old)" : "")
              + "\nMetric dates: " + (root.payload.timezone || "source timezone unknown") + ". Times: desktop local."
              + "\nR refresh / G Grafana / Esc close / Tab panel\nB body battery / S history / Left, Right inspect / Up, Down scroll"
            textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Color.popups.text; opacity: 0.8
            font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
          }
        }
      }
    }
  }
}
