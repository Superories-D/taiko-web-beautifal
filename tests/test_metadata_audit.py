import unittest

from scripts.audit_song_metadata import inspect_text, iter_text_fields, safe_json


class MetadataAuditTests(unittest.TestCase):
    def test_suspicious_patterns_are_classified_without_returning_content(self):
        value = "<img src=x onerror=alert(1)>"
        reasons = inspect_text(value)
        self.assertIn("html_tag", reasons)
        self.assertIn("event_handler", reasons)
        self.assertNotIn(value, reasons)

    def test_normal_multilingual_titles_are_not_flagged(self):
        for value in ("正常中文标题", "正常な日本語タイトル", "정상적인 한국어 제목", "Emoji 🎵 <3"):
            with self.subTest(value=value):
                self.assertEqual(inspect_text(value), [])

    def test_control_characters_and_long_values_are_flagged(self):
        self.assertIn("control_character", inspect_text("Bad\x1bTitle"))
        self.assertIn("long_value", inspect_text("x" * 501))

    def test_nested_language_fields_are_enumerated(self):
        fields = list(iter_text_fields(
            {"title": "Main", "title_lang": {"ja": "日本語", "en": None}},
            ("title", "title_lang"),
        ))
        self.assertEqual(fields, [("title", "Main"), ("title_lang.ja", "日本語")])

    def test_json_output_escapes_html_significant_characters(self):
        output = safe_json({"record_id": "<id>&"})
        self.assertNotIn("<", output)
        self.assertNotIn(">", output)
        self.assertNotIn("&", output)
        self.assertIn("\\u003c", output)


if __name__ == "__main__":
    unittest.main()
