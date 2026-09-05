import QtQuick
import qs.Ui as Ui
import "Model.js" as Model

Ui.BarWidget {
  id: root
  moduleName: "io.github.glavman.garmin-glance"
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property string metricKey: ["bodyBattery", "steps", "sleep", "hrv"].indexOf(setting("barMetric", "bodyBattery")) >= 0 ? setting("barMetric", "bodyBattery") : "bodyBattery"
  readonly property var metric: service && service.payload && service.payload.metrics ? service.payload.metrics[metricKey] : null
  readonly property string label: ({bodyBattery: "BB", steps: "Steps", sleep: "Sleep", hrv: "HRV"})[metricKey]
  readonly property bool degraded: !service || !!service.message || !service.payload || service.payload.status === "cached" || Model.stale(metricKey, metric, service.now, service.payload.fetchedAt)
  readonly property bool opened: popup.opened
  readonly property bool popoutSwitchClosing: popup.popoutSwitchClosing
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function open() { popup.open() }
  function close() { popup.close() }
  function toggle() { popup.toggle() }
  function closeForPopoutSwitch() { popup.closeForPopoutSwitch() }

  Ui.WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: (root.vertical ? "G" : (root.service && root.service.demoMode ? "Demo " : "") + root.label + " " + Model.format(root.metric)) + (root.degraded ? " *" : "")
    dimmed: root.degraded
    tooltipText: root.label + ": " + Model.format(root.metric)
      + (root.metric && root.metric.time ? "\nSample: " + root.metric.time : "\nNo measurement")
      + (root.service && root.service.message ? "\n" + root.service.message : "")
      + (root.service && root.service.payload && (root.service.payload.status === "cached" || root.service.now - Date.parse(root.service.payload.fetchedAt) > 3600000) ? "\nCached reading / not a live sync" : "")
      + "\nLeft: dashboard / Middle: refresh / *: stale, cached or unavailable"
    onPressed: function(code) {
      if (code === Qt.MiddleButton) { if (root.service) root.service.refresh(false) }
      else root.toggle()
    }
  }
  Panel {
    id: popup
    bar: root.bar
    moduleName: root.moduleName
    settings: root.settings
    anchorItem: button
    hostWidget: root
    service: root.service
  }
}
