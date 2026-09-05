"""Check the published setup prompt without executing JavaScript or reading config."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_prompt_matches_readme(self):
        source = (ROOT / "Setup.js").read_text()
        url_match = re.search(r'^var documentationUrl = (".*")$', source, re.MULTILINE)
        self.assertIsNotNone(url_match)
        url = json.loads(url_match[1])
        prompt_match = re.search(r'var prompt = \[\n(.*?)\n\]\.join\("\\n"\)', source, re.DOTALL)
        self.assertIsNotNone(prompt_match)
        lines = []
        for line in prompt_match[1].splitlines():
            value = line.strip().removesuffix(",")
            lines.append(url if value == "documentationUrl" else json.loads(value))
        blocks = re.findall(r"^```text\n(.*?)\n```$", (ROOT / "README.md").read_text(),
                            re.MULTILINE | re.DOTALL)
        self.assertEqual(len(blocks), 1, "README must expose one unambiguous setup prompt")
        self.assertEqual("\n".join(lines), blocks[0])
        self.assertEqual(lines.count(url), 1)

    def test_documentation_url_targets_shipped_guide(self):
        source = (ROOT / "Setup.js").read_text()
        match = re.search(r'^var documentationUrl = (".*")$', source, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match[1]),
                         "https://github.com/glavman/omarchy-garmin-glance/blob/main/docs/SETUP.md")
        self.assertTrue((ROOT / "docs/SETUP.md").is_file())

    def test_external_guide_requires_explicit_click(self):
        # Do not open a browser in the native suite, even with an isolated HOME.
        source = (ROOT / "Setup.qml").read_text()
        self.assertEqual(source.count("Qt.openUrlExternally("), 1)
        self.assertIn("onClicked: Qt.openUrlExternally(Guide.documentationUrl)", source)
        self.assertNotRegex(source, r"\b(?:Process|Timer)\s*\{|Component\.onCompleted")


if __name__ == "__main__":
    unittest.main()
