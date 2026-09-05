import QtQuick
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

Ui.BarWidget {
  id: root
  moduleName: "io.github.glavman.garmin-glance"
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
  readonly property bool degraded: {
    if (!service || !!service.message || !service.payload || ["cached", "error", "partial"].indexOf(service.payload.status) >= 0) return true
    var metrics = service.payload.metrics || {}
    return ["steps", "bodyBattery", "sleep"].some(function(key) { return Model.stale(key, metrics[key], service.now, service.payload.fetchedAt) })
  }
  readonly property bool opened: popup.opened
  readonly property bool popoutSwitchClosing: popup.popoutSwitchClosing
  readonly property var device: Model.watchDevice(service ? service.payload : null, setting("watchModel", ""), !!service && service.demoMode)
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function open() { popup.open() }
  function close() { popup.close() }
  function toggle() { popup.toggle() }
  function closeForPopoutSwitch() { popup.closeForPopoutSwitch() }

  Ui.BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    dimmed: root.degraded
    tooltipText: Model.tooltip(root.service ? root.service.payload : null, root.service ? root.service.now : Date.now())
      + (root.service && root.service.message ? "\n" + root.service.message : "")
    onPressed: function(code) {
      if (code === Qt.MiddleButton) { if (root.service) root.service.refresh(false) }
      else root.toggle()
    }
    Accessible.role: Accessible.Button
    Accessible.name: tooltipText
    iconComponent: WatchIcon {
      ink: button.foreground; watchStyle: Model.watchStyle(root.device.name)
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
