"""Validation, health probing, and deterministic selection for multiplayer nodes."""

import hashlib
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit, urlunsplit

import urllib3


class MultiplayerServerValidationError(ValueError):
    """Raised when a configured multiplayer server is not safe to use."""


def _normalise_host(hostname):
    if not hostname:
        raise MultiplayerServerValidationError('A hostname is required.')
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname.lower() == 'localhost' or '.' not in hostname:
            raise MultiplayerServerValidationError('Use a public hostname, not a local hostname.')
        try:
            return hostname.encode('idna').decode('ascii').lower()
        except UnicodeError as exc:
            raise MultiplayerServerValidationError('The hostname is invalid.') from exc
    if not ip.is_global:
        raise MultiplayerServerValidationError('Use a publicly routable IP address.')
    return ip.compressed


def normalise_websocket_url(value):
    """Return a canonical public websocket origin for a node."""
    if not isinstance(value, str) or not value.strip():
        raise MultiplayerServerValidationError('A WebSocket URL is required.')
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise MultiplayerServerValidationError('The WebSocket URL has an invalid port.') from exc

    if parsed.scheme not in ('ws', 'wss'):
        raise MultiplayerServerValidationError('The WebSocket URL must use ws:// or wss://.')
    if parsed.username or parsed.password:
        raise MultiplayerServerValidationError('The WebSocket URL must not contain credentials.')
    if parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise MultiplayerServerValidationError('The WebSocket URL must be an origin without a path or query string.')

    hostname = _normalise_host(parsed.hostname)
    display_host = '[{}]'.format(hostname) if ':' in hostname else hostname
    netloc = display_host if port is None else '{}:{}'.format(display_host, port)
    return urlunsplit((parsed.scheme, netloc, '', '', ''))


def health_url_for_websocket(websocket_url):
    parsed = urlsplit(normalise_websocket_url(websocket_url))
    scheme = 'https' if parsed.scheme == 'wss' else 'http'
    return urlunsplit((scheme, parsed.netloc, '/health', '', ''))


def assert_public_resolution(url):
    """Reject hostnames that currently resolve to local or reserved addresses."""
    hostname = urlsplit(url).hostname
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise MultiplayerServerValidationError('The server hostname could not be resolved.') from exc
    if not addresses:
        raise MultiplayerServerValidationError('The server hostname did not resolve to an address.')
    public_addresses = []
    for address in addresses:
        resolved = ipaddress.ip_address(address[4][0])
        if not resolved.is_global:
            raise MultiplayerServerValidationError('The server hostname resolved to a non-public address.')
        if resolved.compressed not in public_addresses:
            public_addresses.append(resolved.compressed)
    return public_addresses


def fetch_health_json(health_url, resolved_ip, timeout):
    """Fetch /health through a DNS-pinned public IP with normal TLS hostname checks."""
    parsed = urlsplit(health_url)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    request_timeout = urllib3.Timeout(connect=timeout[0], read=timeout[1])
    headers = {
        'Host': parsed.netloc,
        'Accept': 'application/json',
        'User-Agent': 'Taiko-Web-Multiplayer-Health/1.0'
    }
    pool_options = {
        'timeout': request_timeout,
        'retries': False,
        'maxsize': 1,
        'block': True
    }
    if parsed.scheme == 'https':
        pool = urllib3.HTTPSConnectionPool(
            resolved_ip,
            port,
            assert_hostname=parsed.hostname,
            server_hostname=parsed.hostname,
            ssl_context=ssl.create_default_context(),
            **pool_options
        )
    else:
        pool = urllib3.HTTPConnectionPool(resolved_ip, port, **pool_options)

    response = None
    try:
        response = pool.request(
            'GET',
            parsed.path or '/health',
            headers=headers,
            redirect=False,
            preload_content=False
        )
        body = response.read(65537)
        if len(body) > 65536:
            raise MultiplayerServerValidationError('Health endpoint response is too large.')
        try:
            data = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        return response.status, data
    finally:
        if response is not None:
            response.release_conn()
        pool.close()


def probe_health(websocket_url, timeout=(1.5, 2.5)):
    """Probe a node without following redirects and return a serialisable result."""
    started = time.monotonic()
    try:
        health_url = health_url_for_websocket(websocket_url)
        resolved_addresses = assert_public_resolution(health_url)
        status_code, data = fetch_health_json(health_url, resolved_addresses[0], timeout)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if status_code != 200:
            return {'online': False, 'latency_ms': elapsed_ms, 'error': 'Health endpoint returned HTTP {}.'.format(status_code)}
        if not isinstance(data, dict) or data.get('status') != 'ok':
            return {'online': False, 'latency_ms': elapsed_ms, 'error': 'Health endpoint returned an invalid response.'}
        connections = data.get('connections')
        max_connections = data.get('max_connections')
        accepting_connections = data.get('accepting_connections')
        if isinstance(connections, bool) or not isinstance(connections, int) or connections < 0:
            return {'online': False, 'latency_ms': elapsed_ms, 'error': 'Health endpoint returned an invalid connection count.'}
        if max_connections is not None and (isinstance(max_connections, bool) or not isinstance(max_connections, int) or max_connections < 1):
            return {'online': False, 'latency_ms': elapsed_ms, 'error': 'Health endpoint returned an invalid capacity.'}
        if accepting_connections is not None and not isinstance(accepting_connections, bool):
            return {'online': False, 'latency_ms': elapsed_ms, 'error': 'Health endpoint returned an invalid admission state.'}
        return {
            'online': True,
            'latency_ms': elapsed_ms,
            'connections': connections,
            'reported_max_connections': max_connections,
            'accepting_connections': accepting_connections is not False,
            'error': None
        }
    except (MultiplayerServerValidationError, urllib3.exceptions.HTTPError, OSError, ssl.SSLError) as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {'online': False, 'latency_ms': elapsed_ms, 'error': str(exc) or 'Health check failed.'}


def select_server(servers, client_id):
    """Balance healthy nodes by capacity utilisation, then health-check latency."""
    if not servers:
        return None
    client_key = client_id or ''

    def score(server):
        health = server.get('last_health') or {}
        capacity = max(1, int(server.get('max_connections') or 1))
        connections = max(0, int(health.get('connections') or 0))
        utilisation_score = min(1, connections / capacity) * 800
        latency_score = min(800, max(0, int(health.get('latency_ms') or 800)))
        tie_breaker = int.from_bytes(
            hashlib.sha256((client_key + ':' + server['node_id']).encode('utf-8')).digest()[:2],
            'big'
        ) / 65535
        return utilisation_score + latency_score + tie_breaker

    return min(servers, key=lambda server: (score(server), server['node_id']))
