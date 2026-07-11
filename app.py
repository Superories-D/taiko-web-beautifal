#!/usr/bin/env python3

import base64
import bcrypt
import hashlib
import ipaddress
try:
    import config
except ModuleNotFoundError:
    raise FileNotFoundError('No such file or directory: \'config.py\'. Copy the example config file config.example.py to config.py')
import json
import math
import re
import requests
import schema
import secrets
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pathlib
import shutil
from urllib.parse import quote, urlsplit
from flask_limiter import Limiter

import flask
import tjaf

# ----

from functools import wraps
from flask import Flask, jsonify, render_template, request, abort, redirect, session, flash, make_response, send_from_directory
from flask_caching import Cache
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
from cachelib.file import FileSystemCache
from ffmpy import FFmpeg, FFRuntimeError
from bson import ObjectId
from pymongo import MongoClient, ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError, PyMongoError
from redis import Redis
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


APP_ROOT = pathlib.Path(__file__).resolve().parent
PUBLIC_DIR = APP_ROOT / 'public'
FRONTEND_ASSET_VERSION = os.environ.get('TAIKO_WEB_ASSET_VERSION', '20260711.1')


def utc_now():
    """Return a naive UTC datetime for MongoDB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def path_from_env(name, default):
    return pathlib.Path(os.environ.get(name, str(default))).resolve()


SONGS_DIR = path_from_env('TAIKO_WEB_SONGS_DIR', APP_ROOT / 'public' / 'songs')
NOTICE_UPLOADS_DIR = path_from_env('TAIKO_WEB_NOTICE_UPLOADS_DIR', APP_ROOT / 'public' / 'notice_uploads')


def take_config(name, required=False):
    if hasattr(config, name):
        return getattr(config, name)
    elif required:
        raise ValueError('Required option is not defined in the config.py file: {}'.format(name))
    else:
        return None


def env_flag(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ('0', 'false', 'no', 'off', '')


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def normalize_basedir(value):
    value = str(value or '/').strip().replace('\\', '/')
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('BASEDIR must be a URL path without a host, query, or fragment')
    parts = [part for part in parsed.path.split('/') if part]
    if any(part in ('.', '..') for part in parts):
        raise ValueError('BASEDIR cannot contain relative path segments')
    return '/' if not parts else '/{}/'.format('/'.join(parts))


def normalize_site_origin(value):
    value = str(value or '').strip().rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('TAIKO_WEB_SITE_ORIGIN must be an http(s) origin')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('TAIKO_WEB_SITE_ORIGIN cannot contain a path, query, or fragment')
    return '{}://{}'.format(parsed.scheme, parsed.netloc)


def redis_uri_from_config(redis_options):
    host = str(redis_options.get('CACHE_REDIS_HOST') or '127.0.0.1')
    if ':' in host and not host.startswith('['):
        host = '[{}]'.format(host)
    port = int(redis_options.get('CACHE_REDIS_PORT') or 6379)
    database = redis_options.get('CACHE_REDIS_DB')
    database = 0 if database is None else int(database)
    password = redis_options.get('CACHE_REDIS_PASSWORD')
    credentials = ':{}@'.format(quote(str(password), safe='')) if password else ''
    return 'redis://{}{}:{}/{}'.format(credentials, host, port, database)


def load_or_create_secret_key():
    configured_key = os.environ.get('TAIKO_WEB_SECRET_KEY') or take_config('SECRET_KEY')
    if (
        isinstance(configured_key, str) and
        configured_key != 'change-me' and
        len(configured_key) >= 32
    ):
        return configured_key

    secret_path = path_from_env(
        'TAIKO_WEB_SECRET_KEY_FILE',
        APP_ROOT / '.taiko-secret-key'
    )
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w', encoding='ascii') as secret_file:
            secret_file.write(secrets.token_hex(32))
            secret_file.flush()
            os.fsync(secret_file.fileno())

    for _ in range(50):
        try:
            secret_key = secret_path.read_text(encoding='ascii').strip()
        except OSError:
            time.sleep(0.02)
            continue
        if len(secret_key) >= 32:
            return secret_key
        time.sleep(0.02)
    raise RuntimeError(
        'Set TAIKO_WEB_SECRET_KEY to at least 32 characters'
    )


app = Flask(__name__)
FEATURE_ADMIN = env_flag('TAIKO_WEB_FEATURE_ADMIN', True)
FEATURE_SITE_MESSAGES = env_flag('TAIKO_WEB_FEATURE_SITE_MESSAGES', True)
FEATURE_TOP_SONGS = env_flag('TAIKO_WEB_FEATURE_TOP_SONGS', True)
SONG_TYPES = [
    "01 Pop",
    "02 Anime",
    "03 Vocaloid",
    "04 Children and Folk",
    "05 Variety",
    "06 Classical",
    "07 Game Music",
    "08 Live Festival Mode",
    "09 Namco Original",
    "10 Taiko Towers",
    "11 Dan Dojo",
    "12 Custom",
]
CUSTOM_CATEGORY = {
    "id": 12,
    "title": "12 Custom",
    "title_lang": {
        "ja": "カスタム",
        "en": "Custom",
        "cn": "自定义",
        "tw": "自訂",
        "ko": "커스텀",
    },
    "song_skin": {
        "sort": 12,
        "background": "#2fb7ac",
        "border": ["#a8fff2", "#08736f"],
        "outline": "#07585f",
        "info_fill": "#07585f",
    },
    "aliases": ["custom", "user upload", "upload", "自定义", "自訂", "カスタム", "커스텀"],
}

redis_config = dict(take_config('REDIS', required=True))
redis_config['CACHE_REDIS_HOST'] = os.environ.get("TAIKO_WEB_REDIS_HOST") or redis_config['CACHE_REDIS_HOST']
redis_uri = os.environ.get('REDIS_URI') or redis_uri_from_config(redis_config)
redis_client = Redis.from_url(
    redis_uri,
    socket_connect_timeout=1,
    socket_timeout=1
)
try:
    redis_client.ping()
    redis_available = True
except Exception:
    redis_available = False
limiter_storage_uri = redis_uri if redis_available else "memory://"

# Only these reverse proxies may supply the client IP used for rate limiting.
CLOUDFLARE_PROXY_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22',
        '103.31.4.0/22', '141.101.64.0/18', '108.162.192.0/18',
        '190.93.240.0/20', '188.114.96.0/20', '197.234.240.0/22',
        '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
        '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
        '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32',
        '2405:b500::/32', '2405:8100::/32', '2a06:98c0::/29',
        '2c0f:f248::/32'
    )
)


def get_remote_address() -> str:
    remote_address = flask.request.remote_addr or '127.0.0.1'
    connecting_address = flask.request.headers.get('CF-Connecting-IP')
    if not connecting_address:
        return remote_address
    try:
        remote_ip = ipaddress.ip_address(remote_address)
        connecting_ip = ipaddress.ip_address(connecting_address)
    except ValueError:
        return remote_address
    if any(remote_ip in network for network in CLOUDFLARE_PROXY_NETWORKS):
        return str(connecting_ip)
    return remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    # default_limits=[],
    # storage_uri="memory://",
    # Redis
    storage_uri=limiter_storage_uri,
    # Redis cluster
    # storage_uri="redis+cluster://localhost:7000,localhost:7001,localhost:70002",
    # Memcached
    # storage_uri="memcached://localhost:11211",
    # Memcached Cluster
    # storage_uri="memcached://localhost:11211,localhost:11212,localhost:11213",
    # MongoDB
    # storage_uri="mongodb://localhost:27017",
    # Etcd
    # storage_uri="etcd://localhost:2379",
    strategy="fixed-window", # or "moving-window"
)

mongo_config = take_config('MONGO', required=True)
client = MongoClient(host=os.environ.get("TAIKO_WEB_MONGO_HOST") or mongo_config['host'])
basedir = normalize_basedir(
    os.environ.get('TAIKO_WEB_BASEDIR') or take_config('BASEDIR') or '/'
)
site_origin = normalize_site_origin(
    os.environ.get('TAIKO_WEB_SITE_ORIGIN') or take_config('SITE_ORIGIN')
)
SEO_DEFAULT_LANG = 'ja'
SEO_LANGUAGES = {
    'ja': {
        'html_lang': 'ja',
        'hreflang': 'ja',
        'title': 'Taiko Web | ブラウザ太鼓リズムゲーム',
        'description': 'Taiko Webで太鼓リズム譜面をブラウザですぐにプレイ。曲検索、カスタムTJA譜面、キーボード・タッチ・コントローラー操作に対応。',
        'keywords': '太鼓, 太鼓ウェブ, 太鼓の達人, リズムゲーム, ブラウザゲーム, HTML5ゲーム, TJA, カスタム曲, オンライン太鼓',
    },
    'en': {
        'html_lang': 'en',
        'hreflang': 'en',
        'title': 'Taiko Web | Browser Rhythm Game Simulator',
        'description': 'Play Taiko Web, a fast HTML5 taiko rhythm game simulator for desktop, tablet, and mobile browsers. Search songs, import custom TJA charts, and play with keyboard, touch, or controllers.',
        'keywords': 'taiko, Taiko Web, Taiko no Tatsujin, rhythm game, browser game, HTML5 game, drum game, custom songs, TJA, online taiko',
    },
    'cn': {
        'html_lang': 'zh-Hans',
        'hreflang': 'zh-Hans',
        'title': 'Taiko Web | 浏览器太鼓节奏游戏',
        'description': '在浏览器中游玩 Taiko Web 太鼓节奏游戏，支持歌曲搜索、自定义 TJA 谱面、键盘、触控和手柄操作。',
        'keywords': '太鼓, 太鼓网页, 太鼓达人, 节奏游戏, 浏览器游戏, HTML5游戏, 鼓游戏, 自定义歌曲, TJA, 在线太鼓',
    },
    'tw': {
        'html_lang': 'zh-Hant',
        'hreflang': 'zh-Hant',
        'title': 'Taiko Web | 瀏覽器太鼓節奏遊戲',
        'description': '在瀏覽器中遊玩 Taiko Web 太鼓節奏遊戲，支援歌曲搜尋、自訂 TJA 譜面、鍵盤、觸控和控制器操作。',
        'keywords': '太鼓, 太鼓網頁, 太鼓達人, 節奏遊戲, 瀏覽器遊戲, HTML5遊戲, 鼓遊戲, 自訂歌曲, TJA, 線上太鼓',
    },
    'ko': {
        'html_lang': 'ko',
        'hreflang': 'ko',
        'title': 'Taiko Web | 브라우저 태고 리듬 게임',
        'description': '브라우저에서 Taiko Web 태고 리듬 게임을 플레이하세요. 곡 검색, 커스텀 TJA 채보, 키보드, 터치, 컨트롤러 조작을 지원합니다.',
        'keywords': '태고, Taiko Web, 태고의 달인, 리듬 게임, 브라우저 게임, HTML5 게임, 드럼 게임, 커스텀 곡, TJA, 온라인 태고',
    },
}
SEO_LANG_ALIASES = {
    'jp': 'ja',
    'zh': 'cn',
    'zh-cn': 'cn',
    'zh-hans': 'cn',
    'zh-sg': 'cn',
    'zh-tw': 'tw',
    'zh-hk': 'tw',
    'zh-hant': 'tw',
}

app.secret_key = load_or_create_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = env_flag('TAIKO_WEB_SESSION_COOKIE_SECURE', False)
if redis_available:
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis_client
    app.cache = Cache(app, config={
        'CACHE_TYPE': 'RedisCache',
        'CACHE_REDIS_URL': redis_uri
    })
else:
    app.config['SESSION_TYPE'] = 'cachelib'
    app.config['SESSION_CACHELIB'] = FileSystemCache(
        cache_dir=str(APP_ROOT / 'flask_session'),
        threshold=500
    )
    app.cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
sess = Session()
sess.init_app(app)
app.jinja_env.globals.setdefault('csrf_token', generate_csrf)
app.config['WTF_CSRF_CHECK_DEFAULT'] = False
csrf = CSRFProtect(app)

db = client[os.environ.get('TAIKO_WEB_MONGO_DATABASE') or mongo_config['database']]


def create_index_safely(collection, keys, **kwargs):
    try:
        return collection.create_index(keys, **kwargs)
    except PyMongoError as error:
        app.logger.warning(
            'Could not create MongoDB index on %s (%s): %s',
            collection.name,
            keys,
            error
        )
        return None


def drop_legacy_unique_index(collection, expected_keys):
    try:
        for name, details in collection.index_information().items():
            if details.get('key') == expected_keys and details.get('unique'):
                collection.drop_index(name)
    except PyMongoError as error:
        app.logger.warning(
            'Could not replace legacy MongoDB index on %s: %s',
            collection.name,
            error
        )


create_index_safely(db.users, 'username', unique=True)
create_index_safely(
    db.users,
    'username_lower',
    unique=True,
    partialFilterExpression={'username_lower': {'$type': 'string'}}
)
db.songs.create_index('id', unique=True)
db.songs.create_index('hash')
create_index_safely(
    db.songs,
    'hash',
    unique=True,
    partialFilterExpression={'hash': {'$type': 'string', '$gt': ''}},
    name='song_hash_unique'
)
db.songs.create_index('title')
db.songs.create_index('song_type')
db.scores.create_index('username')
create_index_safely(
    db.scores,
    [('username', 1), ('hash', 1)],
    unique=True,
    partialFilterExpression={
        'username': {'$type': 'string'},
        'hash': {'$type': 'string'}
    },
    name='score_username_hash_unique'
)
db.play_records.create_index('song_hash')
db.play_records.create_index('played_at')
db.play_records.create_index([('song_hash', 1), ('played_at', -1)])
db.play_records.create_index([('played_at', -1), ('song_hash', 1)])
db.song_play_counts.create_index([('play_count', -1), ('last_played_at', -1)])
db.leaderboard.create_index([('song_hash', 1), ('difficulty', 1), ('score_value', -1)])
db.leaderboard.create_index([('song_hash', 1), ('difficulty', 1), ('month', 1), ('score_value', -1)])
db.leaderboard.create_index('username')
db.site_messages.create_index([('active', 1), ('created_at', -1)])
db.site_message_reads.create_index([('username', 1), ('message_id', 1)], unique=True)
db.site_message_reads.create_index('message_id')
drop_legacy_unique_index(db.weekly_challenges, [('date_key', 1)])
drop_legacy_unique_index(
    db.weekly_challenge_scores,
    [('week_key', 1), ('username', 1)]
)
create_index_safely(
    db.weekly_challenges,
    'challenge_id',
    unique=True,
    partialFilterExpression={'challenge_id': {'$type': 'string'}}
)
create_index_safely(db.weekly_challenges, 'date_key')
create_index_safely(db.weekly_challenges, 'week_key')
create_index_safely(
    db.weekly_challenges,
    [('week_key', 1), ('canonical', 1)],
    unique=True,
    partialFilterExpression={'canonical': True},
    name='canonical_week_key_unique'
)
create_index_safely(
    db.weekly_challenge_scores,
    [('challenge_id', 1), ('username', 1)],
    unique=True,
    partialFilterExpression={
        'challenge_id': {'$type': 'string'},
        'username': {'$type': 'string'}
    },
    name='challenge_username_unique'
)
create_index_safely(
    db.weekly_challenge_scores,
    [('challenge_id', 1), ('score_value', -1), ('updated_at', 1)]
)
db.weekly_challenge_scores.create_index('week_start')
create_index_safely(
    db.seq,
    'name',
    unique=True,
    partialFilterExpression={'name': {'$type': 'string'}}
)
db.board_posts.create_index([('created_at', -1)])

VISIT_RETENTION_DAYS = 400
VISIT_RETENTION_SECONDS = VISIT_RETENTION_DAYS * 24 * 60 * 60
VISIT_ENTERED_AT_INDEX = 'entered_at_1'
PUBLIC_TOP_SONGS_CACHE_SECONDS = 30
PUBLIC_SONGS_CACHE_SECONDS = 15
PUBLIC_SONGS_CACHE_VERSION_KEY = 'public_songs_cache_version'
PUBLIC_SONGS_CACHE_BOOT_VERSION = str(time.time_ns())
ADMIN_STATS_MAX_TIME_MS = max(500, env_int('TAIKO_WEB_ADMIN_STATS_MAX_TIME_MS', 2000))
TOP_SONGS_CACHE_KEY = 'public_top_songs'
TOP_SONGS_REFRESH_LOCK_KEY = 'public_top_songs_refresh_lock'
TOP_SONGS_BACKFILL_KEY = 'song_play_counts_backfilled'
TOP_SONGS_CACHE_SCHEMA_VERSION = 3
TOP_SONGS_CACHE_DAYS = max(1, env_int('TAIKO_WEB_TOP_SONGS_CACHE_DAYS', 1))
TOP_SONGS_CACHE_MAX_ROWS = max(10, min(env_int('TAIKO_WEB_TOP_SONGS_CACHE_ROWS', 50), 200))
TOP_SONGS_REFRESH_LOCK_SECONDS = max(60, env_int('TAIKO_WEB_TOP_SONGS_REFRESH_LOCK_SECONDS', 900))
TOP_SONGS_SORT_MAX_TIME_MS = max(1000, env_int('TAIKO_WEB_TOP_SONGS_SORT_MAX_TIME_MS', 2000))
TOP_SONGS_BACKFILL_MAX_TIME_MS = max(1000, env_int('TAIKO_WEB_TOP_SONGS_BACKFILL_MAX_TIME_MS', 5000))
REMOTE_REQUEST_TIMEOUT = (3.05, 15)


def ensure_visit_record_indexes():
    try:
        for index in db.visit_records.list_indexes():
            if (
                index.get('name') == VISIT_ENTERED_AT_INDEX and
                index.get('expireAfterSeconds') != VISIT_RETENTION_SECONDS
            ):
                db.visit_records.drop_index(VISIT_ENTERED_AT_INDEX)
                break
        db.visit_records.create_index(
            [('entered_at', 1)],
            name=VISIT_ENTERED_AT_INDEX,
            expireAfterSeconds=VISIT_RETENTION_SECONDS
        )
        db.visit_records.create_index([('visitor_key', 1), ('entered_at', -1)])
    except Exception as e:
        print('Warning: failed to ensure visit record indexes: {}'.format(e))


ensure_visit_record_indexes()

SITE_MESSAGE_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
SITE_MESSAGE_MAX_IMAGE_BYTES = 5 * 1024 * 1024
SITE_MESSAGE_MAX_TITLE_LENGTH = 120
SITE_MESSAGE_MAX_BODY_LENGTH = 5000
SITE_MESSAGE_MAX_IMAGE_URL_LENGTH = 1000
UPLOAD_TJA_MAX_BYTES = max(64 * 1024, min(env_int('TAIKO_WEB_UPLOAD_TJA_MAX_BYTES', 2 * 1024 * 1024), 10 * 1024 * 1024))
UPLOAD_MUSIC_MAX_BYTES = max(1024 * 1024, min(env_int('TAIKO_WEB_UPLOAD_MUSIC_MAX_BYTES', 32 * 1024 * 1024), 128 * 1024 * 1024))
UPLOAD_ALLOWED_MUSIC_TYPES = {'ogg', 'mp3'}
UPLOAD_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
app.config['MAX_CONTENT_LENGTH'] = (
    UPLOAD_TJA_MAX_BYTES +
    UPLOAD_MUSIC_MAX_BYTES +
    UPLOAD_MULTIPART_OVERHEAD_BYTES
)


class UploadValidationError(ValueError):
    pass


def object_id_or_404(value):
    try:
        return ObjectId(value)
    except Exception:
        abort(404)


def serialize_site_message(message, read_ids=None):
    read_ids = read_ids or set()
    message_id = str(message.get('_id'))
    created_at = message.get('created_at')
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat() + 'Z'

    return {
        'id': message_id,
        'title': message.get('title') or '',
        'body': message.get('body') or '',
        'image_url': message.get('image_url') or '',
        'created_at': created_at,
        'created_by': message.get('created_by') or '',
        'active': bool(message.get('active', True)),
        'read': message_id in read_ids
    }


def get_site_message_read_ids(username, message_ids):
    if not username or not message_ids:
        return set()

    return {
        item.get('message_id')
        for item in db.site_message_reads.find({
            'username': username,
            'message_id': {'$in': message_ids}
        }, {'_id': False, 'message_id': True})
    }


def get_site_messages(limit=50, active_only=True):
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 50

    query = {'active': True} if active_only else {}
    return list(db.site_messages.find(query).sort('created_at', -1).limit(limit))


def is_allowed_site_message_image(filename):
    return pathlib.Path(filename or '').suffix.lower() in SITE_MESSAGE_IMAGE_EXTENSIONS


def site_message_image_signature_matches(data, suffix):
    if suffix in ('.jpg', '.jpeg'):
        return data.startswith(b'\xff\xd8\xff')
    if suffix == '.png':
        return data.startswith(b'\x89PNG\r\n\x1a\n')
    if suffix == '.gif':
        return data.startswith((b'GIF87a', b'GIF89a'))
    if suffix == '.webp':
        return len(data) >= 12 and data.startswith(b'RIFF') and data[8:12] == b'WEBP'
    return False


def local_site_message_image_path(image_url):
    prefix = site_path('notice_uploads/')
    if not isinstance(image_url, str) or not image_url.startswith(prefix):
        return None
    filename = image_url[len(prefix):]
    if not re.fullmatch(r'[a-f0-9]{32}\.(?:jpg|jpeg|png|gif|webp)', filename):
        return None
    root = NOTICE_UPLOADS_DIR.resolve()
    path = (root / filename).resolve()
    return path if path.parent == root else None


def remove_site_message_image(image_url):
    path = local_site_message_image_path(image_url)
    if path:
        path.unlink(missing_ok=True)


def save_site_message_image(upload):
    if not upload or not upload.filename:
        return None

    filename = secure_filename(upload.filename)
    if not filename or not is_allowed_site_message_image(filename):
        raise ValueError('Unsupported image type. Please upload jpg, png, gif, or webp.')

    data = upload.stream.read(SITE_MESSAGE_MAX_IMAGE_BYTES + 1)
    if not data:
        raise ValueError('Image is empty.')
    if len(data) > SITE_MESSAGE_MAX_IMAGE_BYTES:
        raise ValueError('Image is too large. Please keep it under 5 MB.')

    NOTICE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = pathlib.Path(filename).suffix.lower()
    if not site_message_image_signature_matches(data, suffix):
        raise ValueError('Image content does not match its file extension.')
    stored_name = '{}{}'.format(uuid.uuid4().hex, suffix)
    target = NOTICE_UPLOADS_DIR / stored_name
    temporary = NOTICE_UPLOADS_DIR / '.notice-{}.tmp'.format(uuid.uuid4().hex)
    try:
        with temporary.open('xb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return site_path('notice_uploads/{}'.format(stored_name))


def utc_period_starts(now=None):
    now = now or utc_now()
    return {
        'hour': now - timedelta(hours=1),
        'day': now.replace(hour=0, minute=0, second=0, microsecond=0),
        'week': (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0),
        'month': now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    }


def song_display_title(song):
    if not song:
        return 'Unknown song'
    title_lang = song.get('title_lang') or {}
    return title_lang.get('en') or song.get('title') or 'Untitled'


def song_period_counts_many(song_hashes, periods):
    song_hashes = list(dict.fromkeys(
        song_hash for song_hash in song_hashes if song_hash
    ))
    if not song_hashes:
        return {}

    empty_counts = {name: 0 for name in periods}
    output = {
        song_hash: dict(empty_counts)
        for song_hash in song_hashes
    }
    group = {'_id': '$song_hash'}
    for name, start in periods.items():
        group[name] = {
            '$sum': {
                '$cond': [{'$gte': ['$played_at', start]}, 1, 0]
            }
        }

    try:
        rows = db.play_records.aggregate([
            {'$match': {
                'song_hash': {'$in': song_hashes},
                'played_at': {'$gte': min(periods.values())}
            }},
            {'$group': group}
        ], maxTimeMS=ADMIN_STATS_MAX_TIME_MS, allowDiskUse=False)
        for row in rows:
            output[row['_id']] = {
                name: row.get(name, 0)
                for name in periods
            }
    except PyMongoError:
        return {
            song_hash: {name: None for name in periods}
            for song_hash in song_hashes
        }
    return output


def song_period_counts(song_hash, periods):
    return song_period_counts_many([song_hash], periods).get(
        song_hash,
        {name: 0 for name in periods}
    )


def top_songs_cache_stale(cache_doc, now=None):
    if not cache_doc:
        return True
    if cache_doc.get('schema_version') != TOP_SONGS_CACHE_SCHEMA_VERSION:
        return True
    rows = cache_doc.get('rows')
    updated_at = cache_doc.get('updated_at')
    if not isinstance(rows, list) or not updated_at:
        return True
    now = now or utc_now()
    return updated_at <= now - timedelta(days=TOP_SONGS_CACHE_DAYS)


def get_top_songs_cache_doc():
    return db.top_song_cache.find_one({'_id': TOP_SONGS_CACHE_KEY}) or {}


def acquire_top_songs_refresh_lock():
    now = utc_now()
    token = uuid.uuid4().hex
    lock_until = now + timedelta(seconds=TOP_SONGS_REFRESH_LOCK_SECONDS)
    try:
        result = db.top_song_cache.update_one(
            {
                '_id': TOP_SONGS_REFRESH_LOCK_KEY,
                '$or': [
                    {'locked_until': {'$lte': now}},
                    {'locked_until': {'$exists': False}}
                ]
            },
            {'$set': {
                'token': token,
                'started_at': now,
                'locked_until': lock_until
            }},
            upsert=True
        )
        if result.upserted_id or result.modified_count:
            return token
    except DuplicateKeyError:
        return None
    return None


def release_top_songs_refresh_lock(token):
    if token:
        db.top_song_cache.delete_one({
            '_id': TOP_SONGS_REFRESH_LOCK_KEY,
            'token': token
        })


def top_songs_refreshing(now=None):
    now = now or utc_now()
    lock = db.top_song_cache.find_one({'_id': TOP_SONGS_REFRESH_LOCK_KEY}) or {}
    return bool(lock.get('locked_until') and lock.get('locked_until') > now)


def song_play_counts_empty():
    return not db.song_play_counts.find_one({}, {'_id': True})


def play_records_exist():
    return bool(db.play_records.find_one({}, {'_id': True}))


def song_play_counts_backfill_done():
    return bool(db.top_song_cache.find_one({'_id': TOP_SONGS_BACKFILL_KEY}, {'_id': True}))


def mark_song_play_counts_backfilled(status):
    db.top_song_cache.update_one(
        {'_id': TOP_SONGS_BACKFILL_KEY},
        {'$set': {
            'status': status,
            'updated_at': utc_now()
        }},
        upsert=True
    )


def backfill_song_play_counts_if_needed():
    if song_play_counts_backfill_done():
        return 'ready'
    if not play_records_exist():
        mark_song_play_counts_backfilled('empty')
        return 'empty'

    list(db.play_records.aggregate([
        {'$match': {'song_hash': {'$nin': [None, '']}}},
        {'$group': {
            '_id': '$song_hash',
            'song_hash': {'$first': '$song_hash'},
            'play_count': {'$sum': 1},
            'last_played_at': {'$max': '$played_at'}
        }},
        {'$merge': {
            'into': 'song_play_counts',
            'on': '_id',
            'whenMatched': 'replace',
            'whenNotMatched': 'insert'
        }}
    ], allowDiskUse=True, maxTimeMS=TOP_SONGS_BACKFILL_MAX_TIME_MS))
    mark_song_play_counts_backfilled('backfilled')
    return 'backfilled'


def get_top_song_count_docs(limit, multiplier=1):
    limit = max(1, min(int(limit), 200))
    cursor = db.song_play_counts.find(
        {'song_hash': {'$nin': [None, '']}},
        {'_id': False, 'song_hash': True, 'play_count': True, 'last_played_at': True}
    ).sort([
        ('play_count', -1),
        ('last_played_at', -1)
    ]).hint([
        ('play_count', -1),
        ('last_played_at', -1)
    ]).limit(limit * max(1, multiplier)).max_time_ms(TOP_SONGS_SORT_MAX_TIME_MS)
    return list(cursor)


def build_song_identity_maps(songs):
    songs_by_hash = {}
    songs_by_id = {}
    songs_by_title = {}
    for song in songs:
        song_hash = song.get('hash')
        song_id = song.get('id')
        title = song.get('title')
        if song_hash not in (None, ''):
            songs_by_hash.setdefault(str(song_hash), song)
        if song_id not in (None, ''):
            songs_by_id.setdefault(str(song_id), song)
        if title not in (None, ''):
            songs_by_title.setdefault(str(title), song)
    return songs_by_hash, songs_by_id, songs_by_title


def resolve_song_identity(song_hash, identity_maps):
    key = str(song_hash)
    songs_by_hash, songs_by_id, songs_by_title = identity_maps
    return (
        songs_by_hash.get(key) or
        songs_by_id.get(key) or
        songs_by_title.get(key)
    )


def find_enabled_song_by_identity(song_hash):
    song_ids = [song_hash]
    numeric_id = safe_int_value(song_hash)
    if numeric_id is not None:
        song_ids.append(numeric_id)
    song = db.songs.find_one({
        'enabled': True,
        '$or': [
            {'hash': song_hash},
            {'id': {'$in': song_ids}},
            {'title': song_hash}
        ]
    })
    return song if song and public_song_files_available(song) else None


def build_public_top_songs_cache_rows(limit=TOP_SONGS_CACHE_MAX_ROWS):
    count_docs = get_top_song_count_docs(limit, multiplier=20)
    song_hashes = [item.get('song_hash') for item in count_docs if item.get('song_hash')]
    song_ids = set()
    for song_hash in song_hashes:
        song_ids.add(song_hash)
        song_id = safe_int_value(song_hash)
        if song_id is not None:
            song_ids.add(song_id)

    if not song_hashes and not song_ids:
        return []

    songs = list(db.songs.find(
        {
            'enabled': True,
            '$or': [
                {'hash': {'$in': song_hashes}},
                {'id': {'$in': list(song_ids)}},
                {'title': {'$in': song_hashes}}
            ]
        },
        {
            '_id': False,
            'id': True,
            'hash': True,
            'title': True,
            'title_lang': True,
            'subtitle': True,
            'subtitle_lang': True,
            'category_id': True,
            'song_type': True,
            'type': True,
            'music_type': True,
            'courses': True
        }
    ))
    identity_maps = build_song_identity_maps(songs)

    rows = []
    for item in count_docs:
        song_hash = item.get('song_hash')
        song = resolve_song_identity(song_hash, identity_maps)
        if not song or not public_song_files_available(song):
            continue

        rows.append({
            'rank': len(rows) + 1,
            'song_id': song.get('id'),
            'song_hash': song.get('hash') or song_hash,
            'title': song.get('title') or '',
            'title_lang': safe_lang_map(song.get('title_lang')),
            'subtitle': song.get('subtitle') or '',
            'subtitle_lang': safe_lang_map(song.get('subtitle_lang')),
            'category_id': song.get('category_id'),
            'song_type': song.get('song_type') or '',
            'play_count': item.get('play_count', 0)
        })
        if len(rows) >= limit:
            break

    return rows


def refresh_top_songs_cache(force=False, requested_by=None, allow_backfill=True):
    cache_doc = get_top_songs_cache_doc()
    if not force and not top_songs_cache_stale(cache_doc):
        return {'status': 'fresh', 'rows_count': len(cache_doc.get('rows') or [])}

    token = acquire_top_songs_refresh_lock()
    if not token:
        return {'status': 'busy', 'rows_count': len(cache_doc.get('rows') or [])}

    started = time.monotonic()
    try:
        cache_doc = get_top_songs_cache_doc()
        if not force and not top_songs_cache_stale(cache_doc):
            return {'status': 'fresh', 'rows_count': len(cache_doc.get('rows') or [])}

        backfill_status = 'skipped'
        if allow_backfill:
            backfill_status = backfill_song_play_counts_if_needed()
        elif not song_play_counts_backfill_done():
            if play_records_exist():
                if song_play_counts_empty():
                    now = utc_now()
                    rows = cache_doc.get('rows') if isinstance(cache_doc.get('rows'), list) else []
                    db.top_song_cache.update_one(
                        {'_id': TOP_SONGS_CACHE_KEY},
                        {'$set': {
                            'rows': rows,
                            'updated_at': now,
                            'expires_at': now + timedelta(days=TOP_SONGS_CACHE_DAYS),
                            'status': 'needs_backfill',
                            'schema_version': TOP_SONGS_CACHE_SCHEMA_VERSION,
                            'last_backfill_status': 'needed',
                            'requested_by': requested_by or 'auto'
                        }},
                        upsert=True
                    )
                    return {'status': 'needs_backfill', 'rows_count': len(cache_doc.get('rows') or [])}
                backfill_status = 'partial'
            else:
                mark_song_play_counts_backfilled('empty')

        rows = build_public_top_songs_cache_rows(TOP_SONGS_CACHE_MAX_ROWS)
        now = utc_now()
        refresh_ms = int((time.monotonic() - started) * 1000)
        db.top_song_cache.update_one(
            {'_id': TOP_SONGS_CACHE_KEY},
            {'$set': {
                'rows': rows,
                'updated_at': now,
                'expires_at': now + timedelta(days=TOP_SONGS_CACHE_DAYS),
                'status': 'ready',
                'schema_version': TOP_SONGS_CACHE_SCHEMA_VERSION,
                'last_error': None,
                'last_error_at': None,
                'last_refresh_ms': refresh_ms,
                'last_backfill_status': backfill_status,
                'requested_by': requested_by or 'auto'
            }},
            upsert=True
        )
        return {
            'status': 'updated',
            'rows_count': len(rows),
            'refresh_ms': refresh_ms,
            'backfill_status': backfill_status
        }
    except PyMongoError as exc:
        now = utc_now()
        message = str(exc)[:240]
        db.top_song_cache.update_one(
            {'_id': TOP_SONGS_CACHE_KEY},
            {'$set': {
                'status': 'error',
                'last_error': message,
                'last_error_at': now,
                'requested_by': requested_by or 'auto'
            }},
            upsert=True
        )
        return {'status': 'error', 'error': message, 'rows_count': len(cache_doc.get('rows') or [])}
    finally:
        release_top_songs_refresh_lock(token)


def get_top_songs_cache_status():
    cache_doc = get_top_songs_cache_doc()
    rows = cache_doc.get('rows') if isinstance(cache_doc.get('rows'), list) else []
    updated_at = cache_doc.get('updated_at')
    needs_backfill = (
        not song_play_counts_backfill_done() and
        play_records_exist()
    )
    return {
        'updated_at': updated_at,
        'expires_at': cache_doc.get('expires_at'),
        'rows_count': len(rows),
        'stale': top_songs_cache_stale(cache_doc),
        'refreshing': top_songs_refreshing(),
        'needs_backfill': needs_backfill,
        'status': cache_doc.get('status') or 'missing',
        'last_error': cache_doc.get('last_error'),
        'last_error_at': cache_doc.get('last_error_at'),
        'last_refresh_ms': cache_doc.get('last_refresh_ms'),
        'last_backfill_status': cache_doc.get('last_backfill_status')
    }


def record_song_play_count(song_hash, played_at):
    if not song_hash:
        return
    try:
        result = db.song_play_counts.update_one(
            {'_id': song_hash},
            {
                '$set': {'song_hash': song_hash, 'last_played_at': played_at},
                '$inc': {'play_count': 1}
            },
            upsert=True
        )
        if result.upserted_id is not None:
            mark_top_songs_cache_stale()
    except PyMongoError:
        app.logger.exception('Failed to update aggregate play count for %s', song_hash)


def get_public_songs_cache_version():
    return app.cache.get(PUBLIC_SONGS_CACHE_VERSION_KEY) or PUBLIC_SONGS_CACHE_BOOT_VERSION


def invalidate_public_songs_cache():
    app.cache.set(PUBLIC_SONGS_CACHE_VERSION_KEY, str(time.time_ns()), timeout=0)


def mark_top_songs_cache_stale():
    cache_doc = get_top_songs_cache_doc()
    if not cache_doc:
        return
    stale_at = utc_now() - timedelta(days=TOP_SONGS_CACHE_DAYS + 1)
    db.top_song_cache.update_one(
        {'_id': TOP_SONGS_CACHE_KEY},
        {'$set': {
            'updated_at': stale_at,
            'status': 'stale'
        }}
    )


def invalidate_song_derived_caches():
    try:
        invalidate_public_songs_cache()
    except Exception:
        app.logger.exception('Failed to invalidate the public song cache')
    try:
        mark_top_songs_cache_stale()
    except Exception:
        app.logger.exception('Failed to mark the Top10 cache stale')


def total_period_counts(collection, datetime_field, periods):
    group = {'_id': None}
    for name, start in periods.items():
        group[name] = {
            '$sum': {
                '$cond': [{'$gte': ['${}'.format(datetime_field), start]}, 1, 0]
            }
        }
    try:
        rows = list(collection.aggregate([
            {'$match': {datetime_field: {'$gte': min(periods.values())}}},
            {'$group': group}
        ], maxTimeMS=ADMIN_STATS_MAX_TIME_MS, allowDiskUse=False))
        row = rows[0] if rows else {}
        return {name: row.get(name, 0) for name in periods}
    except PyMongoError:
        return {name: None for name in periods}


def unique_visit_counts(periods):
    totals = {'_id': None}
    for name, start in periods.items():
        totals[name] = {
            '$sum': {
                '$cond': [{'$gte': ['$last_entered_at', start]}, 1, 0]
            }
        }
    try:
        rows = list(db.visit_records.aggregate([
            {'$match': {'entered_at': {'$gte': min(periods.values())}}},
            {'$group': {
                '_id': '$visitor_key',
                'last_entered_at': {'$max': '$entered_at'}
            }},
            {'$group': totals}
        ], maxTimeMS=ADMIN_STATS_MAX_TIME_MS, allowDiskUse=False))
        row = rows[0] if rows else {}
        return {name: row.get(name, 0) for name in periods}
    except PyMongoError:
        return {name: None for name in periods}


def get_song_heat_rows(limit=30):
    limit = max(1, min(int(limit), 100))
    periods = utc_period_starts()
    count_docs = get_top_song_count_docs(limit)
    song_hashes = [
        item.get('song_hash')
        for item in count_docs
        if item.get('song_hash')
    ]
    song_ids = set(song_hashes)
    song_ids.update(
        song_id
        for song_id in (safe_int_value(song_hash) for song_hash in song_hashes)
        if song_id is not None
    )
    songs = list(db.songs.find({
        '$or': [
            {'hash': {'$in': song_hashes}},
            {'id': {'$in': list(song_ids)}},
            {'title': {'$in': song_hashes}}
        ]
    })) if song_hashes else []
    identity_maps = build_song_identity_maps(songs)
    period_counts = song_period_counts_many(song_hashes, periods)
    rows = []

    for item in count_docs:
        song_hash = item.get('song_hash')
        song = resolve_song_identity(song_hash, identity_maps)
        rows.append({
            'song': song,
            'song_id': song.get('id') if song else None,
            'song_hash': song_hash,
            'title': song_display_title(song),
            'total': item.get('play_count', 0),
            'periods': period_counts.get(
                song_hash,
                {name: 0 for name in periods}
            )
        })

    return rows


def get_public_top_songs(limit=10):
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10

    refresh_top_songs_cache(force=False, requested_by='auto', allow_backfill=False)
    cache_doc = get_top_songs_cache_doc()
    rows = cache_doc.get('rows') if isinstance(cache_doc.get('rows'), list) else []
    return rows[:limit]


def get_admin_overview_stats():
    periods = utc_period_starts()
    enabled_songs = list(db.songs.find(
        {'enabled': True},
        {'id': True, 'type': True, 'music_type': True, 'courses': True}
    ))
    playable_song_count = sum(
        1 for song in enabled_songs if public_song_files_available(song)
    )
    return {
        'song_count': db.songs.count_documents({}),
        'enabled_song_count': len(enabled_songs),
        'playable_song_count': playable_song_count,
        'missing_song_file_count': len(enabled_songs) - playable_song_count,
        'user_count': db.users.count_documents({}),
        'message_count': db.site_messages.count_documents({}),
        'play_counts': total_period_counts(db.play_records, 'played_at', periods),
        'visit_counts': unique_visit_counts({
            'day': periods['day'],
            'week': periods['week'],
            'month': periods['month']
        }),
        'top_songs_cache': get_top_songs_cache_status(),
        'heat_rows': get_song_heat_rows(20),
        'retention_days': VISIT_RETENTION_DAYS
    }


def get_admin_song_stats(song):
    periods = utc_period_starts()
    song_hash = song.get('hash') or str(song.get('id'))
    try:
        total = db.play_records.count_documents(
            {'song_hash': song_hash},
            maxTimeMS=ADMIN_STATS_MAX_TIME_MS
        )
    except PyMongoError:
        total = None
    try:
        recent_records = list(
            db.play_records.find({'song_hash': song_hash})
            .sort('played_at', -1)
            .limit(25)
            .max_time_ms(ADMIN_STATS_MAX_TIME_MS)
        )
    except PyMongoError:
        recent_records = []
    return {
        'song_hash': song_hash,
        'total': total,
        'periods': song_period_counts(song_hash, periods),
        'recent_records': recent_records
    }

BOARD_RETENTION_DAYS = 30
BOARD_RETENTION_SECONDS = BOARD_RETENTION_DAYS * 24 * 60 * 60
BOARD_CREATED_AT_INDEX = 'created_at_1'

BOARD_BLOCKED_WORDS = [
    "taiko" + "app" + "." + "uk",
    "cj" + "dg",
]
BOARD_MAX_NAME_LENGTH = 40
BOARD_MAX_MESSAGE_LENGTH = 1000
BOARD_LINK_PATTERN = re.compile(
    r'(?:https?://|www\.|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,24})'
    r'(?:[\s/:?#.,!?)\]]|$)',
    re.IGNORECASE
)


def ensure_board_posts_indexes():
    try:
        for index in db.board_posts.list_indexes():
            if (
                index.get('name') == BOARD_CREATED_AT_INDEX and
                index.get('expireAfterSeconds') != BOARD_RETENTION_SECONDS
            ):
                db.board_posts.drop_index(BOARD_CREATED_AT_INDEX)
                break
        db.board_posts.create_index(
            [('created_at', 1)],
            name=BOARD_CREATED_AT_INDEX,
            expireAfterSeconds=BOARD_RETENTION_SECONDS
        )
    except Exception as e:
        print('Warning: failed to ensure board post TTL index: {}'.format(e))


ensure_board_posts_indexes()


def board_text(*values):
    return " ".join(value or "" for value in values)


def board_contains_blocked_word(*values):
    text = board_text(*values).casefold()
    return any(word.casefold() in text for word in BOARD_BLOCKED_WORDS)


def board_contains_link(*values):
    return bool(BOARD_LINK_PATTERN.search(board_text(*values)))


def board_post_is_allowed(post):
    return not board_contains_link(
        post.get('name'), post.get('message')
    ) and not board_contains_blocked_word(
        post.get('name'), post.get('message')
    )


def board_cutoff():
    return utc_now() - timedelta(days=BOARD_RETENTION_DAYS)


def delete_old_board_posts():
    try:
        db.board_posts.delete_many({'created_at': {'$lt': board_cutoff()}})
    except Exception as e:
        print('Warning: failed to delete old board posts: {}'.format(e))


def get_board_posts(limit=100):
    delete_old_board_posts()
    posts = []
    query = {'created_at': {'$gte': board_cutoff()}}
    for post in db.board_posts.find(query).sort('created_at', -1).limit(limit * 3):
        if board_post_is_allowed(post):
            posts.append(serialize_board_post(post))
        if len(posts) >= limit:
            break
    return posts


def serialize_board_post(post):
    created_at = post.get('created_at')
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat() + 'Z'

    return {
        'id': str(post.get('_id')),
        'name': post.get('name', ''),
        'message': post.get('message', ''),
        'created_at': created_at
    }


class HashException(Exception):
    pass


def api_error(message):
    return jsonify({'status': 'error', 'message': message})


def generate_hash(id, form):
    md5 = hashlib.md5(usedforsecurity=False)
    if form.get('type') == 'tja':
        chart_names = ['main.tja']
    else:
        chart_names = []
        for diff in ['easy', 'normal', 'hard', 'oni', 'ura']:
            if form.get('course_' + diff):
                chart_names.append('%s.osu' % diff)

    base_url = take_config('SONGS_BASEURL', required=True)
    for chart_name in chart_names:
        if base_url.startswith(("http://", "https://")):
            url = '{}/{}/{}'.format(base_url.rstrip('/'), id, chart_name)
            try:
                resp = requests.get(url, timeout=REMOTE_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise HashException('Unable to load chart data') from exc
            if resp.status_code != 200:
                raise HashException('Invalid response from %s (status code %s)' % (resp.url, resp.status_code))
            md5.update(resp.content)
        else:
            try:
                song_directory = song_storage_child(str(id))
            except ValueError as error:
                raise HashException('Invalid song path') from error
            path = song_directory / chart_name
            if not path.is_file():
                raise HashException("File not found: %s" % path)
            md5.update(path.read_bytes())

    return base64.b64encode(md5.digest())[:-2].decode('utf-8')


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('username'):
            return api_error('not_logged_in')
        return f(*args, **kwargs)
    return decorated_function


def admin_required(level):
    def decorated_function(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not FEATURE_ADMIN:
                return abort(404)
            if not session.get('username'):
                return abort(403)
            
            user = db.users.find_one({'username': session.get('username')})
            if not user or get_user_level(user) < level:
                return abort(403)

            return f(*args, **kwargs)
        return wrapper
    return decorated_function


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return api_error('invalid_csrf'), 400


@app.errorhandler(413)
def handle_request_too_large(e):
    if request.path.endswith('/api/upload') or request.path.endswith('/api/user-upload'):
        return jsonify({'success': False, 'error': 'upload_too_large'}), 413
    return e


@app.errorhandler(429)
def handle_rate_limit(e):
    if '/api/' in request.path:
        return jsonify({'success': False, 'error': 'rate_limited'}), 429
    return e


@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault(
        'Permissions-Policy',
        'camera=(), geolocation=(), microphone=()'
    )
    endpoint = request.endpoint or ''
    if (
        endpoint == 'route_api_config' or
        endpoint == 'route_csrftoken' or
        endpoint == 'route_secret_admin_login' or
        endpoint.startswith('route_api_account_') or
        endpoint in {
            'route_api_register',
            'route_api_login',
            'route_api_logout',
            'route_api_scores_save',
            'route_api_scores_get'
        } or
        endpoint.startswith('route_api_weekly_challenge_') or
        endpoint.startswith('route_admin_')
    ):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['CDN-Cache-Control'] = 'no-store'
        response.vary.add('Cookie')
    return response


def configured_upload_token():
    return os.environ.get('TAIKO_WEB_UPLOAD_TOKEN') or take_config('UPLOAD_TOKEN') or ''


def request_uses_upload_token():
    configured = configured_upload_token()
    authorization = request.headers.get('Authorization') or ''
    scheme, separator, supplied = authorization.partition(' ')
    return bool(
        configured and
        separator and
        scheme.lower() == 'bearer' and
        secrets.compare_digest(supplied.strip(), str(configured))
    )


@app.before_request
def before_request_func():
    endpoint = request.endpoint or ''
    if (
        request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and
        endpoint and not (
            endpoint == 'api_upload_file' and request_uses_upload_token()
        )
    ):
        csrf.protect()

    username = session.get('username')
    session_id = session.get('session_id')
    if session_id:
        query = {'session_id': session_id}
        if username:
            query['username'] = username
        if not db.users.find_one(query, {'_id': True}):
            session.clear()
    elif username and not db.users.find_one({'username': username}, {'_id': True}):
        session.clear()


def get_config(credentials=False):
    def resource_base(value, fallback):
        value = str(value or fallback).strip()
        if value.startswith(('http://', 'https://')):
            return value.rstrip('/') + '/'
        path = '/' + value.strip('/') + '/'
        if basedir != '/' and not path.startswith(basedir):
            path = basedir + path.lstrip('/')
        return path

    config_out = {
        'basedir': basedir,
        'songs_baseurl': resource_base(
            take_config('SONGS_BASEURL', required=True),
            'songs'
        ),
        'assets_baseurl': resource_base(
            take_config('ASSETS_BASEURL', required=True),
            'assets'
        ),
        'email': take_config('EMAIL'),
        'accounts': take_config('ACCOUNTS'),
        'custom_js': take_config('CUSTOM_JS'),
        'plugins': take_config('PLUGINS') and [x for x in take_config('PLUGINS') if x['url']],
        'preview_type': take_config('PREVIEW_TYPE') or 'mp3',
        'multiplayer_url': take_config('MULTIPLAYER_URL'),
        'features': {
            'site_messages': FEATURE_SITE_MESSAGES,
            'top_songs': FEATURE_TOP_SONGS
        }
    }
    if credentials:
        google_credentials = take_config('GOOGLE_CREDENTIALS') or {}
        min_level = max(50, safe_int_value(google_credentials.get('min_level'), 50))
        if not session.get('username'):
            user_level = 0
        else:
            user = db.users.find_one({'username': session.get('username')})
            user_level = get_user_level(user)
        if google_credentials and user_level >= min_level:
            config_out['google_credentials'] = google_credentials
        else:
            config_out['google_credentials'] = {
                'gdrive_enabled': False
            }

    config_out['_version'] = get_version()
    return config_out

def get_version():
    version = {
        'commit': None,
        'commit_short': '',
        'version': None,
        'asset_version': FRONTEND_ASSET_VERSION,
        'url': take_config('URL')
    }
    version_path = APP_ROOT / 'version.json'
    if version_path.is_file():
        try:
            with version_path.open('r', encoding='utf-8') as version_file:
                ver = json.load(version_file)
        except (OSError, ValueError):
            print('Invalid version.json file')
            return version

        for key in version.keys():
            if ver.get(key):
                version[key] = ver.get(key)

    return version


def site_path(path=''):
    base = basedir if basedir.endswith('/') else basedir + '/'
    return base + path.lstrip('/')


def localized_index_path(lang):
    return site_path(lang)


def absolute_site_url(path):
    origin = site_origin or request.url_root.rstrip('/')
    return origin + '/' + path.lstrip('/')


def resolve_seo_lang(lang):
    lang = (lang or SEO_DEFAULT_LANG).lower()
    lang = SEO_LANG_ALIASES.get(lang, lang)
    if lang in SEO_LANGUAGES:
        return lang
    return None


def get_seo_meta(lang=SEO_DEFAULT_LANG):
    lang = resolve_seo_lang(lang) or SEO_DEFAULT_LANG
    meta = dict(SEO_LANGUAGES[lang])
    meta['lang'] = lang
    meta['canonical_url'] = absolute_site_url(localized_index_path(lang))
    meta['default_url'] = absolute_site_url(localized_index_path(SEO_DEFAULT_LANG))
    meta['alternate_urls'] = [
        {
            'lang': code,
            'hreflang': details['hreflang'],
            'url': absolute_site_url(localized_index_path(code))
        }
        for code, details in SEO_LANGUAGES.items()
    ]
    return meta


def render_index_page(lang=SEO_DEFAULT_LANG):
    version = get_version()
    return render_template('index.html', version=version, config=get_config(), seo=get_seo_meta(lang))


def get_user_level(user):
    if not user:
        return 0
    try:
        return int(user.get('user_level') or 0)
    except (TypeError, ValueError):
        return 0


def get_user_display_name(user, fallback=None):
    if not user:
        return fallback or ''
    return user.get('display_name') or user.get('username') or fallback or ''


def find_user_by_username(username):
    username = str(username or '').strip()
    if not username:
        return None
    username_lower = username.lower()
    user = db.users.find_one({'username_lower': username_lower})
    if user:
        return user

    user = db.users.find_one({
        'username': re.compile(r'^{}$'.format(re.escape(username)), re.IGNORECASE)
    })
    if user and not user.get('username_lower'):
        try:
            db.users.update_one(
                {
                    '_id': user['_id'],
                    '$or': [
                        {'username_lower': {'$exists': False}},
                        {'username_lower': None},
                        {'username_lower': ''}
                    ]
                },
                {'$set': {'username_lower': username_lower}}
            )
            user['username_lower'] = username_lower
        except DuplicateKeyError:
            app.logger.warning(
                'Legacy username case conflict detected for account %s',
                user.get('_id')
            )
            return None
    return user


def check_user_password(user, password):
    try:
        return bool(user) and bcrypt.checkpw(password, user.get('password', b''))
    except (TypeError, ValueError):
        return False


def ensure_user_session_id(user):
    session_id = user.get('session_id') if user else None
    if session_id:
        return session_id
    session_id = os.urandom(24).hex()
    if user and user.get('_id'):
        db.users.update_one({'_id': user['_id']}, {'$set': {'session_id': session_id}})
    return session_id


def get_db_don(user):
    default = get_default_don()
    if not user:
        return default
    stored_don = user.get('don') if isinstance(user.get('don'), dict) else {}
    don_body_fill = user.get('don_body_fill') or stored_don.get('body_fill') or default['body_fill']
    don_face_fill = user.get('don_face_fill') or stored_don.get('face_fill') or default['face_fill']
    return {'body_fill': don_body_fill, 'face_fill': don_face_fill}


ADMIN_COURSES = ['easy', 'normal', 'hard', 'oni', 'ura']


def safe_int_value(value, default=None):
    if value in (None, ''):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def route_song_id(value):
    value = str(value)
    return int(value) if re.fullmatch(r'\d+', value) else value


def is_public_song_id(value):
    value = str(value or '')
    return bool(
        re.fullmatch(r'[0-9]{1,9}', value) or
        re.fullmatch(r'[a-f0-9]{64}-[a-f0-9]{64}', value)
    )


def find_song_by_route_id(value):
    return db.songs.find_one({'id': route_song_id(value)})


def safe_float_value(value, default=None):
    if value in (None, ''):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def safe_lang_map(value):
    return value if isinstance(value, dict) else {}


def songs_use_local_storage():
    base_url = take_config('SONGS_BASEURL') or ''
    return not base_url.startswith(('http://', 'https://'))


def public_song_files_available(song):
    if not songs_use_local_storage():
        return True

    song_id = song.get('id') if isinstance(song, dict) else None
    if song_id in (None, ''):
        return False

    root = SONGS_DIR.resolve()
    song_dir = (root / str(song_id)).resolve()
    if song_dir.parent != root or not song_dir.is_dir():
        return False

    music_type = str(song.get('music_type') or 'mp3').lower()
    if not re.fullmatch(r'[a-z0-9]+', music_type):
        return False
    if not (song_dir / 'main.{}'.format(music_type)).is_file():
        return False

    song_type = song.get('type') or 'tja'
    if song_type == 'tja':
        return (
            (song_dir / 'main.tja').is_file() and
            any(song_has_course(song, course) for course in ADMIN_COURSES)
        )
    if song_type == 'osu':
        courses = song.get('courses') if isinstance(song.get('courses'), dict) else {}
        chart_names = [
            '{}.osu'.format(course)
            for course in ADMIN_COURSES
            if song_has_course(song, course)
        ]
        return bool(chart_names) and all((song_dir / name).is_file() for name in chart_names)
    return False


def song_has_course(song, difficulty):
    if difficulty not in ADMIN_COURSES or not isinstance(song, dict):
        return False
    courses = song.get('courses')
    if not isinstance(courses, dict):
        return False
    course = courses.get(difficulty)
    if not isinstance(course, dict):
        return False
    stars = safe_int_value(course.get('stars'))
    return stars is not None and 0 <= stars <= 10


def normalize_song_courses(courses):
    courses = courses if isinstance(courses, dict) else {}
    normalized = {}
    for course in ADMIN_COURSES:
        course_data = courses.get(course)
        if isinstance(course_data, dict):
            normalized[course] = {
                'stars': safe_int_value(course_data.get('stars'), 0),
                'branch': bool(course_data.get('branch'))
            }
        else:
            normalized[course] = None
    return normalized


def form_int(name, default=None):
    return safe_int_value(request.form.get(name), default)


def form_float(name, default=None):
    return safe_float_value(request.form.get(name), default)


def optional_form_int(name, errors):
    raw = (request.form.get(name) or '').strip()
    if raw == '':
        return None
    value = safe_int_value(raw)
    if value is None:
        errors.append('{} must be an integer'.format(name))
    return value


def required_form_float(name, minimum, maximum, errors):
    raw = (request.form.get(name) or '').strip()
    value = safe_float_value(raw)
    if value is None or not minimum <= value <= maximum:
        errors.append('{} must be between {} and {}'.format(name, minimum, maximum))
        return None
    return value


def reference_exists(collection, value):
    if value is None:
        return True
    candidates = [value, str(value)]
    numeric = safe_int_value(value)
    if numeric is not None:
        candidates.append(numeric)
    return bool(collection.find_one({'id': {'$in': list(dict.fromkeys(candidates))}}, {'_id': True}))


def build_admin_song_form(song_id, existing=None, can_set_enabled=True):
    existing = existing or {}
    errors = []
    output = {'title_lang': {}, 'subtitle_lang': {}, 'courses': {}}
    output['enabled'] = (
        bool(request.form.get('enabled'))
        if can_set_enabled else bool(existing.get('enabled'))
    )
    output['title'] = (request.form.get('title') or '').strip()
    output['subtitle'] = (request.form.get('subtitle') or '').strip()
    if not output['title'] or len(output['title']) > 500:
        errors.append('title is required and must not exceed 500 characters')
    if len(output['subtitle']) > 500:
        errors.append('subtitle must not exceed 500 characters')

    for lang in ['ja', 'en', 'cn', 'tw', 'ko']:
        title = (request.form.get('title_{}'.format(lang)) or '').strip()
        subtitle = (request.form.get('subtitle_{}'.format(lang)) or '').strip()
        if len(title) > 500 or len(subtitle) > 500:
            errors.append('{} translation is too long'.format(lang))
        output['title_lang'][lang] = title or None
        output['subtitle_lang'][lang] = subtitle or None

    for course in ADMIN_COURSES:
        raw = (request.form.get('course_{}'.format(course)) or '').strip()
        if raw == '':
            output['courses'][course] = None
            continue
        stars = safe_int_value(raw)
        if stars is None or not 0 <= stars <= 10:
            errors.append('{} stars must be an integer from 0 to 10'.format(course))
            output['courses'][course] = None
            continue
        output['courses'][course] = {
            'stars': stars,
            'branch': bool(request.form.get('branch_{}'.format(course)))
        }
    if not any(output['courses'].values()):
        errors.append('at least one course is required')

    output['category_id'] = optional_form_int('category_id', errors)
    output['skin_id'] = optional_form_int('skin_id', errors)
    output['maker_id'] = optional_form_int('maker_id', errors)
    output['type'] = (request.form.get('type') or '').strip().lower()
    output['music_type'] = (request.form.get('music_type') or '').strip().lower()
    output['offset'] = required_form_float('offset', -86400, 86400, errors)
    output['preview'] = required_form_float('preview', 0, 86400, errors)
    output['volume'] = required_form_float('volume', 0, 4, errors)
    output['lyrics'] = bool(request.form.get('lyrics'))
    output['hash'] = (request.form.get('hash') or '').strip()
    output['id'] = song_id

    if output['type'] not in ('tja', 'osu'):
        errors.append('invalid chart type')
    if output['music_type'] not in UPLOAD_ALLOWED_MUSIC_TYPES:
        errors.append('invalid music type')
    if not reference_exists(db.categories, output['category_id']):
        errors.append('category does not exist')
    if not reference_exists(db.song_skins, output['skin_id']):
        errors.append('skin does not exist')
    if not reference_exists(db.makers, output['maker_id']):
        errors.append('maker does not exist')
    return output, errors


def validate_admin_song_document(song, existing_id=None):
    errors = []
    song_hash = song.get('hash')
    if not song_hash or len(song_hash) > 500 or '\x00' in song_hash:
        errors.append('hash is required and must not exceed 500 characters')
    else:
        duplicate_query = {'hash': song_hash}
        if existing_id is not None:
            duplicate_query['id'] = {'$ne': existing_id}
        if db.songs.find_one(duplicate_query, {'_id': True}):
            errors.append('hash is already in use')

    if db.songs.find_one({'id': song.get('id')}, {'_id': True}) and existing_id is None:
        errors.append('song ID is already in use')

    if song.get('enabled') and not public_song_files_available(song):
        errors.append('enabled songs require matching chart and audio files')
    elif song.get('enabled') and songs_use_local_storage():
        music_path = SONGS_DIR / str(song.get('id')) / 'main.{}'.format(song.get('music_type'))
        try:
            header = music_path.read_bytes()[:4096]
        except OSError:
            errors.append('audio file could not be read')
        else:
            if not music_signature_matches(header, song.get('music_type')):
                errors.append('audio content does not match its format')
    return errors


def normalize_admin_song(song):
    song = dict(song or {})
    song['title_lang'] = safe_lang_map(song.get('title_lang'))
    song['subtitle_lang'] = safe_lang_map(song.get('subtitle_lang'))
    normalized_courses = normalize_song_courses(song.get('courses'))
    song['courses'] = {
        course: normalized_courses.get(course) or {}
        for course in ADMIN_COURSES
    }
    song.setdefault('enabled', False)
    song.setdefault('title', 'Untitled')
    song.setdefault('subtitle', '')
    song.setdefault('category_id', None)
    song.setdefault('skin_id', None)
    song.setdefault('maker_id', None)
    song.setdefault('music_type', 'mp3')
    song.setdefault('type', 'tja')
    song.setdefault('offset', 0)
    song.setdefault('preview', 0)
    song.setdefault('volume', 1)
    song.setdefault('hash', '')
    song['storage_available'] = public_song_files_available(song)
    return song


def normalize_public_song(song):
    song = dict(song or {})
    if song.get('id') is None:
        return None

    song['title'] = song.get('title') or 'Untitled'
    song['subtitle'] = song.get('subtitle') or ''
    song['title_lang'] = safe_lang_map(song.get('title_lang'))
    song['subtitle_lang'] = safe_lang_map(song.get('subtitle_lang'))
    song['courses'] = normalize_song_courses(song.get('courses'))
    song['type'] = song.get('type') if song.get('type') in ('tja', 'osu') else 'tja'
    song['music_type'] = song.get('music_type') or 'mp3'
    song['preview'] = safe_float_value(song.get('preview'), 0)
    song['volume'] = safe_float_value(song.get('volume'), 1.0)
    song['lyrics'] = bool(song.get('lyrics'))
    song['hash'] = song.get('hash') or song['title']
    song.setdefault('song_type', '')
    song.setdefault('order', song.get('id'))
    return song


def build_id_map(items):
    output = {}
    for item in items:
        item_id = item.get('id')
        if item_id is None:
            continue
        output[item_id] = item
        output[str(item_id)] = item
        int_id = safe_int_value(item_id)
        if int_id is not None:
            output[int_id] = item
    return output


def get_public_song_context():
    return {
        'categories_by_id': build_id_map(list(db.categories.find({}, {'_id': False}))),
        'makers_by_id': build_id_map(list(db.makers.find({}, {'_id': False}))),
        'song_skins_by_id': build_id_map(list(db.song_skins.find({}, {'_id': False})))
    }


def serialize_public_song(raw_song, context=None):
    song = normalize_public_song(raw_song)
    if not song:
        return None
    context = context or get_public_song_context()
    song.pop('_id', None)
    song.pop('enabled', None)

    maker_id = song.get('maker_id')
    if maker_id is not None:
        if maker_id == 0:
            song['maker'] = 0
        else:
            makers_by_id = context['makers_by_id']
            song['maker'] = makers_by_id.get(maker_id) or makers_by_id.get(safe_int_value(maker_id)) or makers_by_id.get(str(maker_id))
    else:
        song['maker'] = None
    song.pop('maker_id', None)

    category_id = song.get('category_id')
    if category_id is not None:
        categories_by_id = context['categories_by_id']
        category = categories_by_id.get(category_id) or categories_by_id.get(safe_int_value(category_id)) or categories_by_id.get(str(category_id))
        song['category'] = category.get('title') if category else None
    else:
        song['category'] = None

    skin_id = song.get('skin_id')
    if skin_id is not None:
        song_skins_by_id = context['song_skins_by_id']
        song_skin = song_skins_by_id.get(skin_id) or song_skins_by_id.get(safe_int_value(skin_id)) or song_skins_by_id.get(str(skin_id))
        song['song_skin'] = {
            key: value
            for key, value in song_skin.items()
            if key != 'id'
        } if song_skin else None
    else:
        song['song_skin'] = None
    song.pop('skin_id', None)

    return song


def sequence_floor(name):
    if name != 'songs':
        return 0
    values = (
        safe_int_value(song.get('id'))
        for song in db.songs.find({}, {'_id': False, 'id': True})
    )
    return max((value for value in values if value is not None), default=0)


def sequence_state(name):
    documents = list(db.seq.find({'name': name}).limit(100))
    floor = sequence_floor(name)
    if not documents:
        try:
            result = db.seq.insert_one({'name': name, 'value': floor})
            return result.inserted_id, floor
        except DuplicateKeyError:
            documents = list(db.seq.find({'name': name}).limit(100))
    if not documents:
        raise RuntimeError('Unable to initialize sequence {}'.format(name))

    primary = min(documents, key=lambda document: str(document['_id']))
    valid_values = [
        value
        for value in (safe_int_value(document.get('value')) for document in documents)
        if value is not None
    ]
    current = max(valid_values + [floor])
    stored = primary.get('value')
    if isinstance(stored, bool) or not isinstance(stored, int) or stored != current:
        result = db.seq.update_one(
            {'_id': primary['_id'], 'value': stored},
            {'$set': {'value': current}}
        )
        if not result.modified_count and stored != current:
            return sequence_state(name)
    return primary['_id'], current


def next_sequence_value(name):
    _, current = sequence_state(name)
    return current + 1


def allocate_sequence_value(name):
    for _ in range(20):
        document_id, current = sequence_state(name)
        updated = db.seq.find_one_and_update(
            {'_id': document_id, 'value': current},
            {'$inc': {'value': 1}},
            return_document=ReturnDocument.AFTER
        )
        if updated:
            return updated['value']
    raise RuntimeError('Unable to allocate sequence {}'.format(name))


def admin_category_title(category):
    if not category:
        return None
    title_lang = safe_lang_map(category.get('title_lang'))
    return title_lang.get('en') or category.get('title') or 'Untitled category'


def build_admin_song_groups(songs, categories):
    category_by_id = {}
    for category in categories:
        category_id = category.get('id')
        if category_id is not None:
            category_by_id[category_id] = category
            category_by_id[safe_int_value(category_id)] = category
    groups = {}

    def ensure_group(key, title, sort_key):
        if key not in groups:
            groups[key] = {
                'title': title,
                'sort_key': sort_key,
                'songs': [],
                'enabled_count': 0
            }
        return groups[key]

    for category in categories:
        category_id = category.get('id')
        if category_id is not None:
            ensure_group(
                ('category', category_id),
                admin_category_title(category),
                (0, safe_int_value(category_id, 999999), admin_category_title(category))
            )

    for song in songs:
        category_id = song.get('category_id')
        if category_id is not None:
            category = category_by_id.get(category_id) or category_by_id.get(safe_int_value(category_id))
            if category:
                group = ensure_group(
                    ('category', category_id),
                    admin_category_title(category),
                    (0, safe_int_value(category_id, 999999), admin_category_title(category))
                )
            else:
                group = ensure_group(
                    ('missing-category', category_id),
                    'Missing category #{}'.format(category_id),
                    (1, safe_int_value(category_id, 999999), '')
                )
        elif song.get('song_type'):
            song_type = song.get('song_type')
            group = ensure_group(
                ('song-type', song_type),
                song_type,
                (2, song_type)
            )
        else:
            group = ensure_group(
                ('uncategorized', ''),
                'Uncategorized',
                (3, '')
            )

        group['songs'].append(song)
        if song.get('enabled'):
            group['enabled_count'] += 1

    return [
        group
        for group in sorted(groups.values(), key=lambda item: item['sort_key'])
        if group['songs']
    ]

def get_default_don(part=None):
    if part == None:
        return {
            'body_fill': get_default_don('body_fill'),
            'face_fill': get_default_don('face_fill')
        }
    elif part == 'body_fill':
        return '#5fb7c1'
    elif part == 'face_fill':
        return '#ff5724'

def is_hex(input):
    try:
        int(input, 16)
        return True
    except ValueError:
        return False


@app.route(basedir)
def route_index():
    return render_index_page(SEO_DEFAULT_LANG)


@app.route(basedir + '<lang_code>', strict_slashes=False)
def route_localized_index(lang_code):
    lang = resolve_seo_lang(lang_code)
    if not lang:
        abort(404)
    canonical_path = localized_index_path(lang)
    if request.path != canonical_path:
        return redirect(canonical_path, code=302)
    return render_index_page(lang)


@app.route(basedir + 'board')
def route_board():
    posts = get_board_posts()
    version = get_version()
    return render_template('board.html', posts=posts, version=version, config=get_config())


@app.route(basedir + 'api/board/posts')
def route_api_board_posts():
    posts = get_board_posts()
    return jsonify({'status': 'ok', 'posts': posts})


@app.route(basedir + 'api/board/posts', methods=['POST'])
@limiter.limit("10 per minute")
def route_api_board_posts_create():
    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    message = (data.get('message') or '').strip()

    if not name:
        name = 'Anonymous'
    if not message:
        return api_error('message_required')
    if len(name) > BOARD_MAX_NAME_LENGTH:
        return api_error('name_too_long')
    if len(message) > BOARD_MAX_MESSAGE_LENGTH:
        return api_error('message_too_long')
    if board_contains_blocked_word(name, message):
        return api_error('blocked_word')
    if board_contains_link(name, message):
        return api_error('link_not_allowed')

    user = None
    if session.get('username'):
        user = db.users.find_one({'username': session.get('username')})

    post = {
        'name': name,
        'message': message,
        'created_at': utc_now(),
        'username': session.get('username'),
        'user_display_name': get_user_display_name(user) if user else None,
        'ip_hash': hashlib.sha256(get_remote_address().encode('utf-8')).hexdigest()
    }
    result = db.board_posts.insert_one(post)
    post['_id'] = result.inserted_id

    return jsonify({'status': 'ok', 'post': serialize_board_post(post)})


@app.route(basedir + 'repair')
def route_repair():
    return render_index_page(SEO_DEFAULT_LANG)


@app.route(basedir + 'api/csrftoken')
def route_csrftoken():
    return jsonify({'status': 'ok', 'token': generate_csrf()})


@app.route(basedir + 'api/visits/record', methods=['POST'])
@limiter.limit("30 per hour")
def route_api_visits_record():
    data = request.get_json(silent=True) or {}
    if not schema.validate(data, schema.visit_record):
        return abort(400)

    visitor_id = (data.get('visitor_id') or '').strip()
    if not re.match(r'^[a-f0-9]{32}$', visitor_id):
        visitor_id = hashlib.sha256(get_remote_address().encode('utf-8')).hexdigest()
    username = session.get('username') or None
    visitor_key = 'user:{}'.format(username) if username else 'visitor:{}'.format(visitor_id)

    db.visit_records.insert_one({
        'visitor_id': visitor_id,
        'visitor_key': visitor_key,
        'username': username,
        'ip_hash': hashlib.sha256(get_remote_address().encode('utf-8')).hexdigest(),
        'user_agent_hash': hashlib.sha256((request.headers.get('User-Agent') or '').encode('utf-8')).hexdigest(),
        'entered_at': utc_now()
    })

    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/site-messages')
def route_api_site_messages():
    if not FEATURE_SITE_MESSAGES:
        return jsonify({
            'status': 'ok',
            'logged_in': bool(session.get('username')),
            'messages': [],
            'unread_count': 0
        })
    messages = get_site_messages(request.args.get('limit', 50), active_only=True)
    message_ids = [str(message.get('_id')) for message in messages]
    username = session.get('username')
    read_ids = get_site_message_read_ids(username, message_ids)
    serialized = [serialize_site_message(message, read_ids) for message in messages]

    return jsonify({
        'status': 'ok',
        'logged_in': bool(username),
        'messages': serialized,
        'unread_count': sum(1 for message in serialized if not message['read'])
    })


@app.route(basedir + 'api/site-messages/<message_id>/read', methods=['POST'])
@login_required
def route_api_site_messages_read(message_id):
    if not FEATURE_SITE_MESSAGES:
        return abort(404)
    object_id = object_id_or_404(message_id)
    if not db.site_messages.find_one({'_id': object_id, 'active': True}, {'_id': True}):
        return abort(404)

    db.site_message_reads.update_one({
        'username': session.get('username'),
        'message_id': message_id
    }, {
        '$setOnInsert': {
            'username': session.get('username'),
            'message_id': message_id,
            'read_at': utc_now()
        }
    }, upsert=True)

    return jsonify({'status': 'ok'})


def get_current_admin(min_level=50):
    username = session.get('username')
    if not username:
        return None
    user = db.users.find_one({'username': username})
    if user and get_user_level(user) >= min_level:
        return user
    return None


@app.route(basedir + '1128admin1128', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def route_secret_admin_login():
    if not FEATURE_ADMIN:
        return abort(404)
    if request.method == 'GET' and get_current_admin(50):
        return redirect(basedir + 'admin/overview')

    username = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').encode('utf-8')
        user = find_user_by_username(username)
        password_ok = check_user_password(user, password)
        if (
            user and
            get_user_level(user) >= 50 and
            password_ok
        ):
            session_id = ensure_user_session_id(user)
            session.clear()
            session['session_id'] = session_id
            session['username'] = user.get('username')
            session.permanent = True
            return redirect(basedir + 'admin/overview')

        flash('Invalid admin username or password.', 'error')

    return render_template('admin_login.html', config=get_config(), username=username)


@app.route(basedir + 'admin')
@admin_required(level=50)
def route_admin():
    return redirect(basedir + 'admin/overview')


@app.route(basedir + 'admin/overview')
@admin_required(level=50)
def route_admin_overview():
    user = db.users.find_one({'username': session['username']})
    return render_template('admin_overview.html',
        stats=get_admin_overview_stats(), admin=user, config=get_config())


@app.route(basedir + 'admin/top-songs/refresh', methods=['POST'])
@admin_required(level=50)
def route_admin_top_songs_refresh():
    result = refresh_top_songs_cache(
        force=True,
        requested_by=session.get('username'),
        allow_backfill=True
    )

    status = result.get('status')
    if status == 'updated':
        flash(
            'Top10 cache refreshed: {} songs, {} ms.'.format(
                result.get('rows_count', 0),
                result.get('refresh_ms', 0)
            )
        )
    elif status == 'busy':
        flash('Top10 refresh is already running. Please try again later.', 'error')
    elif status == 'needs_backfill':
        flash('Top10 refresh needs a manual backfill, but no safe cache was changed.', 'error')
    elif status == 'error':
        flash('Top10 refresh failed: {}'.format(result.get('error') or 'unknown error'), 'error')
    else:
        flash('Top10 cache is already fresh.')

    return redirect(basedir + 'admin/overview')


@app.route(basedir + 'admin/messages')
@admin_required(level=50)
def route_admin_messages():
    messages = get_site_messages(100, active_only=False)
    user = db.users.find_one({'username': session['username']})
    return render_template('admin_messages.html',
        messages=messages, admin=user, config=get_config())


@app.route(basedir + 'admin/messages', methods=['POST'])
@admin_required(level=50)
def route_admin_messages_post():
    title = (request.form.get('title') or '').strip()
    body = (request.form.get('body') or '').strip()
    image_url = (request.form.get('image_url') or '').strip()

    if len(title) > SITE_MESSAGE_MAX_TITLE_LENGTH:
        flash('Error: Title is too long.', 'error')
        return redirect(basedir + 'admin/messages')
    if len(body) > SITE_MESSAGE_MAX_BODY_LENGTH:
        flash('Error: Message is too long.', 'error')
        return redirect(basedir + 'admin/messages')
    if len(image_url) > SITE_MESSAGE_MAX_IMAGE_URL_LENGTH:
        flash('Error: Image URL is too long.', 'error')
        return redirect(basedir + 'admin/messages')
    if image_url and not (image_url.startswith('http://') or image_url.startswith('https://') or image_url.startswith('/')):
        flash('Error: Image URL must start with http://, https://, or /.', 'error')
        return redirect(basedir + 'admin/messages')

    try:
        uploaded_url = save_site_message_image(request.files.get('image_file'))
    except ValueError as e:
        flash('Error: {}'.format(e), 'error')
        return redirect(basedir + 'admin/messages')

    if uploaded_url:
        image_url = uploaded_url
    if not title and not body and not image_url:
        flash('Error: Please enter text or upload an image.', 'error')
        return redirect(basedir + 'admin/messages')

    try:
        db.site_messages.insert_one({
            'title': title,
            'body': body,
            'image_url': image_url,
            'active': bool(request.form.get('active')),
            'created_at': utc_now(),
            'created_by': session.get('username')
        })
    except PyMongoError:
        if uploaded_url:
            remove_site_message_image(uploaded_url)
        app.logger.exception('Could not publish site message')
        flash('Error: Message could not be saved.', 'error')
        return redirect(basedir + 'admin/messages')
    flash('Message published.')
    return redirect(basedir + 'admin/messages')


@app.route(basedir + 'admin/messages/<message_id>/remove', methods=['POST'])
@admin_required(level=50)
def route_admin_messages_remove(message_id):
    object_id = object_id_or_404(message_id)
    message = db.site_messages.find_one({'_id': object_id})
    if not message:
        return abort(404)
    result = db.site_messages.delete_one({'_id': object_id})
    if result.deleted_count:
        try:
            remove_site_message_image(message.get('image_url'))
        except OSError:
            app.logger.exception('Could not remove image for message %s', message_id)
    db.site_message_reads.delete_many({'message_id': message_id})
    flash('Message removed.')
    return redirect(basedir + 'admin/messages')


@app.route(basedir + 'admin/messages/<message_id>/toggle', methods=['POST'])
@admin_required(level=50)
def route_admin_messages_toggle(message_id):
    object_id = object_id_or_404(message_id)
    message = db.site_messages.find_one({'_id': object_id})
    if not message:
        return abort(404)

    db.site_messages.update_one({'_id': object_id}, {'$set': {
        'active': not bool(message.get('active', True))
    }})
    flash('Message updated.')
    return redirect(basedir + 'admin/messages')


@app.route(basedir + 'admin/songs')
@admin_required(level=50)
def route_admin_songs():
    songs = sorted(
        [normalize_admin_song(song) for song in db.songs.find({})],
        key=lambda song: (
            song.get('id') is None,
            safe_int_value(song.get('id'), 999999),
            str(song.get('id') or ''),
            song.get('title') or ''
        )
    )
    categories = list(db.categories.find({}))
    song_groups = build_admin_song_groups(songs, categories)
    user = db.users.find_one({'username': session['username']})
    return render_template('admin_songs.html',
        songs=songs, song_groups=song_groups, admin=user, categories=categories, config=get_config())


@app.route(basedir + 'admin/songs/<song_id>')
@admin_required(level=50)
def route_admin_songs_id(song_id):
    song = find_song_by_route_id(song_id)
    if not song:
        return abort(404)
    song = normalize_admin_song(song)

    categories = list(db.categories.find({}))
    song_skins = list(db.song_skins.find({}))
    makers = list(db.makers.find({}))
    user = db.users.find_one({'username': session['username']})

    return render_template('admin_song_detail.html',
        song=song, song_stats=get_admin_song_stats(song),
        categories=categories, song_skins=song_skins, makers=makers, admin=user, config=get_config())


@app.route(basedir + 'admin/songs/new')
@admin_required(level=100)
def route_admin_songs_new():
    categories = list(db.categories.find({}))
    song_skins = list(db.song_skins.find({}))
    makers = list(db.makers.find({}))
    seq_new = next_sequence_value('songs')

    return render_template('admin_song_new.html', categories=categories, song_skins=song_skins, makers=makers, config=get_config(), id=seq_new)


@app.route(basedir + 'admin/songs/new', methods=['POST'])
@admin_required(level=100)
def route_admin_songs_new_post():
    seq_new = allocate_sequence_value('songs')
    output, errors = build_admin_song_form(seq_new)
    if request.form.get('gen_hash'):
        try:
            output['hash'] = generate_hash(seq_new, request.form)
        except HashException as e:
            errors.append(str(e))
    output['order'] = seq_new
    errors.extend(validate_admin_song_document(output))
    if errors:
        for error in errors:
            flash('Error: {}'.format(error), 'error')
        return redirect(basedir + 'admin/songs/new')

    try:
        db.songs.insert_one(output)
    except DuplicateKeyError:
        flash('Error: Song ID or hash already exists.', 'error')
        return redirect(basedir + 'admin/songs/new')
    flash('Song created.')
    invalidate_song_derived_caches()
    
    return redirect(basedir + 'admin/songs/%s' % str(seq_new))


@app.route(basedir + 'admin/songs/<song_id>', methods=['POST'])
@admin_required(level=50)
def route_admin_songs_id_post(song_id):
    song = find_song_by_route_id(song_id)
    if not song:
        return abort(404)
    song_id = song.get('id')

    user = db.users.find_one({'username': session['username']})
    user_level = get_user_level(user)

    output, errors = build_admin_song_form(
        song_id,
        existing=song,
        can_set_enabled=user_level >= 100
    )
    if request.form.get('gen_hash'):
        try:
            output['hash'] = generate_hash(song_id, request.form)
        except HashException as e:
            errors.append(str(e))
    errors.extend(validate_admin_song_document(output, existing_id=song_id))
    if errors:
        for error in errors:
            flash('Error: {}'.format(error), 'error')
        return redirect(basedir + 'admin/songs/{}'.format(song_id))

    db.songs.update_one({'id': song_id}, {'$set': output})
    flash('Changes saved.')
    invalidate_song_derived_caches()
    
    return redirect(basedir + 'admin/songs/%s' % song_id)


@app.route(basedir + 'admin/songs/<song_id>/remove', methods=['POST'])
@limiter.limit("30 per minute")
@admin_required(level=100)
def route_admin_songs_id_remove(song_id):
    song = find_song_by_route_id(song_id)
    if not song:
        return abort(404)

    stored_song_id = song.get('id')
    db.songs.delete_one({'id': stored_song_id})
    if is_public_song_id(stored_song_id) and not str(stored_song_id).isdigit():
        try:
            song_path = song_storage_child(str(stored_song_id))
            if song_path.exists() or song_path.is_symlink():
                remove_song_storage_entry(song_path)
        except Exception:
            app.logger.exception('Failed to remove files for song %s', stored_song_id)
    invalidate_song_derived_caches()
    flash('Song removed.')
    return redirect(basedir + 'admin/songs')


@app.route(basedir + 'admin/users')
@admin_required(level=50)
def route_admin_users():
    user = db.users.find_one({'username': session.get('username')})
    max_level = max(0, get_user_level(user) - 1)
    return render_template('admin_users.html', config=get_config(), max_level=max_level, username='', level='')


@app.route(basedir + 'admin/users', methods=['POST'])
@admin_required(level=50)
def route_admin_users_post():
    admin_name = session.get('username')
    admin = db.users.find_one({'username': admin_name})
    max_level = max(0, get_user_level(admin) - 1)
    
    username = (request.form.get('username') or '').strip()
    level = form_int('level', 0) or 0
    
    user = find_user_by_username(username)
    if not username:
        flash('Error: Username is required.')
    elif not user:
        flash('Error: User was not found.')
    elif admin.get('username') == user.get('username'):
        flash('Error: You cannot modify your own level.')
    else:
        user_level = get_user_level(user)
        if level < 0 or level > max_level:
            flash('Error: Invalid level.')
        elif user_level > max_level:
            flash('Error: This user has higher level than you.')
        else:
            output = {'user_level': level}
            db.users.update_one({'username': user['username']}, {'$set': output})
            flash('User updated.')
    
    return render_template('admin_users.html', config=get_config(), max_level=max_level, username=username, level=level)


@app.route(basedir + 'api/preview')
@app.cache.cached(timeout=15, query_string=True)
def route_api_preview():
    song_id = request.args.get('id', None)
    if not is_public_song_id(song_id):
        abort(400)

    song_id = route_song_id(song_id)
    song = db.songs.find_one({'id': song_id, 'enabled': True})
    if not song:
        abort(400)
    if not public_song_files_available(song):
        abort(404)
    song = normalize_public_song(song)
    if not song:
        abort(400)

    song_type = song.get('type', 'tja')
    song_ext = song.get('music_type') or "mp3"
    prev_path = make_preview(song_id, song_type, song_ext, song.get('preview', 0))
    if not prev_path:
        return redirect(get_config()['songs_baseurl'] + '%s/main.%s' % (song_id, song_ext))

    return redirect(get_config()['songs_baseurl'] + '%s/preview.mp3' % song_id)


@app.route(basedir + 'api/songs')
def route_api_songs():
    type_q = flask.request.args.get('type')
    query = {'enabled': True}
    if type_q:
        if type_q not in SONG_TYPES:
            return abort(400)
        query['song_type'] = type_q

    cache_key = 'api_songs:{}:{}'.format(type_q or 'all', get_public_songs_cache_version())
    cached_songs = app.cache.get(cache_key)
    if cached_songs is not None:
        return cache_wrap(flask.jsonify(cached_songs), 60)

    raw_songs = list(db.songs.find(query, {'_id': False, 'enabled': False}))
    context = get_public_song_context()
    songs = []
    for raw_song in raw_songs:
        if not public_song_files_available(raw_song):
            continue
        song = serialize_public_song(raw_song, context)
        if not song:
            continue
        songs.append(song)

    app.cache.set(cache_key, songs, timeout=PUBLIC_SONGS_CACHE_SECONDS)
    return cache_wrap(flask.jsonify(songs), 60)


@app.route(basedir + 'api/songs/top10')
def route_api_songs_top10():
    if not FEATURE_TOP_SONGS:
        return abort(404)
    songs = get_public_top_songs(request.args.get('limit', 10))
    return cache_wrap(jsonify({
        'status': 'ok',
        'songs': songs,
        'cache_seconds': PUBLIC_TOP_SONGS_CACHE_SECONDS
    }), PUBLIC_TOP_SONGS_CACHE_SECONDS)


@app.route(basedir + 'api/categories')
@app.cache.cached(timeout=15)
def route_api_categories():
    categories = list(db.categories.find({},{'_id': False}))
    if not any(category.get('id') == CUSTOM_CATEGORY['id'] or category.get('title') == CUSTOM_CATEGORY['title'] for category in categories):
        categories.append(CUSTOM_CATEGORY)
    return jsonify(categories)

@app.route(basedir + 'api/config')
def route_api_config():
    response = jsonify(get_config(credentials=True))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['CDN-Cache-Control'] = 'no-store'
    return response


@app.route(basedir + 'api/register', methods=['POST'])
@limiter.limit("5 per hour")
def route_api_register():
    data = request.get_json()
    if not schema.validate(data, schema.register):
        return abort(400)

    if session.get('username'):
        session.clear()

    username = data.get('username', '')
    if len(username) < 3 or len(username) > 20 or not re.match('^[a-zA-Z0-9_]{3,20}$', username):
        return api_error('invalid_username')

    if find_user_by_username(username):
        return api_error('username_in_use')

    password = data.get('password', '').encode('utf-8')
    if not 6 <= len(password) <= 72:
        return api_error('invalid_password')

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password, salt)
    don = get_default_don()
    
    session_id = os.urandom(24).hex()
    try:
        db.users.insert_one({
            'username': username,
            'username_lower': username.lower(),
            'password': hashed,
            'display_name': username,
            'don': don,
            'user_level': 1,
            'session_id': session_id
        })
    except DuplicateKeyError:
        return api_error('username_in_use')

    session['session_id'] = session_id
    session['username'] = username
    session.permanent = True
    return jsonify({'status': 'ok', 'username': username, 'display_name': username, 'don': don})


@app.route(basedir + 'api/login', methods=['POST'])
@limiter.limit("20 per minute")
def route_api_login():
    data = request.get_json()
    if not schema.validate(data, schema.login):
        return abort(400)

    if session.get('username'):
        session.clear()

    username = data.get('username', '')
    result = find_user_by_username(username)
    if not result:
        return api_error('invalid_username_password')

    password = data.get('password', '').encode('utf-8')
    if not check_user_password(result, password):
        return api_error('invalid_username_password')
    
    don = get_db_don(result)
    session_id = ensure_user_session_id(result)
    
    session['session_id'] = session_id
    session['username'] = result['username']
    session.permanent = True if data.get('remember') else False

    return jsonify({
        'status': 'ok',
        'username': result['username'],
        'display_name': get_user_display_name(result, result['username']),
        'don': don
    })


@app.route(basedir + 'api/logout', methods=['POST'])
@login_required
def route_api_logout():
    session.clear()
    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/account/display_name', methods=['POST'])
@login_required
def route_api_account_display_name():
    data = request.get_json()
    if not schema.validate(data, schema.update_display_name):
        return abort(400)

    display_name = data.get('display_name', '').strip()
    if not display_name:
        display_name = session.get('username')
    elif len(display_name) > 25:
        return api_error('invalid_display_name')
    
    db.users.update_one({'username': session.get('username')}, {
        '$set': {'display_name': display_name}
    })

    return jsonify({'status': 'ok', 'display_name': display_name})


@app.route(basedir + 'api/account/don', methods=['POST'])
@login_required
def route_api_account_don():
    data = request.get_json()
    if not schema.validate(data, schema.update_don):
        return abort(400)
    
    don_body_fill = data.get('body_fill', '').strip()
    don_face_fill = data.get('face_fill', '').strip()
    if len(don_body_fill) != 7 or\
        not don_body_fill.startswith("#")\
        or not is_hex(don_body_fill[1:])\
        or len(don_face_fill) != 7\
        or not don_face_fill.startswith("#")\
        or not is_hex(don_face_fill[1:]):
        return api_error('invalid_don')
    
    db.users.update_one({'username': session.get('username')}, {'$set': {
        'don_body_fill': don_body_fill,
        'don_face_fill': don_face_fill,
    }})
    
    return jsonify({'status': 'ok', 'don': {'body_fill': don_body_fill, 'face_fill': don_face_fill}})


@app.route(basedir + 'api/account/password', methods=['POST'])
@limiter.limit("5 per hour")
@login_required
def route_api_account_password():
    data = request.get_json()
    if not schema.validate(data, schema.update_password):
        return abort(400)

    user = db.users.find_one({'username': session.get('username')})
    if not user:
        session.clear()
        return api_error('not_logged_in')
    current_password = data.get('current_password', '').encode('utf-8')
    if not check_user_password(user, current_password):
        return api_error('current_password_invalid')
    
    new_password = data.get('new_password', '').encode('utf-8')
    if not 6 <= len(new_password) <= 72:
        return api_error('invalid_new_password')
    
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(new_password, salt)
    session_id = os.urandom(24).hex()

    db.users.update_one({'username': session.get('username')}, {
        '$set': {'password': hashed, 'session_id': session_id}
    })

    session['session_id'] = session_id
    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/account/remove', methods=['POST'])
@limiter.limit("1 per day")
@login_required
def route_api_account_remove():
    data = request.get_json()
    if not schema.validate(data, schema.delete_account):
        return abort(400)

    user = db.users.find_one({'username': session.get('username')})
    if not user:
        session.clear()
        return api_error('not_logged_in')
    password = data.get('password', '').encode('utf-8')
    if not check_user_password(user, password):
        return api_error('verify_password_invalid')

    username = session.get('username')
    db.scores.delete_many({'username': username})
    db.weekly_challenge_scores.delete_many({'username': username})
    db.site_message_reads.delete_many({'username': username})
    deleted_identity = 'deleted:{}'.format(uuid.uuid4().hex)
    db.play_records.update_many(
        {'username': username},
        {'$set': {'username': None}}
    )
    db.visit_records.update_many(
        {'username': username},
        {
            '$set': {'username': None, 'visitor_key': deleted_identity},
            '$unset': {'visitor_id': ''}
        }
    )
    db.board_posts.update_many(
        {'username': username},
        {
            '$set': {'username': None},
            '$unset': {'user_display_name': ''}
        }
    )
    db.leaderboard.update_many(
        {'username': username},
        {'$set': {'username': None}}
    )
    db.site_messages.update_many(
        {'created_by': username},
        {'$set': {'created_by': 'Deleted administrator'}}
    )
    db.users.delete_one({'username': username})

    session.clear()
    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/scores/save', methods=['POST'])
@limiter.limit("30 per minute")
@login_required
def route_api_scores_save():
    data = request.get_json()
    if not schema.validate(data, schema.scores_save):
        return abort(400)

    username = session.get('username')
    scores_by_hash = {
        score['hash']: score['score']
        for score in data.get('scores', [])
    }
    operations = [
        UpdateOne(
            {'username': username, 'hash': song_hash},
            {'$set': {
                'username': username,
                'hash': song_hash,
                'score': score
            }},
            upsert=True
        )
        for song_hash, score in scores_by_hash.items()
    ]
    try:
        if operations:
            db.scores.bulk_write(operations, ordered=True)
    except PyMongoError:
        app.logger.exception('Score import failed for user %s', username)
        return api_error('score_save_failed'), 503

    if data.get('is_import'):
        stale_query = {'username': username}
        if scores_by_hash:
            stale_query['hash'] = {'$nin': list(scores_by_hash)}
        db.scores.delete_many(stale_query)

    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/scores/get')
@login_required
def route_api_scores_get():
    username = session.get('username')

    scores = []
    for score in db.scores.find({'username': username}):
        if 'hash' not in score or 'score' not in score:
            continue
        scores.append({
            'hash': score['hash'],
            'score': score['score']
        })

    user = db.users.find_one({'username': username})
    if not user:
        session.clear()
        return api_error('not_logged_in')
    don = get_db_don(user)
    return jsonify({
        'status': 'ok',
        'scores': scores,
        'username': user.get('username') or username,
        'display_name': get_user_display_name(user, username),
        'don': don
    })


@app.route(basedir + 'api/playcount/record', methods=['POST'])
@limiter.limit("120 per hour")
def route_api_playcount_record():
    data = request.get_json()
    if not schema.validate(data, schema.playcount_record):
        return abort(400)

    username = session.get('username') if session.get('username') else None
    played_at = utc_now()
    song_hash = data.get('hash')
    song = find_enabled_song_by_identity(song_hash)
    if not song or not song_has_course(song, data.get('difficulty')):
        return abort(400)

    db.play_records.insert_one({
        'song_hash': song_hash,
        'difficulty': data.get('difficulty'),
        'username': username,
        'score': data.get('score'),
        'is_auto': data.get('is_auto'),
        'played_at': played_at
    })
    record_song_play_count(song_hash, played_at)

    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/playcount/get')
@limiter.limit("120 per minute")
def route_api_playcount_get():
    song_hash = request.args.get('hash', None)
    if not song_hash or len(song_hash) > 500:
        return abort(400)

    count_doc = db.song_play_counts.find_one(
        {'_id': song_hash},
        {'_id': False, 'play_count': True}
    )
    if count_doc:
        play_count = count_doc.get('play_count', 0)
    else:
        try:
            play_count = db.play_records.count_documents(
                {'song_hash': song_hash},
                maxTimeMS=ADMIN_STATS_MAX_TIME_MS
            )
        except PyMongoError:
            play_count = 0

    today = utc_now()
    start_of_week = today - timedelta(days=today.weekday(), hours=today.hour, minutes=today.minute, seconds=today.second, microseconds=today.microsecond)
    try:
        weekly_rows = list(db.play_records.aggregate([
            {'$match': {
                'song_hash': song_hash,
                'is_auto': False,
                'played_at': {'$gte': start_of_week}
            }},
            {'$group': {
                '_id': None,
                'score': {'$max': '$score'}
            }}
        ], maxTimeMS=ADMIN_STATS_MAX_TIME_MS, allowDiskUse=False))
        weekly_high_score = weekly_rows[0].get('score') if weekly_rows else None
    except PyMongoError:
        weekly_high_score = None

    return jsonify({
        'status': 'ok',
        'play_count': play_count,
        'weekly_high_score': weekly_high_score
    })


@app.route(basedir + 'api/leaderboard/submit', methods=['POST'])
@limiter.limit("30 per hour")
def route_api_leaderboard_submit():
    data = request.get_json(silent=True) or {}
    song_hash = data.get('hash')
    difficulty = data.get('difficulty')
    display_name = data.get('display_name', 'Anonymous')
    raw_score = data.get('score')

    if not isinstance(song_hash, str) or not 1 <= len(song_hash) <= 500:
        return abort(400)
    if not isinstance(difficulty, str) or not 1 <= len(difficulty) <= 32:
        return abort(400)
    if not isinstance(display_name, str) or len(display_name) > 100:
        return abort(400)
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        return abort(400)
    if not math.isfinite(raw_score) or raw_score < 0 or raw_score > 1000000000:
        return abort(400)
    score_value = int(raw_score)
    if score_value != raw_score:
        return abort(400)
    song = find_enabled_song_by_identity(song_hash)
    if not song or not song_has_course(song, difficulty):
        return abort(400)

    if not display_name or not display_name.strip():
        display_name = 'Anonymous'

    current_month = utc_now().strftime('%Y-%m')
    db.leaderboard.insert_one({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'display_name': display_name.strip()[:20],
        'score_value': score_value,
        'month': current_month,
        'created_at': utc_now()
    })

    higher_count = db.leaderboard.count_documents({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'month': current_month,
        'score_value': {'$gt': score_value}
    }, maxTimeMS=ADMIN_STATS_MAX_TIME_MS)
    rank = higher_count + 1

    stale_scores = list(db.leaderboard.find({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'month': current_month
    }, {'_id': True})
        .sort('score_value', -1)
        .skip(100)
        .limit(1000)
        .max_time_ms(ADMIN_STATS_MAX_TIME_MS))

    if stale_scores:
        ids_to_delete = [score['_id'] for score in stale_scores]
        db.leaderboard.delete_many({'_id': {'$in': ids_to_delete}})

    return jsonify({
        'status': 'ok',
        'rank': rank,
        'in_top_100': rank <= 100
    })


@app.route(basedir + 'api/leaderboard/get')
@limiter.limit("120 per minute")
def route_api_leaderboard_get():
    song_hash = request.args.get('hash')
    difficulty = request.args.get('difficulty')

    if not song_hash or len(song_hash) > 500:
        return abort(400)
    if difficulty and len(difficulty) > 32:
        return abort(400)

    current_month = utc_now().strftime('%Y-%m')

    query = {
        'song_hash': song_hash,
        'month': current_month
    }
    if difficulty:
        query['difficulty'] = difficulty

    scores = list(
        db.leaderboard.find(query)
        .sort('score_value', -1)
        .limit(100)
        .max_time_ms(ADMIN_STATS_MAX_TIME_MS)
    )

    result = []
    for i, score in enumerate(scores):
        result.append({
            'rank': i + 1,
            'display_name': score.get('display_name', 'Anonymous'),
            'score_value': score.get('score_value', 0),
            'difficulty': score.get('difficulty')
        })
    
    return jsonify({
        'status': 'ok',
        'leaderboard': result,
        'month': current_month
    })


def week_start_for(now=None):
    now = now or utc_now()
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def week_key_for(now=None):
    iso = (now or utc_now()).isocalendar()
    return '{}-W{:02d}'.format(iso[0], iso[1])


def week_start_from_key(week_key):
    match = re.fullmatch(r'(\d{4})-W(\d{2})', str(week_key or ''))
    if not match:
        return None
    try:
        return datetime.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        return None


def weekly_challenge_song(challenge):
    if not challenge:
        return None
    song = db.songs.find_one({
        'id': challenge.get('song_id'),
        'enabled': True
    })
    difficulty = challenge.get('difficulty') or 'oni'
    if (
        not song or
        not song_has_course(song, difficulty) or
        not public_song_files_available(song)
    ):
        return None
    expected_hash = song.get('hash') or song.get('title') or str(song.get('id'))
    if challenge.get('song_hash') != expected_hash:
        return None
    return song


def legacy_weekly_challenges(week_key):
    week_start = week_start_from_key(week_key)
    if not week_start:
        return []
    date_from = week_start.strftime('%Y-%m-%d')
    date_to = (week_start + timedelta(days=6)).strftime('%Y-%m-%d')
    candidates = list(db.weekly_challenges.find({
        '$or': [
            {'week_key': week_key},
            {
                'week_key': {'$exists': False},
                'date_key': {'$gte': date_from, '$lte': date_to}
            }
        ]
    }))
    return [
        challenge
        for challenge in candidates
        if challenge.get('challenge_id') != week_key and weekly_challenge_song(challenge)
    ]


def legacy_weekly_challenge(week_key):
    candidates = legacy_weekly_challenges(week_key)
    if not candidates:
        return None

    def candidate_key(challenge):
        score_count = db.weekly_challenge_scores.count_documents({
            'challenge_id': challenge.get('challenge_id'),
            'song_hash': challenge.get('song_hash'),
            'difficulty': challenge.get('difficulty') or 'oni'
        })
        return (
            -score_count,
            str(challenge.get('date_key') or ''),
            str(challenge.get('_id'))
        )

    return min(candidates, key=candidate_key)


def historical_weekly_challenge(week_key):
    challenge = db.weekly_challenges.find_one({'challenge_id': week_key})
    if challenge and weekly_challenge_song(challenge):
        return challenge
    return legacy_weekly_challenge(week_key)


def current_weekly_challenge(now=None):
    now = now or utc_now()
    week_start = week_start_for(now)
    week_key = week_key_for(now)
    existing = db.weekly_challenges.find_one({'challenge_id': week_key})
    if existing:
        return existing

    candidates = [
        song
        for song in db.songs.find({'enabled': True})
        if song_has_course(song, 'oni') and public_song_files_available(song)
    ]
    candidates.sort(key=lambda song: str(song.get('id')))
    if not candidates:
        return None

    seed = hashlib.sha256(('weekly-challenge:' + week_key).encode('utf-8')).digest()
    song = candidates[int.from_bytes(seed[:8], 'big') % len(candidates)]
    doc = {
        'challenge_id': week_key,
        'date_key': week_start.strftime('%Y-%m-%d'),
        'week_key': week_key,
        'week_start': week_start,
        'week_end': week_start + timedelta(weeks=1),
        'song_id': song['id'],
        'song_hash': song.get('hash') or song.get('title') or str(song['id']),
        'difficulty': 'oni',
        'canonical': True,
        'created_at': now
    }
    try:
        return db.weekly_challenges.find_one_and_update(
            {'challenge_id': week_key},
            {'$setOnInsert': doc},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
    except DuplicateKeyError:
        return db.weekly_challenges.find_one({
            '$or': [
                {'challenge_id': week_key},
                {'week_key': week_key, 'canonical': True}
            ]
        })


def serialize_challenge(challenge):
    week_start = challenge.get('week_start') or week_start_from_key(
        challenge.get('week_key')
    )
    week_end = challenge.get('week_end')
    if not isinstance(week_end, datetime) and isinstance(week_start, datetime):
        week_end = week_start + timedelta(weeks=1)
    return {
        'challenge_id': challenge.get('challenge_id'),
        'date_key': challenge.get('date_key'),
        'week_key': challenge.get('week_key'),
        'song_id': challenge.get('song_id'),
        'song_hash': challenge.get('song_hash'),
        'difficulty': challenge.get('difficulty', 'oni'),
        'week_ends_at': week_end.isoformat() + 'Z' if isinstance(week_end, datetime) else None
    }


def challenge_score_query(challenge):
    return {
        'challenge_id': challenge.get('challenge_id'),
        'song_hash': challenge.get('song_hash'),
        'difficulty': challenge.get('difficulty') or 'oni'
    }


def challenge_board(challenge):
    scores = db.weekly_challenge_scores.find(challenge_score_query(challenge)).sort([
        ('score_value', -1),
        ('updated_at', 1)
    ]).limit(100)
    result = []
    for i, score in enumerate(scores):
        result.append({
            'rank': i + 1,
            'display_name': score.get('display_name', score.get('username', 'Anonymous')),
            'score_value': score.get('score_value', 0),
            'good': score.get('good', 0),
            'ok': score.get('ok', 0),
            'bad': score.get('bad', 0),
            'max_combo': score.get('max_combo', 0),
            'drumroll': score.get('drumroll', 0)
        })
    return result


@app.route(basedir + 'api/weekly-challenge/current')
def route_api_weekly_challenge_current():
    now = utc_now()
    challenge = current_weekly_challenge(now)
    if not challenge:
        return api_error('no_oni_songs')

    song = weekly_challenge_song(challenge)
    if not song:
        return api_error('challenge_song_missing')

    return jsonify({
        'status': 'ok',
        'challenge': serialize_challenge(challenge),
        'song': serialize_public_song(song),
        'server_now': now.isoformat() + 'Z'
    })


@app.route(basedir + 'api/weekly-challenge/leaderboards')
def route_api_weekly_challenge_leaderboards():
    now = utc_now()
    challenge = current_weekly_challenge(now)
    if not challenge:
        return api_error('no_oni_songs')

    previous_week = week_start_for(now) - timedelta(weeks=1)
    previous_challenge = historical_weekly_challenge(week_key_for(previous_week))

    def challenge_payload(item):
        if not item:
            return None
        song = weekly_challenge_song(item)
        payload = serialize_challenge(item)
        payload['song'] = serialize_public_song(song) if song else None
        payload['leaderboard'] = challenge_board(item)
        return payload

    return jsonify({
        'status': 'ok',
        'current': challenge_payload(challenge),
        'previous': challenge_payload(previous_challenge),
        'server_now': now.isoformat() + 'Z'
    })


def int_score_field(data, key):
    try:
        return max(0, int(data.get(key, 0)))
    except (TypeError, ValueError):
        return 0


@app.route(basedir + 'api/weekly-challenge/submit', methods=['POST'])
@login_required
def route_api_weekly_challenge_submit():
    data = request.get_json()
    if not schema.validate(data, schema.weekly_challenge_submit):
        return abort(400)

    challenge = current_weekly_challenge()
    if not challenge:
        return api_error('no_oni_songs')
    song = weekly_challenge_song(challenge)
    if not song:
        return api_error('challenge_song_missing')

    challenge_id = data.get('challenge_id')
    song_hash = data.get('song_hash') or data.get('hash')
    difficulty = data.get('difficulty')
    if (
        challenge_id != challenge.get('challenge_id') or
        song_hash != challenge.get('song_hash') or
        difficulty != challenge.get('difficulty')
    ):
        return api_error('challenge_not_active')

    username = session.get('username')
    user = db.users.find_one({'username': username})
    if not user:
        return api_error('not_logged_in')

    score_value = int_score_field(data, 'score')
    now = utc_now()
    score_identity = {
        'challenge_id': challenge.get('challenge_id'),
        'username': username
    }
    existing = db.weekly_challenge_scores.find_one(score_identity)
    existing_matches_challenge = bool(
        existing and
        existing.get('song_hash') == challenge.get('song_hash') and
        existing.get('difficulty') == challenge.get('difficulty')
    )
    if (
        not existing_matches_challenge or
        score_value > existing.get('score_value', 0)
    ):
        db.weekly_challenge_scores.update_one(score_identity, {
            '$set': {
                'challenge_id': challenge_id,
                'display_name': user.get('display_name') or username,
                'score_value': score_value,
                'good': int_score_field(data, 'good'),
                'ok': int_score_field(data, 'ok'),
                'bad': int_score_field(data, 'bad'),
                'max_combo': int_score_field(data, 'max_combo'),
                'drumroll': int_score_field(data, 'drumroll'),
                'song_id': challenge.get('song_id'),
                'song_hash': challenge.get('song_hash'),
                'difficulty': challenge.get('difficulty'),
                'updated_at': now
            },
            '$setOnInsert': {
                'week_key': challenge.get('week_key'),
                'week_start': challenge.get('week_start'),
            }
        }, upsert=True)

    overflow = list(db.weekly_challenge_scores.find(
        challenge_score_query(challenge)
    ).sort([
        ('score_value', -1),
        ('updated_at', 1)
    ]).skip(100))
    if overflow:
        db.weekly_challenge_scores.delete_many({'_id': {'$in': [score['_id'] for score in overflow]}})

    score_doc = db.weekly_challenge_scores.find_one(score_identity)
    rank = None
    in_top_100 = False
    if score_doc:
        rank_query = challenge_score_query(challenge)
        rank_query['score_value'] = {'$gt': score_doc.get('score_value', 0)}
        higher_count = db.weekly_challenge_scores.count_documents(rank_query)
        rank = higher_count + 1
        in_top_100 = rank <= 100

    return jsonify({
        'status': 'ok',
        'rank': rank,
        'in_top_100': in_top_100
    })


@app.route(basedir + 'privacy')
def route_api_privacy():
    privacy_path = APP_ROOT / 'templates' / 'privacy.txt'
    last_modified = time.strftime('%d %B %Y', time.gmtime(privacy_path.stat().st_mtime))
    integration = take_config('GOOGLE_CREDENTIALS')['gdrive_enabled'] if take_config('GOOGLE_CREDENTIALS') else False
    
    response = make_response(render_template('privacy.txt', last_modified=last_modified, config=get_config(), integration=integration))
    response.headers['Content-type'] = 'text/plain; charset=utf-8'
    return response


def make_preview(song_id, song_type, song_ext, preview):
    song_path = SONGS_DIR / str(song_id) / f'main.{song_ext}'
    prev_path = SONGS_DIR / str(song_id) / 'preview.mp3'

    if prev_path.is_file():
        return str(prev_path)
    if not song_path.is_file() or not preview or preview <= 0:
        return False

    temp_path = prev_path.with_name('.preview-{}.mp3'.format(uuid.uuid4().hex))
    try:
        ff = FFmpeg(
            inputs={str(song_path): '-ss %s' % preview},
            outputs={str(temp_path): '-codec:a libmp3lame -ar 32000 -b:a 92k -y -loglevel panic'}
        )
        ff.run()
        temp_path.replace(prev_path)
    except (FFRuntimeError, OSError):
        app.logger.exception('Failed to generate preview for song %s', song_id)
        return False
    finally:
        temp_path.unlink(missing_ok=True)

    return str(prev_path) if prev_path.is_file() else False

error_pages = take_config('ERROR_PAGES') or {}

def create_error_page(code, url):
    if url.startswith("http://") or url.startswith("https://"):
        try:
            resp = requests.get(url, timeout=REMOTE_REQUEST_TIMEOUT)
        except requests.RequestException:
            app.logger.warning('Unable to load remote error page for status %s', code)
            return
        if resp.status_code == 200:
            content = resp.content
            app.register_error_handler(
                code,
                lambda error, content=content, status=code: (content, status)
            )
    else:
        if url.startswith(basedir):
            url = url[len(basedir):]
        public_root = PUBLIC_DIR.resolve()
        path = (public_root / url.lstrip('/\\')).resolve()
        try:
            path.relative_to(public_root)
        except ValueError:
            app.logger.warning('Ignoring error page outside public directory: %s', url)
            return
        if path.is_file():
            app.register_error_handler(
                code,
                lambda error, path=path, status=code: (
                    send_from_directory(str(path.parent), path.name),
                    status
                )
            )

for code in error_pages:
    if error_pages[code]:
        create_error_page(code, error_pages[code])

def cache_wrap(res_from, secs):
    res = flask.make_response(res_from)
    res.headers["Cache-Control"] = f"public, max-age={secs}, s-maxage={secs}"
    res.headers["CDN-Cache-Control"] = f"max-age={secs}"
    return res

@app.route(basedir + "src/<path:ref>")
def send_src(ref):
    return cache_wrap(flask.send_from_directory(str(PUBLIC_DIR / 'src'), ref), 3600)

@app.route(basedir + "assets/<path:ref>")
def send_assets(ref):
    return cache_wrap(flask.send_from_directory(str(PUBLIC_DIR / 'assets'), ref), 3600)

@app.route(basedir + "songs/<path:ref>")
def send_songs(ref):
    parts = ref.split('/')
    if len(parts) != 2 or not is_public_song_id(parts[0]):
        return abort(404)
    song = db.songs.find_one({
        'id': route_song_id(parts[0]),
        'enabled': True
    })
    if not song or not public_song_files_available(song):
        return abort(404)

    allowed_files = {'main.{}'.format(song.get('music_type') or 'mp3')}
    if song.get('type') == 'tja':
        allowed_files.add('main.tja')
    elif song.get('type') == 'osu':
        allowed_files.update(
            '{}.osu'.format(course)
            for course in ADMIN_COURSES
            if song_has_course(song, course)
        )
    if song.get('lyrics'):
        allowed_files.add('main.vtt')
    if song.get('video') is not None:
        allowed_files.add('main.mp4')
    allowed_files.update({'preview.mp3', 'preview.ogg'})
    if parts[1] not in allowed_files:
        return abort(404)

    preview_match = re.fullmatch(r'([^/]+)/preview\.(?:mp3|ogg)', ref)
    preview_path = (SONGS_DIR / ref).resolve()
    if (
        preview_match and
        not preview_path.is_file() and
        is_public_song_id(preview_match.group(1))
    ):
        return redirect(flask.url_for('route_api_preview', id=preview_match.group(1)))
    return cache_wrap(flask.send_from_directory(str(SONGS_DIR), ref), 604800)

@app.route(basedir + "notice_uploads/<path:ref>")
def send_notice_uploads(ref):
    if not re.fullmatch(r'[a-f0-9]{32}\.(?:jpg|jpeg|png|gif|webp)', ref):
        return abort(404)
    return cache_wrap(flask.send_from_directory(str(NOTICE_UPLOADS_DIR), ref), 604800)

@app.route(basedir + "manifest.json")
def send_manifest():
    return cache_wrap(flask.send_from_directory(str(PUBLIC_DIR), "manifest.json"), 3600)


def read_limited_upload(upload, limit, error_code):
    data = upload.stream.read(limit + 1)
    if not data:
        raise UploadValidationError('empty_file')
    if len(data) > limit:
        raise UploadValidationError(error_code)
    return data


def decode_uploaded_tja(data):
    for encoding in ('utf-8-sig', 'cp932', 'shift_jis', 'euc-jp', 'iso-2022-jp'):
        try:
            return data.decode(encoding).replace('\r', '')
        except UnicodeDecodeError:
            continue
    raise UploadValidationError('invalid_tja_encoding')


def uploaded_music_type(filename):
    suffix = pathlib.Path((filename or '').replace('\\', '/')).suffix.lower().lstrip('.')
    if suffix not in UPLOAD_ALLOWED_MUSIC_TYPES:
        raise UploadValidationError('unsupported_music_type')
    return suffix


def music_signature_matches(data, music_type):
    if music_type == 'ogg':
        return data.startswith(b'OggS')
    if music_type == 'mp3':
        if data.startswith(b'ID3'):
            return True
        scan = data[:4096]
        return any(
            scan[index] == 0xff and scan[index + 1] & 0xe0 == 0xe0
            for index in range(max(0, len(scan) - 1))
        )
    return False


def validate_uploaded_tja(tja, tja_text, music_type):
    if not tja.title or len(tja.title) > 500:
        raise UploadValidationError('invalid_tja_title')
    if tja.invalid_courses:
        raise UploadValidationError('invalid_tja_course')
    if tja.invalid_numeric_fields:
        raise UploadValidationError('invalid_tja_number')
    valid_courses = [
        course
        for course in tja.courses.values()
        if isinstance(course, dict)
    ]
    if not valid_courses:
        raise UploadValidationError('missing_tja_courses')
    if any(
        safe_int_value(course.get('stars')) is None or
        not 0 <= safe_int_value(course.get('stars')) <= 10
        for course in valid_courses
    ):
        raise UploadValidationError('invalid_tja_level')

    normalized_lines = []
    for raw_line in tja_text.splitlines():
        line = raw_line.strip()
        comment_index = line.find('//')
        if comment_index >= 0 and not line.upper().startswith('MAKER:'):
            line = line[:comment_index].strip()
        if line:
            normalized_lines.append(line)

    in_chart = False
    chart_count = 0
    for line in normalized_lines:
        upper = line.upper()
        if upper in ('#START', '#START P1'):
            if in_chart:
                raise UploadValidationError('invalid_tja_start')
            in_chart = True
            chart_count += 1
        elif upper == '#END':
            if not in_chart:
                raise UploadValidationError('invalid_tja_end')
            in_chart = False
    if not chart_count:
        raise UploadValidationError('missing_tja_start')
    if in_chart:
        raise UploadValidationError('missing_tja_end')

    wave = (tja.wave or '').strip()
    if not wave or '\x00' in wave:
        raise UploadValidationError('missing_tja_wave')
    if pathlib.PurePath(wave).name != wave or '/' in wave or '\\' in wave:
        raise UploadValidationError('unsafe_tja_wave')
    wave_type = pathlib.Path(wave).suffix.lower().lstrip('.')
    if wave_type not in UPLOAD_ALLOWED_MUSIC_TYPES or wave_type != music_type:
        raise UploadValidationError('music_type_mismatch')

    numeric_headers = {'BPM', 'OFFSET', 'DEMOSTART'}
    for line in normalized_lines:
        if ':' not in line:
            continue
        name, value = (part.strip() for part in line.split(':', 1))
        if name.upper() not in numeric_headers:
            continue
        try:
            number = float(value)
        except ValueError:
            raise UploadValidationError('invalid_tja_number')
        if not math.isfinite(number):
            raise UploadValidationError('invalid_tja_number')


def song_storage_child(name):
    if not re.fullmatch(r'[A-Za-z0-9._-]+', name or ''):
        raise ValueError('invalid song storage name')
    root = SONGS_DIR.resolve()
    child = root / name
    if child.parent.resolve() != root:
        raise ValueError('song storage path escaped its root')
    return child


def remove_song_storage_entry(path):
    root = SONGS_DIR.resolve()
    path = pathlib.Path(path)
    if path.parent.resolve() != root:
        raise ValueError('refusing to remove a path outside the song storage root')
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def fsync_directory(path):
    try:
        directory_fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def write_durable_file(path, data):
    with path.open('xb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def install_uploaded_song_files(song_id, music_type, tja_data, music_data):
    if not re.fullmatch(r'[a-f0-9]{64}-[a-f0-9]{64}', song_id):
        raise ValueError('invalid uploaded song id')

    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    target = song_storage_child(song_id)
    staged = song_storage_child('.upload-{}'.format(token))
    backup = song_storage_child('.backup-{}'.format(token))
    state = {'target': target, 'backup': None, 'installed': False}

    try:
        staged.mkdir()
        write_durable_file(staged / 'main.tja', tja_data)
        write_durable_file(staged / 'main.{}'.format(music_type), music_data)
        if target.exists() or target.is_symlink():
            target.replace(backup)
            state['backup'] = backup
        staged.replace(target)
        state['installed'] = True
        fsync_directory(SONGS_DIR.resolve())
        return state
    except Exception:
        if staged.exists() or staged.is_symlink():
            remove_song_storage_entry(staged)
        if state['backup'] and (state['backup'].exists() or state['backup'].is_symlink()):
            if target.exists() or target.is_symlink():
                remove_song_storage_entry(target)
            state['backup'].replace(target)
        raise


def rollback_uploaded_song_files(state):
    target = state['target']
    backup = state.get('backup')
    if state.get('installed') and (target.exists() or target.is_symlink()):
        remove_song_storage_entry(target)
    if backup and (backup.exists() or backup.is_symlink()):
        backup.replace(target)
    fsync_directory(SONGS_DIR.resolve())


def finalize_uploaded_song_files(state):
    backup = state.get('backup')
    if backup and (backup.exists() or backup.is_symlink()):
        remove_song_storage_entry(backup)
        fsync_directory(SONGS_DIR.resolve())


def process_song_upload(allowed_song_types=None, default_song_type=None, upload_source='web_upload'):
    try:
        if 'file_tja' not in request.files or 'file_music' not in request.files:
            raise UploadValidationError('missing_files')

        file_tja = request.files['file_tja']
        file_music = request.files['file_music']
        if not file_tja.filename or not file_music.filename:
            raise UploadValidationError('empty_filename')
        if pathlib.Path(file_tja.filename.replace('\\', '/')).suffix.lower() != '.tja':
            raise UploadValidationError('unsupported_chart_type')

        raw_tja_data = read_limited_upload(
            file_tja,
            UPLOAD_TJA_MAX_BYTES,
            'tja_too_large'
        )
        music_data = read_limited_upload(
            file_music,
            UPLOAD_MUSIC_MAX_BYTES,
            'music_too_large'
        )
        music_type = uploaded_music_type(file_music.filename)
        if not music_signature_matches(music_data, music_type):
            raise UploadValidationError('invalid_music_file')

        tja_text = decode_uploaded_tja(raw_tja_data)
        if '\x00' in tja_text:
            raise UploadValidationError('invalid_tja_content')
        tja = tjaf.Tja(tja_text)
        validate_uploaded_tja(tja, tja_text, music_type)

        allowed_song_types = set(allowed_song_types or [CUSTOM_CATEGORY['title']])
        song_type = (request.form.get('song_type') or default_song_type or '').strip()
        if song_type not in allowed_song_types:
            raise UploadValidationError('invalid_song_type')

        tja_data = tja_text.encode('utf-8')
        tja_hash = hashlib.sha256(tja_data).hexdigest()
        music_hash = hashlib.sha256(music_data).hexdigest()
        generated_id = '{}-{}'.format(tja_hash, music_hash)

        db_entry = tja.to_mongo(generated_id, time.time_ns())
        db_entry.update({
            'enabled': True,
            'hash': generated_id,
            'music_type': music_type,
            'song_type': song_type,
            'uploaded_at': utc_now(),
            'upload_source': upload_source
        })

        file_state = install_uploaded_song_files(
            generated_id,
            music_type,
            tja_data,
            music_data
        )
        try:
            result = db.songs.update_one(
                {'id': generated_id},
                {'$setOnInsert': db_entry},
                upsert=True
            )
        except Exception:
            rollback_uploaded_song_files(file_state)
            raise

        try:
            finalize_uploaded_song_files(file_state)
        except Exception:
            app.logger.exception('Failed to remove an upload backup for %s', generated_id)

        created = result.upserted_id is not None
        if created:
            try:
                invalidate_song_derived_caches()
            except Exception:
                app.logger.exception('Failed to invalidate song caches after upload %s', generated_id)

        return jsonify({
            'success': True,
            'id': generated_id,
            'created': created
        }), 201 if created else 200
    except UploadValidationError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    except RequestEntityTooLarge:
        raise
    except Exception:
        app.logger.exception('Song upload failed')
        return jsonify({'success': False, 'error': 'upload_failed'}), 500


@app.route(basedir + "upload/", defaults={"ref": "index.html"})
@app.route(basedir + "upload/<path:ref>")
def send_upload(ref):
    return cache_wrap(flask.send_from_directory(str(PUBLIC_DIR / 'upload'), ref), 3600)

@app.route(basedir + "api/user-upload", methods=["POST"])
@limiter.limit("5 per hour")
def user_upload_file():
    return process_song_upload(
        allowed_song_types=[CUSTOM_CATEGORY['title']],
        default_song_type=CUSTOM_CATEGORY['title'],
        upload_source='web_upload'
    )

@app.route(basedir + "api/upload", methods=["POST"])
@limiter.limit("5 per hour")
def api_upload_file():
    if not request_uses_upload_token() and not get_current_admin(50):
        return jsonify({'success': False, 'error': 'upload_unauthorized'}), 403
    return process_song_upload(
        allowed_song_types=SONG_TYPES,
        default_song_type=CUSTOM_CATEGORY['title'],
        upload_source='api_upload'
    )

@app.route(basedir + "api/remove", methods=["POST"])
def remove():
    return flask.jsonify({ "success": False, "reason": "Remove is disabled" }), 403

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run the taiko-web development server.')
    parser.add_argument('port', type=int, metavar='PORT', nargs='?', default=34801, help='Port to listen on.')
    parser.add_argument('-b', '--bind-address', default='localhost', help='Bind server to address.')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode.')
    args = parser.parse_args()

    app.run(host=args.bind_address, port=args.port, debug=args.debug)

