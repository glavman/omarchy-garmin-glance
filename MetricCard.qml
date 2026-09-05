import QtQuick
import qs.Commons

Rectangle {
  id: root
  property string title: ""
  property var metric: null
  property bool stale: true
  property bool cachedReading: false
  property string detail: ""
  readonly property bool available: !!metric && metric.state !== "missing" && typeof metric.value === "number" && isFinite(metric.value)
  readonly property string valueText: metric && available ? metric.value.toLocaleString(Qt.locale(), 'f', metric.unit === "ms" ? 1 : 0) : "--"
  readonly property string stamp: !metric ? "No sample" : metric.date || (metric.time && isFinite(Date.parse(metric.time)) ? Qt.formatDateTime(new Date(metric.time), "yyyy-MM-dd HH:mm") + " local" : "No sample date")
  implicitHeight: content.implicitHeight + Style.space(24)
  radius: Style.cornerRadius
  color: Style.normalFill
  border.width: 1
  border.color: Util.alpha(Color.popups.text, 0.12)
  Accessible.role: Accessible.StaticText
  Accessible.name: title + ": " + valueText + " " + (metric && available ? metric.unit : "unavailable") + (available && stale ? ", stale" : "") + (cachedReading ? ", cached reading" : "") + ", " + stamp

  Column {
    id: content
    x: Style.space(12); y: x
    width: parent.width - x * 2
    spacing: Style.space(5)
    Text {
      width: parent.width; text: root.title; textFormat: Text.PlainText
      color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(13, Style.font.subtitle)
      elide: Text.ElideRight
    }
    Text {
      width: parent.width; text: root.valueText + (root.metric && root.available ? " " + root.metric.unit : "")
      textFormat: Text.PlainText; elide: Text.ElideRight
      color: root.available ? Color.accent : Color.popups.text
      font.family: Style.font.family; font.pixelSize: Math.max(24, Style.font.display); font.bold: true
    }
    Text {
      width: parent.width; text: (root.available ? (root.stale ? "Stale / " : "") : "Unavailable / ") + (root.cachedReading ? "Cached reading / " : "") + root.stamp
      textFormat: Text.PlainText; wrapMode: Text.Wrap
      color: Color.popups.text; opacity: 0.8; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
    }
    Text {
      width: parent.width; visible: text !== ""; text: root.detail; textFormat: Text.PlainText; wrapMode: Text.Wrap
      color: Color.popups.text; opacity: 0.8; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
    }
  }
}
