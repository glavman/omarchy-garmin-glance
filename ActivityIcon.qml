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
    case "trailRunning":
      circle(14, 3, 1.5)
      line([6, 8, 9, 6, 12, 8, 16, 10, 19, 8])
      line([12, 8, 10, 12, 15, 15, 17, 18])
      line([10, 12, 6, 16, 3, 15])
      line([2, 22, 8, 19, 12, 21, 18, 19, 22, 21])
      break
    case "treadmill":
      circle(11, 3, 1.5)
      line([5, 9, 8, 6, 11, 8, 15, 9])
      line([11, 8, 9, 12, 13, 15])
      line([9, 12, 5, 15])
      line([15, 5, 21, 5, 19, 18])
      line([4, 18, 19, 18, 21, 21, 2, 21], true)
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
    case "indoorCycling":
      circle(9, 15, 4)
      line([9, 15, 12, 16, 14, 16])
      line([9, 11, 8, 7, 5, 7, 10, 7])
      line([12, 12, 17, 8, 18, 3, 21, 3])
      line([17, 8, 19, 20, 22, 20])
      line([6, 18, 4, 21, 2, 21])
      break
    case "windsurfing":
      line([10, 19, 10, 2, 20, 15, 10, 15])
      ctx.beginPath()
      ctx.moveTo(3, 19)
      ctx.quadraticCurveTo(12, 23, 21, 19)
      ctx.stroke()
      break
    case "surfing":
      circle(13, 3, 1.5)
      line([5, 9, 9, 7, 12, 8, 16, 10, 20, 8])
      line([12, 8, 10, 12, 7, 16])
      line([10, 12, 15, 13, 17, 16])
      ctx.beginPath()
      ctx.moveTo(3, 17)
      ctx.quadraticCurveTo(12, 21, 21, 16)
      ctx.moveTo(2, 22)
      ctx.bezierCurveTo(6, 19, 8, 24, 12, 21)
      ctx.bezierCurveTo(16, 18, 18, 23, 22, 20)
      ctx.stroke()
      break
    case "rowing":
      line([3, 20, 14, 9])
      line([13, 8, 18, 3, 21, 6, 16, 11], true)
      line([3, 12, 6, 16, 18, 16, 21, 12])
      line([3, 12, 9, 12])
      line([18, 12, 21, 12])
      break
    case "indoorRowing":
      circle(10, 4, 2)
      circle(20, 15, 2.5)
      line([10, 8, 8, 13, 13, 13, 15, 17])
      line([10, 8, 14, 10, 18, 9])
      line([18, 9, 20, 12])
      line([5, 16, 10, 16])
      line([2, 20, 22, 20])
      line([5, 20, 5, 22])
      line([20, 20, 20, 22])
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
    case "openWaterSwimming":
      circle(18, 11, 2)
      line([4, 15, 10, 10, 6, 6, 3, 8])
      line([10, 10, 14, 14])
      line([14, 6, 14, 2, 20, 4, 14, 6])
      for (var waveY = 18; waveY <= 22; waveY += 4) {
        ctx.beginPath()
        ctx.moveTo(2, waveY)
        ctx.bezierCurveTo(6, waveY - 3, 8, waveY + 2, 12, waveY)
        ctx.bezierCurveTo(16, waveY - 3, 18, waveY + 2, 22, waveY)
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
    case "crossCountrySkiing":
      circle(13, 3, 1.5)
      line([13, 7, 10, 12, 5, 17])
      line([10, 12, 15, 14, 18, 18])
      line([7, 7, 10, 6, 13, 7, 16, 10, 20, 8])
      line([7, 7, 3, 18])
      line([20, 8, 21, 18])
      line([2, 21, 20, 21, 22, 19])
      break
    case "snowboarding":
      circle(14, 3, 1.5)
      line([6, 9, 10, 7, 13, 8, 17, 11, 21, 10])
      line([13, 8, 11, 12, 8, 16])
      line([11, 12, 16, 14, 15, 17])
      ctx.beginPath()
      ctx.moveTo(3, 18)
      ctx.bezierCurveTo(0, 23, 20, 24, 22, 17)
      ctx.bezierCurveTo(23, 15, 20, 15, 19, 17)
      ctx.quadraticCurveTo(11, 21, 5, 17)
      ctx.quadraticCurveTo(4, 16, 3, 18)
      ctx.stroke()
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
    case "pilates":
      circle(4, 14, 2)
      line([8, 15, 13, 15, 17, 5])
      line([13, 15, 20, 9])
      line([8, 15, 11, 11, 14, 11])
      line([2, 21, 22, 21])
      break
    case "paddling":
      line([8, 16, 16, 8])
      line([3, 17, 6, 14, 10, 18, 7, 21], true)
      line([14, 6, 17, 3, 21, 7, 18, 10], true)
      break
    case "kayaking":
      circle(12, 4, 1.5)
      line([12, 8, 12, 14])
      line([8, 11, 10, 9, 15, 11])
      line([5, 5, 19, 19])
      line([3, 3, 7, 5, 5, 7, 3, 3])
      line([17, 19, 19, 17, 21, 21, 17, 19])
      ctx.beginPath()
      ctx.moveTo(2, 14)
      ctx.quadraticCurveTo(12, 11, 22, 14)
      ctx.quadraticCurveTo(12, 23, 2, 14)
      ctx.stroke()
      break
    case "paddleboarding":
      circle(11, 3, 1.5)
      line([11, 7, 11, 13, 8, 18])
      line([11, 13, 14, 18])
      line([11, 8, 15, 10, 18, 8])
      line([18, 5, 18, 15])
      line([17, 15, 19, 15, 19, 19, 17, 19], true)
      ctx.beginPath()
      ctx.moveTo(2, 20)
      ctx.quadraticCurveTo(12, 24, 22, 20)
      ctx.stroke()
      break
    case "cardio":
      ctx.beginPath()
      ctx.moveTo(12, 21)
      ctx.bezierCurveTo(-5, 10, 4, -2, 12, 6)
      ctx.bezierCurveTo(20, -2, 29, 10, 12, 21)
      ctx.stroke()
      line([3, 12, 8, 12, 10, 9, 13, 16, 15, 12, 21, 12])
      break
    case "elliptical":
      circle(11, 3, 1.5)
      line([11, 7, 9, 12, 14, 14, 16, 18])
      line([9, 12, 6, 18])
      line([11, 7, 14, 10, 18, 8])
      line([18, 5, 17, 18])
      line([4, 18, 9, 18])
      line([14, 18, 20, 18])
      ctx.beginPath()
      ctx.moveTo(2, 22)
      ctx.quadraticCurveTo(12, 17, 22, 22)
      ctx.stroke()
      break
    case "stairClimbing":
      circle(10, 3, 1.5)
      line([5, 9, 8, 6, 11, 8, 15, 9])
      line([11, 8, 9, 12, 13, 12, 13, 16])
      line([9, 12, 6, 17])
      line([2, 22, 8, 22, 8, 19, 15, 19, 15, 15, 22, 15])
      break
    case "hiit":
      line([14, 2, 4, 14, 11, 14, 10, 22, 20, 10, 13, 10], true)
      line([3, 5, 5, 5])
      line([19, 19, 21, 19])
      break
    case "tennis":
      ctx.save()
      ctx.translate(14, 8)
      ctx.rotate(Math.PI / 4)
      ctx.scale(0.75, 1)
      circle(0, 0, 6)
      ctx.restore()
      line([10, 12, 7, 17, 4, 20, 2, 18, 5, 15, 10, 12])
      line([11, 5, 17, 11])
      line([15, 3, 19, 7])
      line([10, 9, 15, 4])
      line([14, 12, 19, 7])
      circle(19, 19, 2.5)
      break
    case "golf":
      line([10, 18, 10, 2, 20, 6, 10, 10])
      ctx.beginPath()
      ctx.moveTo(7, 15)
      ctx.bezierCurveTo(-2, 16, 2, 22, 12, 22)
      ctx.bezierCurveTo(23, 22, 25, 16, 14, 15)
      ctx.stroke()
      circle(6, 18, 1)
      break
    case "soccer":
      circle(12, 12, 10)
      line([12, 7, 17, 11, 15, 16, 9, 16, 7, 11], true)
      line([12, 7, 12, 2])
      line([17, 11, 21, 8])
      line([15, 16, 18, 20])
      line([9, 16, 6, 20])
      line([7, 11, 3, 8])
      break
    case "basketball":
      circle(12, 12, 10)
      line([2, 12, 22, 12])
      line([12, 2, 12, 22])
      ctx.beginPath()
      ctx.moveTo(5, 5)
      ctx.bezierCurveTo(13, 8, 13, 16, 5, 19)
      ctx.moveTo(19, 5)
      ctx.bezierCurveTo(11, 8, 11, 16, 19, 19)
      ctx.stroke()
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
