import QtQuick
import qs.Commons

Rectangle {
  id: root
  property string title: ""
  property string unit: "score"
  property var samples: []
  property bool intraday: false
  property real endTime: Date.now()
  property real ceiling: 100
  property bool selected: false
  property int cursor: -1
  property color ink: Color.accent
  property color gridColor: Util.alpha(Color.popups.text, 0.14)
  signal activated()
  readonly property real startTime: endTime - 86400000
  readonly property var points: {
    var result = []
    for (var i = 0; i < samples.length; ++i) {
      var p = samples[i], t = p ? Date.parse(intraday ? p.time : p.date) : NaN
      if (!isFinite(t) || (intraday && (t < startTime || t > endTime))) continue
      result.push({ t: t, date: p.date, value: typeof p.value === "number" && isFinite(p.value) && p.value >= 0 && (ceiling !== 100 || p.value <= 100) ? p.value : null })
    }
    result.sort(function(a, b) { return a.t - b.t })
    return intraday || !result.length ? result : result.filter(function(p) { return p.t >= result[result.length - 1].t - 6 * 86400000 })
  }
  readonly property real maximum: ceiling > 0 ? ceiling : Math.max(1, ...points.map(function(p) { return p.value || 0 })) * 1.1
  readonly property bool hasValues: points.some(function(p) { return p.value !== null })
  readonly property string readout: {
    var p = points[cursor]
    if (!p) return hasValues ? "Hover to inspect / Left, Right when selected" : "No samples available"
    return (intraday ? Qt.formatDateTime(new Date(p.t), "yyyy-MM-dd HH:mm:ss") + " local" : p.date) + " / " + (p.value === null ? "Unavailable" : String(p.value) + " " + unit)
  }
  implicitHeight: heading.implicitHeight + inspection.implicitHeight + Style.space(intraday ? 174 : 134)
  radius: Style.cornerRadius; color: Style.normalFill
  border.width: 1; border.color: selected ? Color.accent : gridColor
  Accessible.role: Accessible.Chart
  Accessible.name: title + ". " + readout
  Accessible.focusable: true
  Accessible.focused: selected

  function pointX(index) {
    if (intraday) return (points[index].t - startTime) / 86400000 * plot.width
    var first = points.length ? points[points.length - 1].t - 6 * 86400000 : 0
    return ((points[index].t - first) / 86400000 + 0.5) / 7 * plot.width
  }
  function moveCursor(delta) {
    if (points.length) cursor = cursor < 0 ? (delta < 0 ? points.length - 1 : 0) : Math.max(0, Math.min(points.length - 1, cursor + delta))
  }
  onPointsChanged: { cursor = -1; plot.requestPaint() }
  onCursorChanged: plot.requestPaint()
  onMaximumChanged: plot.requestPaint()
  onInkChanged: plot.requestPaint()
  onGridColorChanged: plot.requestPaint()

  Text {
    id: heading
    x: Style.space(12); y: x; width: parent.width - x * 2
    text: root.title; textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(14, Style.font.title); font.bold: true
  }
  Text {
    id: inspection
    x: heading.x; y: heading.y + heading.height + Style.space(6); width: heading.width
    text: root.readout; textFormat: Text.PlainText; wrapMode: Text.Wrap
    color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
  }
  Canvas {
    id: plot
    x: Style.space(48); y: inspection.y + inspection.height + Style.space(12)
    width: Math.max(1, parent.width - x - Style.space(16)); height: parent.height - y - Style.space(30)
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d"); ctx.reset()
      ctx.strokeStyle = root.gridColor; ctx.lineWidth = 1
      for (var row = 0; row <= 2; ++row) {
        var gy = 2 + row / 2 * (height - 4)
        ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke()
      }
      var previous = null
      for (var i = 0; i < root.points.length; ++i) {
        var p = root.points[i]
        if (p.value === null) { previous = null; continue }
        var px = root.pointX(i), py = 2 + (1 - p.value / root.maximum) * (height - 4)
        ctx.strokeStyle = root.ink; ctx.fillStyle = root.ink; ctx.lineWidth = 2
        // Never bridge explicit nulls or an intraday sampling outage over 30 minutes.
        if (root.intraday) {
          if (previous && p.t - previous.t <= 1800000) {
            ctx.beginPath(); ctx.moveTo(previous.x, previous.y); ctx.lineTo(px, py); ctx.stroke()
          }
          ctx.beginPath(); ctx.arc(px, py, i === root.cursor ? 4 : 2, 0, Math.PI * 2); ctx.fill()
        } else {
          var bw = Math.max(2, width / 7 * 0.5)
          ctx.globalAlpha = i === root.cursor ? 1 : 0.65
          ctx.fillRect(px - bw / 2, py, bw, Math.max(2, height - 2 - py)); ctx.globalAlpha = 1
        }
        previous = { x: px, y: py, t: p.t }
      }
      if (root.cursor >= 0 && root.cursor < root.points.length) {
        ctx.strokeStyle = root.ink; ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(root.pointX(root.cursor), 0); ctx.lineTo(root.pointX(root.cursor), height); ctx.stroke()
      }
    }
    MouseArea {
      anchors.fill: parent; hoverEnabled: true
      onPositionChanged: function(mouse) {
        var closest = -1, distance = Infinity
        for (var i = 0; i < root.points.length; ++i) {
          var d = Math.abs(root.pointX(i) - mouse.x)
          if (d < distance) { closest = i; distance = d }
        }
        root.cursor = closest
      }
      onClicked: root.activated()
      onExited: if (!root.selected) root.cursor = -1
    }
  }
  Text {
    x: Style.space(6); y: plot.y; width: plot.x - x - Style.space(4)
    text: root.maximum >= 1000 ? (root.maximum / 1000).toFixed(1) + "k" : Math.ceil(root.maximum)
    horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
  }
  Text {
    x: Style.space(6); y: plot.y + plot.height - height; width: plot.x - x - Style.space(4)
    text: "0"; horizontalAlignment: Text.AlignRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
  }
  Text {
    x: plot.x; y: plot.y + plot.height + Style.space(6); width: plot.width
    text: root.intraday ? "24h ago" : root.points.length ? new Date(root.points[root.points.length - 1].t - 6 * 86400000).toISOString().slice(5, 10) : "7 days"
    elide: Text.ElideRight; color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
  }
  Text {
    anchors.right: plot.right; y: plot.y + plot.height + Style.space(6)
    text: root.intraday ? "Now" : root.points.length ? root.points[root.points.length - 1].date.slice(5) : ""
    color: Color.popups.text; font.family: Style.font.family; font.pixelSize: Math.max(12, Style.font.body)
  }
}
