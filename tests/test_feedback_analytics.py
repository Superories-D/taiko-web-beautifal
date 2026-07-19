import unittest
from functools import wraps
from unittest.mock import MagicMock

from flask import Flask, jsonify, session

import schema
from feedback_analytics import register_feedback_analytics_routes


class NoopLimiter:
    def limit(self, _value):
        def decorate(func):
            return func
        return decorate


class FeedbackAnalyticsRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test-secret'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.db = MagicMock()
        self.song = {
            '_id': 'song-id', 'id': 'chart-1', 'hash': 'chart-hash',
            'title': 'Test chart', 'enabled': True,
            'courses': {'oni': {'stars': 8}},
        }
        self.db.performance_runs.find_one.return_value = {'_id': 'run'}
        self.db.chart_ratings.find_one.return_value = None
        self.db.chart_ratings.find.return_value = []
        self.db.chart_rating_summaries.find_one.return_value = None
        self.db.chart_reports.find_one.return_value = None
        self.db.performance_runs.update_one.return_value.upserted_id = 'run-id'

        def login_required(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                if not session.get('username'):
                    return jsonify({'status': 'error', 'message': 'not_logged_in'})
                return func(*args, **kwargs)
            return wrapped

        register_feedback_analytics_routes(
            self.app, self.db, NoopLimiter(), MagicMock(), '/', login_required,
            lambda _hash: self.song, schema,
        )
        self.client = self.app.test_client()

    def login(self):
        with self.client.session_transaction() as current:
            current['username'] = 'player'

    def test_summary_is_public_and_rating_requires_completed_run(self):
        response = self.client.get('/api/chart-feedback?hash=chart-hash&difficulty=oni')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['summary']['rating_count'], 0)
        self.login()
        response = self.client.put('/api/chart-feedback/rating', json={
            'song_hash': 'chart-hash', 'difficulty': 'oni', 'stars': 5,
        })
        self.assertEqual(response.status_code, 200)
        self.db.chart_ratings.update_one.assert_called_once()

    def test_rating_is_rejected_without_an_eligible_standard_run(self):
        self.login()
        self.db.performance_runs.find_one.return_value = None
        response = self.client.put('/api/chart-feedback/rating', json={
            'song_hash': 'chart-hash', 'difficulty': 'oni', 'stars': 5,
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json['message'], 'play_required')
        self.db.chart_ratings.update_one.assert_not_called()

    def test_performance_run_rejects_bucket_total_mismatch(self):
        self.login()
        response = self.client.post('/api/performance/runs', json={
            'run_id': 'a' * 32, 'song_hash': 'chart-hash', 'difficulty': 'oni',
            'score': 100, 'good': 2, 'ok': 0, 'bad': 0, 'max_combo': 2,
            'drumroll': 0, 'gauge': 100, 'rule_version': 'standard-v1',
            'buckets': [{
                'start_ms': 0, 'end_ms': 1000, 'good': 1, 'ok': 0, 'bad': 0,
                'offset_sum_ms': 0, 'offset_count': 1,
            }],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['message'], 'invalid_bucket_totals')
        self.db.performance_runs.update_one.assert_not_called()

    def test_performance_run_rejects_reused_id_for_another_chart(self):
        self.login()
        self.db.performance_runs.find_one.return_value = {
            'song_hash': 'another-chart', 'difficulty': 'oni',
        }
        response = self.client.post('/api/performance/runs', json={
            'run_id': 'b' * 32, 'song_hash': 'chart-hash', 'difficulty': 'oni',
            'score': 100, 'good': 1, 'ok': 0, 'bad': 0, 'max_combo': 1,
            'drumroll': 0, 'gauge': 100, 'rule_version': 'standard-v1',
            'buckets': [{
                'start_ms': 0, 'end_ms': 1000, 'good': 1, 'ok': 0, 'bad': 0,
                'offset_sum_ms': 0, 'offset_count': 1,
            }],
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['message'], 'run_id_conflict')
        self.db.performance_runs.update_one.assert_not_called()

    def test_history_rejects_invalid_filters(self):
        self.login()
        bad_limit = self.client.get('/api/performance/history?limit=abc')
        self.assertEqual(bad_limit.status_code, 400)
        self.assertEqual(bad_limit.json['message'], 'invalid_limit')
        bad_difficulty = self.client.get('/api/performance/history?difficulty=expert')
        self.assertEqual(bad_difficulty.status_code, 400)
        self.assertEqual(bad_difficulty.json['message'], 'invalid_difficulty')

    def test_report_is_idempotent_for_open_same_reason(self):
        self.login()
        payload = {
            'song_hash': 'chart-hash', 'difficulty': 'oni',
            'reason': 'audio_sync', 'position_ms': 1200,
            'description': 'The chorus is early.',
        }
        first = self.client.post('/api/chart-feedback/reports', json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json['created'])
        self.db.chart_reports.find_one.return_value = {'report_id': first.json['report_id']}
        second = self.client.post('/api/chart-feedback/reports', json=payload)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json['created'])
        self.assertTrue(self.db.chart_reports.update_one.called)


if __name__ == '__main__':
    unittest.main()
