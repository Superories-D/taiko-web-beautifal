import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import multiplayer


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.body = body if body is not None else {'status': 'ok', 'connections': 0, 'accepting_connections': True}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class MultiplayerNodeTests(unittest.TestCase):
    def test_canonical_websocket_and_health_urls(self):
        self.assertEqual(
            multiplayer.normalise_websocket_url(' WSS://Play.Example.com:444/ '),
            'wss://play.example.com:444'
        )
        self.assertEqual(
            multiplayer.health_url_for_websocket('wss://play.example.com:444'),
            'https://play.example.com:444/health'
        )

    def test_rejects_local_and_path_based_node_urls(self):
        for value in ('ws://localhost:34802', 'ws://127.0.0.1:34802', 'https://play.example.com', 'wss://play.example.com/socket'):
            with self.subTest(value=value), self.assertRaises(multiplayer.MultiplayerServerValidationError):
                multiplayer.normalise_websocket_url(value)

    @patch('multiplayer.assert_public_resolution')
    @patch('multiplayer.requests.get')
    def test_health_requires_a_valid_ok_response(self, request_get, _resolution):
        request_get.return_value = FakeResponse()
        self.assertTrue(multiplayer.probe_health('wss://play.example.com')['online'])

        request_get.return_value = FakeResponse(body={'status': 'starting'})
        result = multiplayer.probe_health('wss://play.example.com')
        self.assertFalse(result['online'])
        self.assertIn('invalid response', result['error'])

        request_get.return_value = FakeResponse(body={'status': 'ok'})
        result = multiplayer.probe_health('wss://play.example.com')
        self.assertFalse(result['online'])
        self.assertIn('connection count', result['error'])

    def test_assignment_is_stable_and_uses_all_healthy_nodes(self):
        servers = [
            {'node_id': 'bbbbbbbbbbbb', 'ws_url': 'wss://b.example'},
            {'node_id': 'aaaaaaaaaaaa', 'ws_url': 'wss://a.example'}
        ]
        first = multiplayer.select_server(servers, 'browser-id')
        second = multiplayer.select_server(list(reversed(servers)), 'browser-id')
        self.assertEqual(first['node_id'], second['node_id'])
        self.assertIsNone(multiplayer.select_server([], 'browser-id'))

    def test_assignment_prefers_available_capacity_before_latency(self):
        selected = multiplayer.select_server([
            {
                'node_id': 'aaaaaaaaaaaa',
                'max_connections': 10,
                'last_health': {'connections': 9, 'latency_ms': 10}
            },
            {
                'node_id': 'bbbbbbbbbbbb',
                'max_connections': 10,
                'last_health': {'connections': 1, 'latency_ms': 180}
            }
        ], 'browser-id')
        self.assertEqual(selected['node_id'], 'bbbbbbbbbbbb')


if __name__ == '__main__':
    unittest.main()
