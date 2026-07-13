import json
import re
import unittest
import xml.etree.ElementTree as ET

import app as taiko


class MultilingualSeoTest(unittest.TestCase):
    def setUp(self):
        self.client = taiko.app.test_client()

    def test_each_language_has_distinct_search_metadata(self):
        expected = {
            'ja': ('ja', '太鼓ウェブ', '無料', '非公式', '週間チャレンジ'),
            'en': ('en', 'Unofficial', 'Free Online', 'Bandai Namco Entertainment', 'Weekly challenges'),
            'cn': ('zh-Hans', '太鼓达人网页版', '免费在线', '非官方', '每周挑战'),
            'tw': ('zh-Hant', '太鼓達人網頁版', '免費線上', '非官方', '每週挑戰'),
            'ko': ('ko', '비공식', '무료 온라인', 'Bandai Namco Entertainment', '주간 챌린지'),
        }
        for code, (html_lang, title_term, intent_term, disclaimer_term, feature_term) in expected.items():
            with self.subTest(code=code):
                response = self.client.get('/' + code, base_url='http://localhost')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Content-Language'], html_lang)
                html = response.get_data(as_text=True)
                self.assertIn('<html lang="{}">'.format(html_lang), html)
                self.assertIn(title_term, html)
                self.assertIn(intent_term, html)
                self.assertIn(disclaimer_term, html)
                self.assertIn(feature_term, html)
                self.assertIn('<div class="initial-loader-title">Taiko Web</div>', html)
                description_match = re.search(
                    r'<meta name="description" content="([^"]*)">',
                    html,
                )
                self.assertIsNotNone(description_match)
                description = description_match.group(1)
                self.assertIn(title_term.casefold(), description.casefold())
                self.assertIn(feature_term.casefold(), description.casefold())
                self.assertIn(
                    '<link rel="canonical" href="https://taiko.asia/{}">'.format(code),
                    html,
                )
                for hreflang in ('ja', 'en', 'zh-Hans', 'zh-Hant', 'ko', 'x-default'):
                    self.assertIn('hreflang="{}"'.format(hreflang), html)

                schema_match = re.search(
                    r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
                    html,
                    re.DOTALL,
                )
                self.assertIsNotNone(schema_match)
                schema = json.loads(schema_match.group(1))
                self.assertEqual(schema['name'], 'Taiko Web')
                self.assertEqual(schema['inLanguage'], html_lang)
                self.assertTrue(schema['isAccessibleForFree'])
                self.assertEqual(schema['offers']['price'], '0')
                self.assertIn(disclaimer_term, schema['disambiguatingDescription'])
                self.assertIn(feature_term, schema['featureList'])
                self.assertEqual(len(schema['featureList']), 5)

    def test_sitemap_contains_reciprocal_language_alternates(self):
        response = self.client.get('/sitemap.xml', base_url='http://localhost')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith('application/xml'))
        root = ET.fromstring(response.data)
        ns = {
            'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
            'xhtml': 'http://www.w3.org/1999/xhtml',
        }
        urls = root.findall('sm:url', ns)
        self.assertEqual(len(urls), len(taiko.SEO_LANGUAGES))
        expected_locations = {
            'https://taiko.asia/' + code for code in taiko.SEO_LANGUAGES
        }
        self.assertEqual(
            {url.find('sm:loc', ns).text for url in urls},
            expected_locations,
        )
        for url in urls:
            alternates = url.findall('xhtml:link', ns)
            self.assertEqual(len(alternates), len(taiko.SEO_LANGUAGES) + 1)
            self.assertEqual(
                {link.attrib['hreflang'] for link in alternates},
                {'ja', 'en', 'zh-Hans', 'zh-Hant', 'ko', 'x-default'},
            )

    def test_robots_points_to_https_sitemap(self):
        response = self.client.get('/robots.txt', base_url='http://localhost')
        self.assertEqual(response.status_code, 200)
        robots = response.get_data(as_text=True)
        self.assertIn('Allow: /', robots)
        self.assertIn('Disallow: /admin', robots)
        self.assertIn('Sitemap: https://taiko.asia/sitemap.xml', robots)

    def test_language_aliases_redirect_permanently(self):
        for alias, canonical in (('jp', 'ja'), ('zh-cn', 'cn'), ('zh-tw', 'tw')):
            with self.subTest(alias=alias):
                response = self.client.get('/' + alias)
                self.assertEqual(response.status_code, 301)
                self.assertTrue(response.headers['Location'].endswith('/' + canonical))


if __name__ == '__main__':
    unittest.main()
