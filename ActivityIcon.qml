import QtQuick

Canvas {
  id: root
  property color ink: "white"
  property string kind: "generic"
  implicitWidth: 24
  implicitHeight: 24
  Accessible.ignored: true

  onInkChanged: requestPaint()
  onKindChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()
  onAvailableChanged: if (available) requestPaint()

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    if (width <= 0 || height <= 0) return
    // Keep the same square drawing space even in a non-square layout slot.
    var scale = Math.min(width, height) / 24
    ctx.save()
    ctx.translate((width - 24 * scale) / 2, (height - 24 * scale) / 2)
    ctx.scale(scale, scale)
    ctx.strokeStyle = root.ink
    ctx.lineWidth = 2
    ctx.lineCap = "round"
    ctx.lineJoin = "round"

    function line(points, closed) {
      ctx.beginPath()
      ctx.moveTo(points[0], points[1])
      for (var i = 2; i < points.length; i += 2) ctx.lineTo(points[i], points[i + 1])
      if (closed) ctx.closePath()
      ctx.stroke()
    }
    function circle(x, y, radius) {
      ctx.beginPath()
      ctx.arc(x, y, radius, 0, Math.PI * 2)
      ctx.stroke()
    }

    switch (root.kind) {
    case "running":
      circle(15, 4, 2)
      line([5, 10, 9, 7, 13, 9, 16, 12, 20, 12])
      line([13, 9, 10, 14, 15, 17, 14, 21])
      line([10, 14, 7, 18, 3, 18])
      break
    case "cycling":
    case "mountainBiking":
      circle(5, 17, 3.5)
      circle(19, 17, 3.5)
      line([5, 17, 9, 10, 14, 17, 5, 17])
      line([9, 10, 16, 10, 14, 17])
      line([19, 17, 16, 7, 19, 7])
      line([7, 7, 10, 7])
      line([9, 7, 9, 10])
      if (root.kind === "mountainBiking") line([3, 7, 7, 2, 11, 5, 14, 2])
      break
    case "windsurfing":
      line([10, 19, 10, 2, 20, 15, 10, 15])
      ctx.beginPath()
      ctx.moveTo(3, 19)
      ctx.quadraticCurveTo(12, 23, 21, 19)
      ctx.stroke()
      break
    case "rowing":
      line([3, 20, 14, 9])
      line([13, 8, 18, 3, 21, 6, 16, 11], true)
      line([3, 12, 6, 16, 18, 16, 21, 12])
      line([3, 12, 9, 12])
      line([18, 12, 21, 12])
      break
    case "strength":
      line([8, 10, 16, 10])
      line([8, 14, 16, 14])
      line([4, 6, 8, 6, 8, 18, 4, 18], true)
      line([16, 6, 20, 6, 20, 18, 16, 18], true)
      line([2, 10, 2, 14])
      line([22, 10, 22, 14])
      break
    case "walking":
      circle(13, 4, 2)
      line([6, 12, 9, 8, 12, 9, 16, 13, 19, 13])
      line([12, 9, 11, 15, 15, 21])
      line([11, 15, 7, 21])
      break
    case "hiking":
      line([3, 20, 10, 5, 14, 12, 17, 8, 22, 20, 3, 20])
      line([7, 11, 10, 13, 12, 9])
      break
    case "swimming":
      circle(18, 10, 2)
      line([4, 14, 10, 9, 6, 5, 3, 7])
      line([10, 9, 14, 13])
      for (var y = 16; y <= 21; y += 5) {
        ctx.beginPath()
        ctx.moveTo(2, y)
        ctx.bezierCurveTo(5, y - 3, 7, y + 3, 10, y)
        ctx.bezierCurveTo(13, y - 3, 15, y + 3, 18, y)
        ctx.quadraticCurveTo(20, y - 2, 22, y)
        ctx.stroke()
      }
      break
    case "skiing":
      for (var x = 3; x <= 8; x += 5) {
        ctx.beginPath()
        ctx.moveTo(x, 21)
        ctx.lineTo(x + 9, 5)
        ctx.quadraticCurveTo(x + 11, 1, x + 13, 4)
        ctx.stroke()
      }
      line([3, 3, 16, 20])
      line([13, 20, 17, 17])
      break
    case "yoga":
      circle(12, 4, 2)
      line([8, 9, 12, 8, 16, 9])
      line([8, 9, 6, 14, 3, 14])
      line([16, 9, 18, 14, 21, 14])
      line([12, 8, 12, 15])
      ctx.beginPath()
      ctx.moveTo(12, 15)
      ctx.bezierCurveTo(2, 12, 1, 20, 8, 20)
      ctx.lineTo(16, 20)
      ctx.bezierCurveTo(23, 20, 22, 12, 12, 15)
      ctx.stroke()
      break
    case "paddling":
      line([8, 16, 16, 8])
      line([3, 17, 6, 14, 10, 18, 7, 21], true)
      line([14, 6, 17, 3, 21, 7, 18, 10], true)
      break
    case "cardio":
      ctx.beginPath()
      ctx.moveTo(12, 21)
      ctx.bezierCurveTo(-5, 10, 4, -2, 12, 6)
      ctx.bezierCurveTo(20, -2, 29, 10, 12, 21)
      ctx.stroke()
      line([3, 12, 8, 12, 10, 9, 13, 16, 15, 12, 21, 12])
      break
    default:
      circle(12, 14, 8)
      line([9, 2, 15, 2])
      line([12, 2, 12, 6])
      line([18, 7, 20, 5])
      line([12, 10, 12, 14, 15, 14])
      break
    }
    ctx.restore()
  }
}
