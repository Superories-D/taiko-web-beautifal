import unittest

import tjaf


class TjaMetadataSecurityTests(unittest.TestCase):
    def parse(self, title, subtitle=None, title_ja=None, subtitle_ja=None):
        lines = ["TITLE:" + title]
        if subtitle is not None:
            lines.append("SUBTITLE:" + subtitle)
        if title_ja is not None:
            lines.append("TITLEJA:" + title_ja)
        if subtitle_ja is not None:
            lines.append("SUBTITLEJA:" + subtitle_ja)
        lines.extend(["WAVE:test.ogg", "COURSE:Oni", "LEVEL:1", "#START", "0,", "#END"])
        return tjaf.Tja("\n".join(lines))

    def test_html_like_titles_are_preserved_as_plain_metadata(self):
        payloads = [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "\"><svg onload=alert(1)>",
            "<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>",
            "javascript:alert(1)",
            "&lt;script&gt;alert(1)&lt;/script&gt;",
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                parsed = self.parse(payload)
                tjaf.validate_metadata(parsed)
                self.assertEqual(parsed.to_mongo("test-id", 1)["title"], payload)

    def test_multilingual_and_special_character_titles_are_accepted(self):
        titles = [
            "正常中文标题",
            "正常な日本語タイトル",
            "정상적인 한국어 제목",
            "Quotes \" ' <angle> [brackets] & emoji 🎵",
        ]
        for title in titles:
            with self.subTest(title=title):
                tjaf.validate_metadata(self.parse(title, subtitle=title, title_ja=title, subtitle_ja=title))

    def test_empty_or_overlong_title_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "^invalid_tja_title$"):
            tjaf.validate_metadata(tjaf.Tja("WAVE:test.ogg"))
        with self.assertRaisesRegex(ValueError, "^invalid_tja_title$"):
            tjaf.validate_metadata(self.parse("x" * 501))

    def test_overlong_subtitle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "^invalid_tja_subtitle$"):
            tjaf.validate_metadata(self.parse("Valid", subtitle="x" * 501))

    def test_control_characters_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "^invalid_tja_title$"):
            tjaf.validate_metadata(self.parse("Bad\x1bTitle"))
        with self.assertRaisesRegex(ValueError, "^invalid_tja_subtitle$"):
            tjaf.validate_metadata(self.parse("Valid", subtitle="Bad\x7fSubtitle"))


if __name__ == "__main__":
    unittest.main()
