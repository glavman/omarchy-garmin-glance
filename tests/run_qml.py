#!/usr/bin/env python3
"""Run dashboard and coach QML tests with packaged Omarchy/Quickshell imports.

Usage: python3 tests/run_qml.py
Requires a running Wayland desktop for the real Panel keyboard test. Unlike bare
qmltestrunner -input tests, this supplies qs imports and Quickshell initialization.
Only QML/JS sources are copied: real backend/coach helpers cannot run. HOME and
XDG config/data/cache/state are temporary; packaged host imports are read-only.
This is test isolation, not a sandbox for untrusted QML.
All discovered suites and data rows run; failures and skips fail the whole run.
Manual execution uses QtTest's internal result/temporary-object APIs, covered by
test_run_qml.py against the installed Qt/Quickshell runtime.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid


HARNESS = r'''
import QtQuick
import QtQuick.Window
import Quickshell
import "plugin" as Garmin

Item {
  id: root
  property var suites: SUITES
  property int suiteIndex: 0
  property int passed: 0
  property int failed: 0
  Window {
    id: window
    visible: true
    width: 360; height: 800
    Loader {
      id: loader
      onLoaded: run.restart()
      onStatusChanged: if (status === Loader.Error) {
        root.fail(root.suites[root.suiteIndex].name + ": QML load failed")
        root.suiteIndex++
        Qt.callLater(root.loadNext)
      }
    }
  }
  function fail(message) {
    console.log("RESULT_TOKEN FAIL " + message)
    failed++
  }
  function finalized(suite, action) {
    var results = suite.qtest_results
    var failures = results.failCount
    var skips = results.skipCount
    try {
      action()
    } finally {
      // Finalization can record deferred failures and then clear `failed`.
      var unsuccessful = results.failed || results.skipped
      try {
        results.finishTestData()
        results.finishTestDataCleanup()
        results.finishTestFunction()
        unsuccessful = unsuccessful || results.failed || results.skipped
          || results.failCount !== failures || results.skipCount !== skips
      } finally {
        results.skipped = false
      }
      if (unsuccessful) throw new Error("QtTest recorded a failure or skip during execution/finalization")
    }
  }
  function loadNext() {
    if (suiteIndex === suites.length) {
      console.log("RESULT_TOKEN " + (failed ? "FAILED " + failed + " PASSED " : "PASS ") + passed)
      Qt.quit()
      return
    }
    loader.source = ""
    loader.source = suites[suiteIndex].file
  }
  Timer {
    id: run
    interval: 200
    onTriggered: {
      window.requestActivate()
      var suite = loader.item
      var spec = root.suites[root.suiteIndex]
      var name = "initTestCase"
      try {
        suite.qtest_results.reset()
        suite.qtest_results.testCaseName = spec.name
        suite.qtest_results.functionName = name
        root.finalized(suite, function() {
          if (typeof suite.initTestCase === "function") suite.initTestCase()
        })
        for (var i = 0; i < spec.functions.length; i++) {
          name = spec.functions[i]
          suite.qtest_results.functionName = name
          var provider = name + "_data"
          var rows = typeof suite[provider] === "function" ? suite[provider]() : [undefined]
          if (!rows.length) throw new Error("Empty data provider: " + provider)
          for (var j = 0; j < rows.length; j++) {
            var label = spec.name + "." + name + "[" + (rows[j] && rows[j].tag || j) + "]"
            try {
              root.finalized(suite, function() {
                try {
                  if (typeof suite.init === "function") suite.init()
                  if (!suite.qtest_results.failed && !suite.qtest_results.skipped)
                    suite[name](rows[j])
                } finally {
                  // Consume test expectations before cleanup assertions can do so.
                  suite.qtest_results.finishTestData()
                  try { if (typeof suite.cleanup === "function") suite.cleanup() }
                  finally {
                    // Manual invocation bypasses QtTest's per-row object disposal.
                    suite.qtest_destroyTemporaryObjects()
                    suite.wait(0)
                  }
                }
              })
              root.passed++
              console.log("PASS " + label)
            } catch (error) {
              root.fail(label + ": " + error + "\n" + error.stack)
            }
          }
        }
      } catch (error) {
        root.fail(spec.name + "." + name + ": " + error + "\n" + error.stack)
      } finally {
        try {
          suite.qtest_results.functionName = "cleanupTestCase"
          root.finalized(suite, function() {
            if (typeof suite.cleanupTestCase === "function") suite.cleanupTestCase()
          })
        } catch (error) {
          root.fail(spec.name + ".cleanupTestCase: " + error + "\n" + error.stack)
        }
      }
      loader.source = ""
      root.suiteIndex++
      Qt.callLater(root.loadNext)
    }
  }
  Component.onCompleted: Qt.callLater(loadNext)
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-shell", type=Path, default=Path("/usr/share/omarchy/shell"))
    parser.add_argument("--timeout", type=float, default=60, help="whole-run timeout in seconds")
    args = parser.parse_args()
    executable = shutil.which("quickshell")
    if not executable or args.timeout <= 0:
        parser.error("quickshell must be installed and timeout must be positive")
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("XDG_RUNTIME_DIR"):
        parser.error("a Wayland desktop is required; the Panel test must not silently skip")
    host = args.host_shell.resolve()
    for module in ("Commons", "Ui"):
        if not (host / module / "qmldir").is_file():
            parser.error(f"missing packaged host module: {host / module}")

    source = Path(__file__).resolve().parent.parent
    token = "QML_RUN_" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="garmin-qml-") as directory:
        temp = Path(directory)
        plugin = temp / "plugin"
        tests = plugin / "tests"
        tests.mkdir(parents=True)
        for pattern in ("*.qml", "*.js"):
            for path in source.glob(pattern):
                shutil.copyfile(path, plugin / path.name)
        suites = []
        for path in sorted((source / "tests").glob("tst_*.qml")):
            name = path.stem.removeprefix("tst_")
            text = path.read_text()
            functions = re.findall(r"\bfunction\s+(test_\w+)\s*\(", text)
            functions = [name for name in functions if not name.endswith("_data")]
            if not functions:
                raise RuntimeError("No test functions discovered")
            # Run assertions explicitly, including each data row, under Quickshell's engine.
            text = re.sub(r"\bwhen:\s*windowShown", "when: false", text)
            text = re.sub(r"\bskip\(", "throw new Error(", text)
            if "when: false" not in text:
                text = text.replace("TestCase {", "TestCase {\n  when: false\n", 1)
            (tests / f"tst_{name}.qml").write_text(text)
            suites.append({"name": name, "file": f"plugin/tests/tst_{name}.qml", "functions": functions})
        if not suites:
            raise RuntimeError("No QML test suites discovered")

        # qs resolves relative to the Quickshell config root. Supply only packaged UI modules.
        for module in ("Commons", "Ui"):
            (temp / module).symlink_to(host / module, target_is_directory=True)
        home = temp / "home"
        home.mkdir()
        bins = temp / "bin"
        bins.mkdir()
        # Style.qml probes these on load. Fail locally instead of reading desktop settings.
        for command in ("hyprctl", "fc-match"):
            (bins / command).symlink_to("/usr/bin/false")
        env = {key: os.environ[key] for key in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "LANG") if key in os.environ}
        env.update({"HOME": str(home), "PATH": str(bins), "QT_QPA_PLATFORM": "wayland",
                    "QT_QUICK_BACKEND": "software", "QSG_RENDER_LOOP": "basic",
                    "QT_LOGGING_RULES": "qml.debug=true", "NO_COLOR": "1"})
        for kind in ("CONFIG", "DATA", "CACHE", "STATE"):
            path = home / kind.lower()
            path.mkdir()
            env[f"XDG_{kind}_HOME"] = str(path)
        harness = temp / "shell.qml"
        harness.write_text(HARNESS.replace("SUITES", json.dumps(suites)).replace("RESULT_TOKEN", token))
        print(f"Host imports (read-only): {host}/Commons, {host}/Ui", flush=True)
        print("Running " + ", ".join(suite["name"] for suite in suites)
              + ", including synthetic Process and real Panel tests", flush=True)
        process = subprocess.Popen([executable, "--no-color", "-p", str(harness)], cwd=temp,
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
            print(output, end="")
            print(f"FAIL: QML tests timed out after {args.timeout:g}s", file=sys.stderr)
            return 1
        finally:
            # Also reap any child helper left behind by a failing or crashed test.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        print(output, end="")
        matches = re.findall(re.escape(token) + r" PASS (\d+)", output)
        if process.returncode != 0 or len(matches) != 1 or token + " FAIL" in output:
            print("FAIL: Quickshell did not report a complete successful run", file=sys.stderr)
            return 1
        print(f"PASS: {matches[0]} test cases (data rows included)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
