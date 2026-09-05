import QtQuick
import QtTest
import ".."

TestCase {
  name: "ActivityIcons"
  width: 80; height: 80
  visible: true
  when: windowShown

  readonly property var kinds: [
    "running", "trailRunning", "treadmill", "cycling", "mountainBiking",
    "indoorCycling", "walking", "hiking", "swimming", "openWaterSwimming",
    "rowing", "indoorRowing", "strength", "cardio", "hiit", "elliptical",
    "stairClimbing", "yoga", "pilates", "skiing", "crossCountrySkiing",
    "snowboarding", "paddling", "kayaking", "paddleboarding", "windsurfing",
    "tennis", "golf", "soccer", "basketball", "surfing"
  ]

  Rectangle {
    id: background
    width: 28; height: 28
    color: "#304050"
    ActivityIcon { id: icon; anchors.fill: parent }
  }

  function test_render_data() {
    return [
      {tag: "native", w: 24, h: 24, ink: "#eeeeee"},
      {tag: "panel", w: 28, h: 28, ink: "#a8c080"},
      {tag: "wide", w: 48, h: 24, ink: "#eeeeee"},
      {tag: "tall", w: 24, h: 48, ink: "#222222"}
    ]
  }

  function test_render(row) {
    background.width = row.w
    background.height = row.h
    icon.ink = row.ink
    icon.kind = "generic"
    wait(30)
    var fallback = grabImage(background)
    icon.kind = "unknown"
    wait(30)
    verify(grabImage(background).equals(fallback), "Unknown kinds retain the generic icon")

    var images = []
    for (var i = 0; i < kinds.length; i++) {
      icon.kind = kinds[i]
      wait(30)
      var image = grabImage(background)
      verify(!image.equals(fallback), kinds[i] + " has a dedicated icon")
      for (var previous = 0; previous < images.length; previous++)
        verify(!image.equals(images[previous]), kinds[i] + " differs from " + kinds[previous])

      var painted = 0
      var offsetX = (row.w - Math.min(row.w, row.h)) / 2
      var offsetY = (row.h - Math.min(row.w, row.h)) / 2
      for (var y = 0; y < row.h; y++) {
        for (var x = 0; x < row.w; x++) {
          if (image.pixel(x, y) === background.color) continue
          painted++
          verify(x >= offsetX && x < row.w - offsetX && y >= offsetY && y < row.h - offsetY,
            kinds[i] + " stays in the centered square")
        }
      }
      verify(painted > 20, kinds[i] + " paints visible strokes")
      images.push(image)
    }
  }
}
