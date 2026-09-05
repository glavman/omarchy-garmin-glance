"""Exercise the manual QtTest lifecycle in an isolated synthetic project."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


FIXTURE = '''import QtQuick
import QtTest
TestCase {
  id: suite
  when: windowShown
  property bool initialized: false
  property int cleaned: 0
  property int destroyed: 0
  Component {
    id: temporary
    QtObject { Component.onDestruction: suite.destroyed++ }
  }
  function deferredFailure(phase) {
    if (cleaned > 0 && phase !== "cleanupTestCase") return
    if ("MODE" === phase + ":expect") expectFail("", "unconsumed expectation")
    if ("MODE" === phase + ":warning") ignoreWarning("warning that never arrives")
    if ("MODE" === phase + ":failure") qtest_results.fail("nonthrow failure", "", 0)
    if ("MODE" === phase + ":skip") qtest_results["skip"]("nonthrow skip", "", 0)
  }
  function initTestCase() {
    initialized = true
    if ("MODE" === "init") fail("synthetic initialization failure")
    deferredFailure("initTestCase")
  }
  function init() {
    verify(initialized)
    compare(destroyed, cleaned, "temporary objects disposed between rows")
    verify(createTemporaryObject(temporary, suite) !== null)
    deferredFailure("init")
  }
  function test_rows_data() { return [{tag: "first"}, {tag: "second"}] }
  function test_rows(row) {
    if (row.tag === "first" && "MODE" === "test") fail("synthetic failure")
    if (row.tag === "first" && "MODE" === "skip") skip("must fail closed")
    deferredFailure("test")
  }
  function cleanup() {
    deferredFailure("cleanup")
    cleaned++; console.log("ROW_CLEANUP " + cleaned)
  }
  function cleanupTestCase() {
    console.log("SUITE_CLEANUP " + cleaned)
    if ("MODE" === "cleanup") fail("synthetic teardown failure")
    deferredFailure("cleanupTestCase")
  }
}
'''


class QmlRunnerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("quickshell") and os.environ.get("WAYLAND_DISPLAY")
                         and os.environ.get("XDG_RUNTIME_DIR")
                         and Path("/usr/share/omarchy/shell/Ui/qmldir").is_file(),
                         "requires packaged Omarchy and a Wayland desktop")
    def test_lifecycle_datasets_failures_and_remaining_suites(self):
        with tempfile.TemporaryDirectory(prefix="qml-runner-test-") as directory:
            root = Path(directory)
            tests = root / "tests"
            tests.mkdir()
            shutil.copyfile(Path(__file__).with_name("run_qml.py"), tests / "run_qml.py")
            (root / "Placeholder.qml").write_text("import QtQuick\nItem {}\n")
            (tests / "tst_z_remaining.qml").write_text(
                'import QtTest\nTestCase { function test_remaining() { verify(true) } }\n')
            modes = ["pass", "init", "test", "skip", "cleanup", "load"]
            modes += [phase + ":" + failure
                      for phase in ("initTestCase", "init", "test", "cleanup", "cleanupTestCase")
                      for failure in ("expect", "warning", "failure", "skip")]
            for mode in modes:
                with self.subTest(mode=mode):
                    text = FIXTURE.replace("MODE", mode)
                    if mode == "load":
                        text = "import MissingSyntheticModule\n" + text
                    (tests / "tst_lifecycle.qml").write_text(text)
                    result = subprocess.run(
                        [sys.executable, "-B", str(tests / "run_qml.py"), "--timeout", "10"],
                        capture_output=True, text=True, timeout=15)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 0 if mode == "pass" else 1, output)
                    self.assertIn("PASS z_remaining.test_remaining[0]", output)
                    init_failed = mode == "init" or mode.startswith("initTestCase:")
                    if mode != "load":
                        self.assertIn("SUITE_CLEANUP " + ("0" if init_failed else "2"), output)
                    if not init_failed and mode != "load":
                        self.assertIn("ROW_CLEANUP 2", output)
                        self.assertIn("PASS lifecycle.test_rows[second]", output)
                    if mode.startswith(("init:", "test:", "cleanup:")):
                        self.assertNotIn("PASS lifecycle.test_rows[first]", output)
                    if mode == "pass":
                        self.assertIn("PASS: 3 test cases (data rows included)", output)


if __name__ == "__main__":
    unittest.main()
