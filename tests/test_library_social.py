import unittest
from unittest.mock import MagicMock, patch

import app as taiko
import schema
from flask.sessions import SecureCookieSessionInterface
from tjaf import Tja


class LibrarySocialContractTest(unittest.TestCase):
    def test_new_routes_are_registered(self):
        rules = {rule.rule for rule in taiko.app.url_map.iter_rules()}
        self.assertIn('/api/library/favorites', rules)
        self.assertIn('/api/library/playlists', rules)
        self.assertIn('/api/social/follow/<public_id>', rules)
        self.assertIn('/api/social/blocked', rules)
        self.assertIn('/api/challenges/<challenge_id>/result', rules)

    def test_contract_schemas_reject_extra_fields(self):
        self.assertTrue(schema.validate({
            'recipient_public_id': 'a' * 32,
            'song_hash': 'song',
            'difficulty': 'oni',
            'rule_version': 'standard-v1',
        }, schema.challenge_create))
        self.assertFalse(schema.validate({
            'recipient_public_id': 'a' * 32,
            'song_hash': 'song',
            'difficulty': 'oni',
            'rule_version': 'standard-v1',
            'username': 'secret',
        }, schema.challenge_create))

    def test_tja_ingest_exposes_bpm_range(self):
        tja = Tja('\n'.join([
            'TITLE:Test',
            'BPM:120',
            'COURSE:Oni',
            'LEVEL:8',
            '#START',
            '#BPMCHANGE:180',
            '1111,',
            '#END',
        ]))
        document = tja.to_mongo('song', 1)
        self.assertEqual(document['bpm_min'], 120)
        self.assertEqual(document['bpm_max'], 180)

    def test_tja_ingest_accepts_space_bpmchange_and_ignores_invalid_values(self):
        tja = Tja('BPM:100\n#BPMCHANGE 240\n#BPMCHANGE 0\n#BPMCHANGE 1200')
        document = tja.to_mongo('song', 1)
        self.assertEqual(document['bpm_min'], 100)
        self.assertEqual(document['bpm_max'], 240)


class LibrarySocialRouteTest(unittest.TestCase):
    def setUp(self):
        self.original_csrf = taiko.app.config.get('WTF_CSRF_ENABLED', True)
        self.original_session_interface = taiko.app.session_interface
        taiko.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        taiko.app.session_interface = SecureCookieSessionInterface()
        self.db = MagicMock()
        self.db.users.find_one.return_value = {
            'username': 'Player',
            'display_name': 'Player',
            'public_id': 'a' * 32,
            '_id': 'player-id',
        }

    def tearDown(self):
        taiko.app.config['WTF_CSRF_ENABLED'] = self.original_csrf
        taiko.app.session_interface = self.original_session_interface

    def client(self):
        return taiko.app.test_client()

    def test_private_library_requires_login(self):
        with patch.object(taiko.db, 'users', self.db.users), self.client() as client:
            response = client.get('/api/library/favorites')
        self.assertEqual(response.get_json()['message'], 'not_logged_in')

    def test_favorite_write_validates_enabled_song_and_uses_user_scope(self):
        self.db.songs.find_one.return_value = {
            'id': 1,
            'hash': 'song-hash',
            'title': 'Song',
            'enabled': True,
            'courses': {'oni': {'stars': 8, 'branch': False}},
        }
        with patch.object(taiko.db, 'users', self.db.users), \
             patch.object(taiko.db, 'songs', self.db.songs), \
             patch.object(taiko.db, 'song_favorites', self.db.song_favorites), self.client() as client:
            with client.session_transaction() as session:
                session['username'] = 'Player'
            response = client.post('/api/library/favorites', json={'song_hash': 'song-hash'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['favorite'])
        self.db.song_favorites.update_one.assert_called_once()
        query = self.db.song_favorites.update_one.call_args.args[0]
        self.assertEqual(query['username'], 'Player')
        self.assertEqual(query['song_hash'], 'song-hash')

    def test_private_playlists_omit_share_token_for_sparse_unique_index(self):
        self.db.song_playlists.count_documents.return_value = 0
        with patch.object(taiko.db, 'users', self.db.users), \
             patch.object(taiko.db, 'song_playlists', self.db.song_playlists), self.client() as client:
            with client.session_transaction() as session:
                session['username'] = 'Player'
            response = client.post('/api/library/playlists', json={
                'name': 'Private list',
                'description': '',
                'song_hashes': [],
            })
        self.assertEqual(response.status_code, 201)
        inserted = self.db.song_playlists.insert_one.call_args.args[0]
        self.assertNotIn('share_token', inserted)

    def test_unshare_unsets_token_instead_of_storing_null(self):
        playlist = {
            '_id': 'playlist-db-id',
            'playlist_id': 'b' * 32,
            'owner_username': 'Player',
            'name': 'Shared list',
            'description': '',
            'song_hashes': [],
            'visibility': 'shared',
            'share_token': 'shared-token-value-long-enough',
        }
        self.db.song_playlists.find_one.return_value = playlist
        with patch.object(taiko.db, 'users', self.db.users), \
             patch.object(taiko.db, 'song_playlists', self.db.song_playlists), self.client() as client:
            with client.session_transaction() as session:
                session['username'] = 'Player'
            response = client.delete('/api/library/playlists/' + ('b' * 32) + '/share')
        self.assertEqual(response.status_code, 200)
        update = self.db.song_playlists.update_one.call_args.args[1]
        self.assertEqual(update['$unset'], {'share_token': ''})
        self.assertNotIn('share_token', update['$set'])
