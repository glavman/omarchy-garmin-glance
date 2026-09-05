import QtQuick
import "Model.js" as Model

Item {
  id: root
  property var payload: ({})
  property string modelOverride: ""
  property color ink: "white"
  property color accent: "white"
  property real textSize: 13
  property string fontFamily: "monospace"
  property real unit: 1
  property bool demoMode: false
  readonly property var device: Model.watchDevice(payload, modelOverride, demoMode)
  readonly property string watchStyle: Model.watchStyle(device.name)
  implicitHeight: Math.max(mark.height, heading.implicitHeight)
  Accessible.role: Accessible.StaticText
  Accessible.name: device.name

  WatchIcon {
    id: mark
    width: 32; height: 32
    anchors.verticalCenter: parent.verticalCenter
    ink: root.accent
    watchStyle: root.watchStyle
    Accessible.ignored: true
  }
  Text {
    id: heading
    x: mark.width + 10 * root.unit; width: Math.max(0, root.width - x)
    anchors.verticalCenter: parent.verticalCenter
    text: root.device.name; textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: root.ink; font.family: root.fontFamily; font.pixelSize: root.textSize; font.bold: true
  }
}
