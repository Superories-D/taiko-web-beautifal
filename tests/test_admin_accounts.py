import unittest
from unittest.mock import MagicMock, patch

import bcrypt
from flask.sessions import SecureCookieSessionInterface

import app as taiko


class AdminAccountHelpersTest(unittest.TestCase):
    def test_manage_permissions_are_strict_and_exclude_self(self):
        admin = {'username': 'Root', 'user_level': 50}
        self.assertTrue(taiko.admin_can_manage_user(admin, {
            'username': 'Player', 'user_level': 49
        }))
        self.assertFalse(taiko.admin_can_manage_user(admin, {
            'username': 'Peer', 'user_level': 50
        }))
        self.assertFalse(taiko.admin_can_manage_user(admin, {
            'username': 'Root', 'user_level': 1
        }))

    def test_account_cleanup_removes_private_data_and_anonymizes_public_history(self):
        fake_db = MagicMock()
        fake_db.users.delete_one.return_value.deleted_count = 1
        with patch.object(taiko, 'db', fake_db):
            result = taiko.remove_user_account_data('Player')

        self.assertEqual(result.deleted_count, 1)
        fake_db.scores.delete_many.assert_called_once_with({'username': 'Player'})
        fake_db.weekly_challenge_scores.delete_many.assert_called_once_with({'username': 'Player'})
        fake_db.site_message_reads.delete_many.assert_called_once_with({'username': 'Player'})
        fake_db.visit_records.delete_many.assert_called_once_with({'username': 'Player'})
        fake_db.play_records.update_many.assert_called_once_with(
            {'username': 'Player'}, {'$set': {'username': None}}
        )
        fake_db.board_posts.update_many.assert_called_once_with(
            {'username': 'Player'},
            {
                '$set': {'username': None, 'user_display_name': 'Deleted user'},
                '$unset': {'ip_hash': ''}
            }
        )
        fake_db.users.delete_one.assert_called_once_with({'username': 'Player'})


class AdminAccountRoutesTest(unittest.TestCase):
    def setUp(self):
        self.original_csrf = taiko.app.config.get('WTF_CSRF_ENABLED', True)
        self.original_limiter = taiko.limiter.enabled
        self.original_session_interface = taiko.app.session_interface
        taiko.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        taiko.limiter.enabled = False
        taiko.app.session_interface = SecureCookieSessionInterface()
        self.admin = {
            '_id': 'admin-id',
            'username': 'Root',
            'username_lower': 'root',
            'user_level': 50,
            'session_id': 'admin-session'
        }
        self.target = {
            '_id': 'target-id',
            'username': 'Player',
            'username_lower': 'player',
            'user_level': 1,
            'password': b'PASSWORD-HASH-MUST-NOT-RENDER',
            'session_id': 'TARGET-SESSION-MUST-NOT-RENDER'
        }
        self.fake_db = MagicMock()
        self.fake_db.users.update_one.return_value.matched_count = 1

        def find_user(query, projection=None):
            if query.get('session_id') == 'admin-session':
                return self.admin
            if query.get('username') == 'Root':
                return self.admin
            if query.get('username_lower') == 'player':
                return self.target
            return None

        self.fake_db.users.find_one.side_effect = find_user
        self.db_patch = patch.object(taiko, 'db', self.fake_db)
        self.db_patch.start()
        self.csrf_patch = patch.object(taiko.csrf, 'protect')
        self.csrf_patch.start()
        self.client = taiko.app.test_client()
        with self.client.session_transaction() as session:
            session['username'] = 'Root'
            session['session_id'] = 'admin-session'

    def tearDown(self):
        self.csrf_patch.stop()
        self.db_patch.stop()
        taiko.limiter.enabled = self.original_limiter
        taiko.app.session_interface = self.original_session_interface
        taiko.app.config['WTF_CSRF_ENABLED'] = self.original_csrf

    def route(self, suffix):
        return '{}admin/users/Player{}'.format(taiko.basedir, suffix)

    def test_password_reset_hashes_password_and_rotates_session(self):
        response = self.client.post(self.route('/password'), data={
            'new_password': 'fresh-pass',
            'confirm_password': 'fresh-pass'
        })
        self.assertEqual(response.status_code, 302)
        update = self.fake_db.users.update_one.call_args.args[1]['$set']
        self.assertTrue(bcrypt.checkpw(b'fresh-pass', update['password']))
        self.assertEqual(len(update['session_id']), 48)
        self.assertNotEqual(update['session_id'], 'admin-session')
        self.assertIn('password_changed_at', update)

    def test_account_detail_does_not_render_secrets(self):
        response = self.client.get(self.route(''))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'PASSWORD-HASH-MUST-NOT-RENDER', response.data)
        self.assertNotIn(b'TARGET-SESSION-MUST-NOT-RENDER', response.data)
        self.assertIn(b'Account data', response.data)

    def test_password_reset_rejects_mismatch(self):
        response = self.client.post(self.route('/password'), data={
            'new_password': 'fresh-pass',
            'confirm_password': 'different-pass'
        })
        self.assertEqual(response.status_code, 302)
        self.fake_db.users.update_one.assert_not_called()

    def test_equal_level_target_is_forbidden(self):
        self.target['user_level'] = 50
        response = self.client.post(self.route('/password'), data={
            'new_password': 'fresh-pass',
            'confirm_password': 'fresh-pass'
        })
        self.assertEqual(response.status_code, 403)
        self.fake_db.users.update_one.assert_not_called()

    def test_delete_requires_exact_username(self):
        response = self.client.post(self.route('/delete'), data={
            'confirm_username': 'player'
        })
        self.assertEqual(response.status_code, 302)
        self.fake_db.users.delete_one.assert_not_called()
        self.fake_db.scores.delete_many.assert_not_called()


if __name__ == '__main__':
    unittest.main()
