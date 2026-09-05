"""Run real icon assertions at offscreen and native Wayland screen DPRs."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RUNNER = "/usr/lib/qt6/bin/qmltestrunner"


class ActivityIconTests(unittest.TestCase):
    @unittest.skipUnless(Path(RUNNER).is_file(), "requires Qt 6 qmltestrunner")
    def test_render_at_multiple_device_pixel_ratios(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="activity-icon-dpr-") as directory:
            root = Path(directory)
            tests = root / "tests"
            tests.mkdir()
            shutil.copyfile(source / "ActivityIcon.qml", root / "ActivityIcon.qml")
            shutil.copyfile(source / "tests/tst_activityicons.qml", tests / "tst_activityicons.qml")
            for platform in ("offscreen", "wayland"):
                with self.subTest(platform=platform):
                    if platform == "wayland" and not (os.environ.get("WAYLAND_DISPLAY")
                                                        and os.environ.get("XDG_RUNTIME_DIR")):
                        self.skipTest("native DPR coverage requires a Wayland desktop")
                    # Report actual capture scale; Screen DPR can be rounded on Wayland.
                    (tests / "tst_capture.qml").write_text('''import QtQuick
import QtQuick.Window
import QtTest
TestCase {
  name: "CaptureDpr"
  when: windowShown
  visible: true
  width: 80; height: 80
  Rectangle { id: target; width: 48; height: 24; color: "red" }
  function test_dimensions() {
    wait(30)
    var image = grabImage(target)
    verify(image.width >= 48 && image.height >= 24)
    verify(Math.abs(image.width - 2 * image.height) <= 1)
    compare(image.pixel(Math.floor(image.width / 2), Math.floor(image.height / 2)), target.color)
    console.log("CAPTURE_DPR screen=" + target.Screen.devicePixelRatio
      + " image=" + image.width + "x" + image.height)
  }
}
''')
                    env = {key: value for key, value in os.environ.items()
                           if not key.startswith("QT_")}
                    env.update(QT_QPA_PLATFORM=platform,
                               QT_QPA_OFFSCREEN_NO_GLX="1", QT_QUICK_BACKEND="software",
                               HOME=str(root), XDG_CACHE_HOME=str(root / "cache"))
                    result = subprocess.run([RUNNER, "-input", str(tests)], env=env,
                                            capture_output=True, text=True, timeout=30)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 0, output)
                    self.assertIn("9 passed, 0 failed, 0 skipped", output)
                    print(platform + ": " + next(line.split("qml: ")[-1]
                          for line in output.splitlines() if "CAPTURE_DPR " in line), flush=True)


if __name__ == "__main__":
    unittest.main()
