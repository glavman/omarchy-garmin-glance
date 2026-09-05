import QtQuick
import Quickshell

FloatingWindow {
  visible: true
  implicitWidth: 500
  implicitHeight: 500

  Component.onCompleted: {
    Quickshell.watchFiles = false
    // Drive QtTest manually inside a native window, not qmltestrunner.
    // File URLs let the test resolve ../Panel.qml outside Quickshell's config root.
    loader.setSource("file://" + Quickshell.shellDir + "/tst_navigation.qml", {when: false})
  }

  Loader {
    id: loader
    anchors.fill: parent
    onStatusChanged: if (status === Loader.Error) {
      console.error("NAVIGATION FAILED: could not load tst_navigation.qml")
      Qt.exit(1)
    }
  }

  Timer {
    interval: 800; running: true
    onTriggered: {
      var test = loader.item
      var current = "initTestCase"
      var code = 0
      var cases = [
        "test_navigation_and_pairs",
        "test_context_and_single_activation",
        "test_details_hover_and_reveal",
        "test_unavailable_actions",
        "test_hover_focus_and_gps",
        "test_narrow_context_button",
        "test_activity_totals_and_dates",
        "test_activity_states",
        "test_activity_row_actions",
        "test_activity_paging_and_shrink",
        "test_activity_hover_and_disabled_ids",
        "test_activity_narrow_and_full_count",
        "test_activity_id_without_connect_provenance",
        "test_tab_and_escape"
      ]
      try {
        if (!test) throw new Error("Navigation test did not load")
        var component = Qt.createComponent("file://" + Quickshell.shellDir + "/../Panel.qml")
        if (component.status === Component.Error) throw new Error(component.errorString())
        test.initTestCase()
        for (var i = 0; i < cases.length; i++) {
          current = cases[i]
          test.init()
          test[current]()
          test.cleanup()
          console.log("PASS", current)
        }
      } catch (error) {
        console.error("NAVIGATION FAILED", current, error.message, error.stack)
        code = 1
      } finally {
        try {
          if (test) test.cleanupTestCase()
        } catch (error) {
          console.error("NAVIGATION FAILED cleanupTestCase", error.message, error.stack)
          code = 1
        }
      }
      if (code === 0) console.log("NAVIGATION PASSED:", cases.length, "cases")
      Qt.exit(code)
    }
  }
}
