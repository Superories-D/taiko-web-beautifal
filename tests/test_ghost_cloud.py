import base64
import json
import unittest
from unittest.mock import MagicMock, patch

import app as taiko
from flask.sessions import SecureCookieSessionInterface


class GhostCloudPayloadTest(unittest.TestCase):
    def test_payload_is_gzip_encoded_and_round_trips(self):
        source = {
            'version': 1,
            'events': [{'t': index * 120, 'j': index % 3, 'p': index * 450} for index in range(30)],
            'points': 13050,
        }
        encoded = taiko.encode_ghost_payload(source)
        self.assertLess(len(base64.b64decode(encoded)), len(json.dumps(source).encode('utf-8')))
        self.assertEqual(taiko.decode_ghost_payload(encoded), source)

    def test_payload_validation_rejects_invalid_judgement(self):
        invalid = taiko.encode_ghost_payload({
            'events': [{'t': 1, 'j': 9, 'p': 0}],
            'points': 0,
        })
        with self.assertRaises(ValueError):
            taiko.decode_ghost_payload(invalid)

    def test_ghost_cutoff_is_thirty_days(self):
        now = taiko.datetime(2026, 7, 15)
        self.assertEqual((now - taiko.ghost_cutoff(now)).days, 30)


class GhostCloudRouteTest(unittest.TestCase):
    def test_logged_in_save_uses_the_new_endpoint(self):
        original_csrf = taiko.app.config.get('WTF_CSRF_ENABLED', True)
        original_session_interface = taiko.app.session_interface
        taiko.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        taiko.app.session_interface = SecureCookieSessionInterface()
        fake_db = MagicMock()
        fake_db.ghost_records.find_one.return_value = None
        source = {'events': [{'t': 100, 'j': 2, 'p': 450}], 'points': 450}
        try:
            with patch.object(taiko, 'db', fake_db), taiko.app.test_client() as client:
                with client.session_transaction() as session:
                    session['username'] = 'Player'
                response = client.post('/api/ghost', json={
                    'hash': 'song-hash',
                    'difficulty': 'oni',
                    'encoding': 'gzip',
                    'payload': taiko.encode_ghost_payload(source),
                })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()['saved'])
            fake_db.ghost_records.update_one.assert_called_once()
            self.assertEqual(fake_db.ghost_records.update_one.call_args.args[0]['difficulty'], 'oni')
        finally:
            taiko.app.config['WTF_CSRF_ENABLED'] = original_csrf
            taiko.app.session_interface = original_session_interface
