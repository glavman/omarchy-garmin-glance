import QtQuick
import qs.Commons

Item {
  id: root
  property var batterySamples: []
  property var stressSamples: []
  property real endTime: Date.now()
  property real startTime: endTime - 86400000
  property bool cached: false
  property string notice: ""
  property bool selected: false
  property real cursorTime: NaN
  property color ink: Color.accent
  property color foreground: Color.popups.text
  readonly property color stressInk: Util.alpha(foreground, 0.28)
  readonly property color gridColor: Util.alpha(foreground, 0.12)
  readonly property bool validRange: isFinite(startTime) && isFinite(endTime)
    && isFinite(new Date(startTime).getTime()) && isFinite(new Date(endTime).getTime())
    && endTime > startTime
  readonly property bool inspecting: validRange && isFinite(cursorTime) && cursorTime >= startTime && cursorTime <= endTime
  readonly property var batteryPoints: points(batterySamples)
  readonly property var stressPoints: points(stressSamples)
  readonly property bool hasValues: batteryPoints.some(function(p) { return p.value !== null })
    || stressPoints.some(function(p) { return p.value !== null })
  readonly property string readout: {
    if (!inspecting) return hasValues ? "Hover to inspect / B selects chart" : "No samples available"
    var battery = nearest(batteryPoints), stress = nearest(stressPoints)
    return Qt.formatDateTime(new Date(cursorTime), "HH:mm") + " local / Battery "
      + (battery && battery.value !== null ? battery.value : "--") + " / Stress "
      + (stress && stress.value !== null ? stress.value : "--")
  }
  signal activated()

  implicitHeight: Math.max(Style.space(155), inspection.y + inspection.height + Style.space(65) + endpoints.implicitHeight)
  clip: true
  activeFocusOnTab: true
  Accessible.role: Accessible.Chart
  Accessible.name: "BODY BATTERY / STRESS. Both scales 0 to 100. " + (cached ? "Cached. " : "") + readout
  Accessible.focusable: true
  Accessible.focused: activeFocus || selected

  function points(samples) {
    var result = []
    if (!validRange || !Array.isArray(samples)) return result
    for (var i = 0; i < samples.length; ++i) {
      var p = samples[i]
      if (!p) continue
      var t = typeof p.time === "number" ? p.time : typeof p.time === "string" ? Date.parse(p.time) : NaN
      if (!isFinite(t) || t < startTime || t > endTime) continue
      result.push({ t: t, value: typeof p.value === "number" && isFinite(p.value) && p.value >= 0 && p.value <= 100 ? p.value : null })
    }
    result.sort(function(a, b) { return a.t - b.t })
    return result
  }

  function nearest(samples) {
    var closest = null, distance = 900000
    if (!inspecting) return null
    // Include null samples in the search: an explicit gap must not reveal an older value.
    for (var i = 0; i < samples.length; ++i) {
      var d = Math.abs(samples[i].t - cursorTime)
      if (d <= distance) { closest = samples[i]; distance = d }
    }
    return closest
  }

  // Each keyboard step is 15 minutes, including across gaps in either series.
  function moveCursor(delta) {
    if (!validRange || !isFinite(delta) || delta === 0) return
    cursorTime = inspecting ? Math.max(startTime, Math.min(endTime, cursorTime + delta * 900000))
      : delta < 0 ? endTime : startTime
  }

  onBatteryPointsChanged: plot.requestPaint()
  onStressPointsChanged: plot.requestPaint()
  onStartTimeChanged: plot.requestPaint()
  onEndTimeChanged: plot.requestPaint()
  onCursorTimeChanged: plot.requestPaint()
  onInkChanged: plot.requestPaint()
  onForegroundChanged: plot.requestPaint()
  onStressInkChanged: plot.requestPaint()
  onGridColorChanged: plot.requestPaint()
  onSelectedChanged: if (!selected && !activeFocus && !hover.containsMouse) cursorTime = NaN
  onActiveFocusChanged: if (!activeFocus && !selected && !hover.containsMouse) cursorTime = NaN
  Keys.onLeftPressed: moveCursor(-1)
  Keys.onRightPressed: moveCursor(1)

  Text {
    id: heading
    width: parent.width
    text: "BODY BATTERY / STRESS"; elide: Text.ElideRight
    color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body; font.bold: true
  }
  Flow {
    id: legend
    y: heading.height + Style.space(4); width: parent.width; spacing: Style.space(10)
    Row {
      spacing: Style.space(5)
      Rectangle { width: Style.space(16); height: Style.space(2); anchors.verticalCenter: parent.verticalCenter; color: root.ink }
      Text { text: "Body battery"; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body }
    }
    Row {
      spacing: Style.space(5)
      Rectangle { width: Style.space(5); height: Style.space(10); anchors.verticalCenter: parent.verticalCenter; color: root.stressInk }
      Text { text: "Stress"; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body }
    }
    Text { visible: root.cached; text: "Cached"; color: root.foreground; opacity: 0.6; font.family: Style.font.family; font.pixelSize: Style.font.body }
    Text { visible: root.notice !== ""; text: root.notice; color: root.foreground; opacity: 0.6; font.family: Style.font.family; font.pixelSize: Style.font.body }
  }
  Text {
    id: inspection
    y: legend.y + legend.height + Style.space(3); width: parent.width
    text: root.readout; textFormat: Text.PlainText; elide: Text.ElideRight
    color: root.foreground; opacity: 0.7; font.family: Style.font.family; font.pixelSize: Style.font.body
  }
  Canvas {
    id: plot
    x: Math.min(Style.space(28), root.width)
    y: inspection.y + inspection.height + Style.space(6)
    width: Math.max(0, root.width - x)
    height: Math.max(0, root.height - y - endpoints.implicitHeight - Style.space(4))
    clip: true
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      if (width <= 0 || height <= 4 || !root.validRange) return
      var span = root.endTime - root.startTime, h = height - 4
      ctx.save()
      ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip()
      ctx.strokeStyle = root.gridColor; ctx.lineWidth = 1
      for (var row = 0; row <= 2; ++row) {
        var gy = 2 + row / 2 * h
        ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(width, gy); ctx.stroke()
      }
      // Bars represent individual observations, not an interpolated stress series.
      var barWidth = Math.max(1, Math.min(Style.space(4), width * 180000 / span))
      ctx.fillStyle = root.stressInk
      for (var i = 0; i < root.stressPoints.length; ++i) {
        var stress = root.stressPoints[i]
        if (stress.value === null) continue
        var sx = (stress.t - root.startTime) / span * width
        var sy = 2 + (1 - stress.value / 100) * h
        ctx.fillRect(sx - barWidth / 2, sy, barWidth, Math.max(1, height - 2 - sy))
      }
      var previous = null
      ctx.strokeStyle = root.ink; ctx.fillStyle = root.ink; ctx.lineWidth = 2
      for (var j = 0; j < root.batteryPoints.length; ++j) {
        var battery = root.batteryPoints[j]
        if (battery.value === null) { previous = null; continue }
        var bx = (battery.t - root.startTime) / span * width
        var by = 2 + (1 - battery.value / 100) * h
        if (previous && battery.t - previous.t <= 1800000) {
          ctx.beginPath(); ctx.moveTo(previous.x, previous.y); ctx.lineTo(bx, by); ctx.stroke()
        }
        // Keep isolated readings visible without joining sampling outages.
        ctx.beginPath(); ctx.arc(bx, by, 1.5, 0, Math.PI * 2); ctx.fill()
        previous = { x: bx, y: by, t: battery.t }
      }
      if (root.inspecting) {
        var cx = (root.cursorTime - root.startTime) / span * width
        ctx.strokeStyle = root.foreground; ctx.globalAlpha = 0.45; ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, height); ctx.stroke()
      }
      ctx.restore()
    }
    MouseArea {
      id: hover
      anchors.fill: parent; hoverEnabled: true
      function inspect(x) {
        if (root.validRange && width > 0)
          root.cursorTime = root.startTime + Math.max(0, Math.min(1, x / width)) * (root.endTime - root.startTime)
      }
      onEntered: inspect(mouseX)
      onPositionChanged: function(mouse) { inspect(mouse.x) }
      onClicked: function(mouse) { inspect(mouse.x); root.forceActiveFocus(); root.activated() }
      onExited: if (!root.selected && !root.activeFocus) root.cursorTime = NaN
    }
  }
  Text {
    x: 0; y: plot.y; width: Math.max(0, plot.x - Style.space(4))
    text: "100"; horizontalAlignment: Text.AlignRight
    color: root.foreground; opacity: 0.55; font.family: Style.font.family; font.pixelSize: Style.font.body * 0.85
  }
  Text {
    x: 0; y: plot.y + Math.max(0, plot.height - height); width: Math.max(0, plot.x - Style.space(4))
    text: "0"; horizontalAlignment: Text.AlignRight
    color: root.foreground; opacity: 0.55; font.family: Style.font.family; font.pixelSize: Style.font.body * 0.85
  }
  Row {
    id: endpoints
    x: plot.x; y: plot.y + plot.height + Style.space(4); width: plot.width
    Repeater {
      model: [root.startTime, root.endTime]
      Column {
        required property real modelData
        required property int index
        width: endpoints.width / 2
        Text {
          width: parent.width; elide: Text.ElideRight
          text: root.validRange ? Qt.formatDateTime(new Date(parent.modelData), "HH:mm") : "--"
          horizontalAlignment: parent.index === 0 ? Text.AlignLeft : Text.AlignRight
          color: root.foreground; opacity: 0.7; font.family: Style.font.family; font.pixelSize: Style.font.body * 0.85
        }
        Text {
          width: parent.width; elide: Text.ElideRight
          text: root.validRange ? Qt.formatDateTime(new Date(parent.modelData), "dd MMM yyyy") : "--"
          horizontalAlignment: parent.index === 0 ? Text.AlignLeft : Text.AlignRight
          color: root.foreground; opacity: 0.5; font.family: Style.font.family; font.pixelSize: Style.font.body * 0.75
        }
      }
    }
  }
}
