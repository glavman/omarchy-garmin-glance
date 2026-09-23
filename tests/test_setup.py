"""Check the published setup prompt without executing JavaScript or reading config."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_prompt_matches_readme(self):
        source = (ROOT / "Setup.js").read_text()
        path = "~/.config/omarchy/plugins/io.github.glavman.garmin-glance/docs/SETUP.md"
        prompt_match = re.search(r'return \[\n(.*?)\n\s*\]\.join\("\\n"\)', source, re.DOTALL)
        self.assertIsNotNone(prompt_match)
        lines = []
        for line in prompt_match[1].splitlines():
            value = line.strip().removesuffix(",")
            lines.append(path if value == "documentationPath" else json.loads(value))
        blocks = re.findall(r"^```text\n(.*?)\n```$", (ROOT / "README.md").read_text(),
                            re.MULTILINE | re.DOTALL)
        self.assertEqual(len(blocks), 1, "README must expose one unambiguous setup prompt")
        self.assertEqual("\n".join(lines), blocks[0])
        self.assertEqual(lines.count(path), 1)

    def test_setup_instruction_chain_uses_bundled_files(self):
        for name in ("Setup.js", "Setup.qml", "README.md", "docs/SETUP.md", "docs/REFERENCE.md"):
            with self.subTest(name=name):
                source = (ROOT / name).read_text()
                self.assertNotRegex(source, r'https://(?:github\.com|raw\.githubusercontent\.com)/'
                                    r'glavman/omarchy-garmin-glance/(?:blob/|raw/)?[^\s)"<>]+')
        self.assertIn('Qt.resolvedUrl("docs/SETUP.md")', (ROOT / "Setup.qml").read_text())

    def test_external_guide_requires_explicit_click(self):
        # Do not open a browser in the native suite, even with an isolated HOME.
        source = (ROOT / "Setup.qml").read_text()
        self.assertEqual(source.count("Qt.openUrlExternally("), 1)
        self.assertIn("onClicked: if (root.guideAvailable) Qt.openUrlExternally(root.documentationUrl)", source)
        self.assertNotRegex(source, r"\b(?:Process|Timer)\s*\{|Component\.onCompleted")


if __name__ == "__main__":
    unittest.main()
