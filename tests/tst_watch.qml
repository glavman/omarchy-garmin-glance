import QtQuick
import QtTest
import ".."

TestCase {
  id: root
  name: "Watch"
  width: 600; height: 600
  when: windowShown
  WatchFace { id: face; width: 540; ink: "#eeeeee"; accent: "#a8c080" }
  WatchIcon { id: icon; width: 22; height: 22 }
  ActivityIcon { id: activityIcon; width: 28; height: 28 }

  function test_activity_icons() {
    var kinds = ["running", "cycling", "mountainBiking", "windsurfing", "rowing", "strength", "walking", "hiking", "swimming", "skiing", "yoga", "paddling", "cardio", "generic", "unknown"]
    for (var i = 0; i < kinds.length; i++) {
      activityIcon.kind = kinds[i]
      activityIcon.ink = i % 2 ? "#eeeeee" : "#222222"
      wait(10)
      verify(grabImage(activityIcon).width > 0)
    }
  }

  function test_layout_data() {
    return [
      {tag: "wide", size: 540, model: "Forerunner 965"},
      {tag: "narrow", size: 240, model: "Venu Sq 2"},
      {tag: "long", size: 280, model: "A".repeat(80)},
      {tag: "rugged", size: 540, model: "fenix 8"},
      {tag: "band", size: 240, model: "vivosmart 5"}
    ]
  }
  function test_layout(row) {
    face.width = row.size
    face.modelOverride = row.model
    face.payload = {metrics: {bodyBattery: {value: 73, unit: "score"}}}
    icon.watchStyle = face.watchStyle
    wait(20)
    compare(face.device.name, row.model)
    verify(face.implicitHeight > 30)
    verify(face.implicitHeight < 600)
    function contained(item) {
      for (var i = 0; i < item.children.length; i++) {
        var child = item.children[i]
        if (child.visible && child.width > 0) {
          verify(child.x >= 0 && child.x + child.width <= item.width + 1, "Child fits parent")
          contained(child)
        }
      }
    }
    contained(face)
  }
}
