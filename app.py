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
from datetime import datetime, timedelta

import pathlib
import shutil
from flask_limiter import Limiter

import flask
import tjaf

# ----

from functools import wraps
from flask import Flask, g, jsonify, render_template, request, abort, redirect, session, flash, make_response, send_from_directory
from flask_caching import Cache
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
from ffmpy import FFmpeg
from bson import ObjectId
from pymongo import MongoClient, UpdateOne
from pymongo.errors import DuplicateKeyError, PyMongoError
from redis import Redis
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


APP_ROOT = pathlib.Path(__file__).resolve().parent


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
redis_client = Redis(
    host=redis_config['CACHE_REDIS_HOST'],
    port=redis_config['CACHE_REDIS_PORT'],
    password=redis_config['CACHE_REDIS_PASSWORD'],
    db=redis_config['CACHE_REDIS_DB'],
    socket_connect_timeout=1,
    socket_timeout=1
)
try:
    redis_client.ping()
    redis_available = True
except Exception:
    redis_available = False
redis_db = redis_config['CACHE_REDIS_DB'] if redis_config['CACHE_REDIS_DB'] is not None else 0
limiter_storage_uri = os.environ.get("REDIS_URI") or (
    "redis://{}:{}/{}".format(redis_config['CACHE_REDIS_HOST'], redis_config['CACHE_REDIS_PORT'], redis_db)
    if redis_available else
    "memory://"
)

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

client = MongoClient(host=os.environ.get("TAIKO_WEB_MONGO_HOST") or take_config('MONGO', required=True)['host'])
basedir = take_config('BASEDIR') or '/'
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
if redis_available:
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis_client
    app.cache = Cache(app, config=redis_config)
else:
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = str(APP_ROOT / 'flask_session')
    app.cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})
sess = Session()
sess.init_app(app)
app.jinja_env.globals.setdefault('csrf_token', generate_csrf)
app.config['WTF_CSRF_CHECK_DEFAULT'] = False
csrf = CSRFProtect(app)

db = client[take_config('MONGO', required=True)['database']]
db.users.create_index('username', unique=True)
db.songs.create_index('id', unique=True)
db.songs.create_index('hash')
db.songs.create_index('title')
db.songs.create_index('song_type')
db.scores.create_index('username')
db.scores.create_index([('username', 1), ('hash', 1)])
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
TOP_SONGS_CACHE_SCHEMA_VERSION = 2
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


def save_site_message_image(upload):
    if not upload or not upload.filename:
        return None

    filename = secure_filename(upload.filename)
    if not filename or not is_allowed_site_message_image(filename):
        raise ValueError('Unsupported image type. Please upload jpg, png, gif, or webp.')

    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > SITE_MESSAGE_MAX_IMAGE_BYTES:
        raise ValueError('Image is too large. Please keep it under 5 MB.')

    NOTICE_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = pathlib.Path(filename).suffix.lower()
    stored_name = '{}{}'.format(uuid.uuid4().hex, suffix)
    upload.save(str(NOTICE_UPLOADS_DIR / stored_name))
    return site_path('notice_uploads/{}'.format(stored_name))


def utc_period_starts(now=None):
    now = now or datetime.utcnow()
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
    now = now or datetime.utcnow()
    return updated_at <= now - timedelta(days=TOP_SONGS_CACHE_DAYS)


def get_top_songs_cache_doc():
    return db.top_song_cache.find_one({'_id': TOP_SONGS_CACHE_KEY}) or {}


def acquire_top_songs_refresh_lock():
    now = datetime.utcnow()
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
    now = now or datetime.utcnow()
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
            'updated_at': datetime.utcnow()
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
    return db.songs.find_one({
        'enabled': True,
        '$or': [
            {'hash': song_hash},
            {'id': {'$in': song_ids}},
            {'title': song_hash}
        ]
    }, {'_id': True})


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
            'song_type': True
        }
    ))
    identity_maps = build_song_identity_maps(songs)

    rows = []
    for item in count_docs:
        song_hash = item.get('song_hash')
        song = resolve_song_identity(song_hash, identity_maps)
        if not song:
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
                    now = datetime.utcnow()
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
        now = datetime.utcnow()
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
        now = datetime.utcnow()
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
        pass


def get_public_songs_cache_version():
    return app.cache.get(PUBLIC_SONGS_CACHE_VERSION_KEY) or PUBLIC_SONGS_CACHE_BOOT_VERSION


def invalidate_public_songs_cache():
    app.cache.set(PUBLIC_SONGS_CACHE_VERSION_KEY, str(time.time_ns()), timeout=0)


def mark_top_songs_cache_stale():
    cache_doc = get_top_songs_cache_doc()
    if not cache_doc:
        return
    stale_at = datetime.utcnow() - timedelta(days=TOP_SONGS_CACHE_DAYS + 1)
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
    return {
        'song_count': db.songs.count_documents({}),
        'enabled_song_count': db.songs.count_documents({'enabled': True}),
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
    return datetime.utcnow() - timedelta(days=BOARD_RETENTION_DAYS)


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
        urls = ['%s%s/main.tja' % (take_config('SONGS_BASEURL', required=True), id)]
    else:
        urls = []
        for diff in ['easy', 'normal', 'hard', 'oni', 'ura']:
            if form.get('course_' + diff):
                urls.append('%s%s/%s.osu' % (take_config('SONGS_BASEURL', required=True), id, diff))

    for url in urls:
        if url.startswith("http://") or url.startswith("https://"):
            try:
                resp = requests.get(url, timeout=REMOTE_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                raise HashException('Unable to load chart data') from exc
            if resp.status_code != 200:
                raise HashException('Invalid response from %s (status code %s)' % (resp.url, resp.status_code))
            md5.update(resp.content)
        else:
            if url.startswith(basedir):
                url = url[len(basedir):]
            path = os.path.normpath(os.path.join("public", url))
            if not os.path.isfile(path):
                raise HashException("File not found: %s" % (os.path.abspath(path)))
            with open(path, "rb") as file:
                md5.update(file.read())

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
    if request.path.endswith('/api/upload'):
        return jsonify({'success': False, 'error': 'upload_too_large'}), 413
    return e


@app.errorhandler(429)
def handle_rate_limit(e):
    if '/api/' in request.path:
        return jsonify({'success': False, 'error': 'rate_limited'}), 429
    return e


@app.before_request
def before_request_func():
    endpoint = request.endpoint or ''
    if (
        request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and
        (endpoint == 'route_secret_admin_login' or endpoint.startswith('route_admin_'))
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
    config_out = {
        'basedir': basedir,
        'songs_baseurl': take_config('SONGS_BASEURL', required=True),
        'assets_baseurl': take_config('ASSETS_BASEURL', required=True),
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
    relative_urls = ['songs_baseurl', 'assets_baseurl']
    for name in relative_urls:
        if not config_out[name].startswith("/") and not config_out[name].startswith("http://") and not config_out[name].startswith("https://"):
            config_out[name] = basedir + config_out[name]
    if credentials:
        google_credentials = take_config('GOOGLE_CREDENTIALS') or {}
        min_level = google_credentials.get('min_level') or 0
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

    if not config_out.get('songs_baseurl'):
        config_out['songs_baseurl'] = ''.join([request.host_url, 'songs']) + '/'
    if not config_out.get('assets_baseurl'):
        config_out['assets_baseurl'] = ''.join([request.host_url, 'assets']) + '/'

    config_out['_version'] = get_version()
    return config_out

def get_version():
    version = {'commit': None, 'commit_short': '', 'version': None, 'url': take_config('URL')}
    if os.path.isfile('version.json'):
        try:
            ver = json.load(open('version.json', 'r'))
        except ValueError:
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
    return request.url_root.rstrip('/') + path


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
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_lang_map(value):
    return value if isinstance(value, dict) else {}


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


def next_sequence_value(name):
    seq = db.seq.find_one({'name': name})
    if not seq:
        return 1
    return safe_int_value(seq.get('value'), 0) + 1


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
        'created_at': datetime.utcnow(),
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
        'entered_at': datetime.utcnow()
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
            'read_at': datetime.utcnow()
        }
    }, upsert=True)

    return jsonify({'status': 'ok'})


def get_current_admin(min_level=50):
    username = session.get('username')
    if not username:
        return None
    user = db.users.find_one({'username': username})
    if user and user.get('user_level', 0) >= min_level:
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
        user = db.users.find_one({'username_lower': username.lower()})
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

    db.site_messages.insert_one({
        'title': title,
        'body': body,
        'image_url': image_url,
        'active': bool(request.form.get('active')),
        'created_at': datetime.utcnow(),
        'created_by': session.get('username')
    })
    flash('Message published.')
    return redirect(basedir + 'admin/messages')


@app.route(basedir + 'admin/messages/<message_id>/remove', methods=['POST'])
@admin_required(level=50)
def route_admin_messages_remove(message_id):
    object_id = object_id_or_404(message_id)
    db.site_messages.delete_one({'_id': object_id})
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
    output = {'title_lang': {}, 'subtitle_lang': {}, 'courses': {}}
    output['enabled'] = True if request.form.get('enabled') else False
    output['title'] = request.form.get('title') or None
    output['subtitle'] = request.form.get('subtitle') or None
    for lang in ['ja', 'en', 'cn', 'tw', 'ko']:
        output['title_lang'][lang] = request.form.get('title_%s' % lang) or None
        output['subtitle_lang'][lang] = request.form.get('subtitle_%s' % lang) or None

    for course in ADMIN_COURSES:
        stars = form_int('course_%s' % course)
        if stars is not None:
            output['courses'][course] = {'stars': stars,
                                         'branch': True if request.form.get('branch_%s' % course) else False}
        else:
            output['courses'][course] = None
    
    output['category_id'] = form_int('category_id') or None
    output['type'] = request.form.get('type')
    output['music_type'] = request.form.get('music_type')
    output['offset'] = form_float('offset', 0)
    output['skin_id'] = form_int('skin_id') or None
    output['preview'] = form_float('preview', 0)
    output['volume'] = form_float('volume', 1.0)
    output['maker_id'] = form_int('maker_id') or None
    output['lyrics'] = True if request.form.get('lyrics') else False
    output['hash'] = request.form.get('hash')
    
    seq_new = next_sequence_value('songs')
    
    hash_error = False
    if request.form.get('gen_hash'):
        try:
            output['hash'] = generate_hash(seq_new, request.form)
        except HashException as e:
            hash_error = True
            flash('An error occurred: %s' % str(e), 'error')
    
    output['id'] = seq_new
    output['order'] = seq_new
    
    db.songs.insert_one(output)
    if not hash_error:
        flash('Song created.')
    
    db.seq.update_one({'name': 'songs'}, {'$set': {'value': seq_new}}, upsert=True)
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

    output = {'title_lang': {}, 'subtitle_lang': {}, 'courses': {}}
    if user_level >= 100:
        output['enabled'] = True if request.form.get('enabled') else False

    output['title'] = request.form.get('title') or None
    output['subtitle'] = request.form.get('subtitle') or None
    for lang in ['ja', 'en', 'cn', 'tw', 'ko']:
        output['title_lang'][lang] = request.form.get('title_%s' % lang) or None
        output['subtitle_lang'][lang] = request.form.get('subtitle_%s' % lang) or None

    for course in ADMIN_COURSES:
        stars = form_int('course_%s' % course)
        if stars is not None:
            output['courses'][course] = {'stars': stars,
                                         'branch': True if request.form.get('branch_%s' % course) else False}
        else:
            output['courses'][course] = None
    
    output['category_id'] = form_int('category_id') or None
    output['type'] = request.form.get('type')
    output['music_type'] = request.form.get('music_type')
    output['offset'] = form_float('offset', 0)
    output['skin_id'] = form_int('skin_id') or None
    output['preview'] = form_float('preview', 0)
    output['volume'] = form_float('volume', 1.0)
    output['maker_id'] = form_int('maker_id') or None
    output['lyrics'] = True if request.form.get('lyrics') else False
    output['hash'] = request.form.get('hash')
    
    hash_error = False
    if request.form.get('gen_hash'):
        try:
            output['hash'] = generate_hash(song_id, request.form)
        except HashException as e:
            hash_error = True
            flash('An error occurred: %s' % str(e), 'error')
    
    db.songs.update_one({'id': song_id}, {'$set': output})
    if not hash_error:
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
    
    user = db.users.find_one({'username_lower': username.lower()}) if username else None
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
    categories = list(db.categories.find({}, {'_id': False}))
    makers = list(db.makers.find({}, {'_id': False}))
    song_skins = list(db.song_skins.find({}, {'_id': False}))

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

    categories_by_id = build_id_map(categories)
    makers_by_id = build_id_map(makers)
    song_skins_by_id = build_id_map(song_skins)

    songs = []
    for raw_song in raw_songs:
        song = normalize_public_song(raw_song)
        if not song:
            continue
        maker_id = song.get('maker_id')
        if maker_id is not None:
            if maker_id == 0:
                song['maker'] = 0
            else:
                song['maker'] = makers_by_id.get(maker_id) or makers_by_id.get(safe_int_value(maker_id)) or makers_by_id.get(str(maker_id))
        else:
            song['maker'] = None
        song.pop('maker_id', None)

        category_id = song.get('category_id')
        if category_id:
            category = categories_by_id.get(category_id) or categories_by_id.get(safe_int_value(category_id)) or categories_by_id.get(str(category_id))
            song['category'] = category.get('title') if category else None
        else:
            song['category'] = None
        #del song['category_id']

        skin_id = song.get('skin_id')
        if skin_id:
            song_skin = song_skins_by_id.get(skin_id) or song_skins_by_id.get(safe_int_value(skin_id)) or song_skins_by_id.get(str(skin_id))
            song['song_skin'] = {
                key: value
                for key, value in song_skin.items()
                if key != 'id'
            } if song_skin else None
        else:
            song['song_skin'] = None
        song.pop('skin_id', None)

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
@app.cache.cached(timeout=15)
def route_api_config():
    config = get_config(credentials=True)
    return jsonify(config)


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

    if db.users.find_one({'username_lower': username.lower()}):
        return api_error('username_in_use')

    password = data.get('password', '').encode('utf-8')
    if not 6 <= len(password) <= 5000:
        return api_error('invalid_password')

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password, salt)
    don = get_default_don()
    
    session_id = os.urandom(24).hex()
    db.users.insert_one({
        'username': username,
        'username_lower': username.lower(),
        'password': hashed,
        'display_name': username,
        'don': don,
        'user_level': 1,
        'session_id': session_id
    })

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
    result = db.users.find_one({'username_lower': username.lower()})
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
    if not 6 <= len(new_password) <= 5000:
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

    db.scores.delete_many({'username': session.get('username')})
    db.users.delete_one({'username': session.get('username')})

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
    if data.get('is_import'):
        db.scores.delete_many({'username': username})

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
    if operations:
        db.scores.bulk_write(operations, ordered=False)

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
    played_at = datetime.utcnow()
    song_hash = data.get('hash')
    if not find_enabled_song_by_identity(song_hash):
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

    today = datetime.utcnow()
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
    if not find_enabled_song_by_identity(song_hash):
        return abort(400)

    if not display_name or not display_name.strip():
        display_name = 'Anonymous'

    current_month = datetime.utcnow().strftime('%Y-%m')
    db.leaderboard.insert_one({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'display_name': display_name.strip()[:20],
        'score_value': score_value,
        'month': current_month,
        'created_at': datetime.utcnow()
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

    current_month = datetime.utcnow().strftime('%Y-%m')

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


@app.route(basedir + 'privacy')
def route_api_privacy():
    last_modified = time.strftime('%d %B %Y', time.gmtime(os.path.getmtime('templates/privacy.txt')))
    integration = take_config('GOOGLE_CREDENTIALS')['gdrive_enabled'] if take_config('GOOGLE_CREDENTIALS') else False
    
    response = make_response(render_template('privacy.txt', last_modified=last_modified, config=get_config(), integration=integration))
    response.headers['Content-type'] = 'text/plain; charset=utf-8'
    return response


def make_preview(song_id, song_type, song_ext, preview):
    song_path = SONGS_DIR / str(song_id) / f'main.{song_ext}'
    prev_path = SONGS_DIR / str(song_id) / 'preview.mp3'

    if song_path.is_file() and not prev_path.is_file():
        if not preview or preview <= 0:
            print('Skipping #%s due to no preview' % song_id)
            return False

        print('Making preview.mp3 for song #%s' % song_id)
        ff = FFmpeg(inputs={str(song_path): '-ss %s' % preview},
                    outputs={str(prev_path): '-codec:a libmp3lame -ar 32000 -b:a 92k -y -loglevel panic'})
        ff.run()

    return str(prev_path)

error_pages = take_config('ERROR_PAGES') or {}

def create_error_page(code, url):
    if url.startswith("http://") or url.startswith("https://"):
        try:
            resp = requests.get(url, timeout=REMOTE_REQUEST_TIMEOUT)
        except requests.RequestException:
            app.logger.warning('Unable to load remote error page for status %s', code)
            return
        if resp.status_code == 200:
            app.register_error_handler(code, lambda e: (resp.content, code))
    else:
        if url.startswith(basedir):
            url = url[len(basedir):]
        path = os.path.normpath(os.path.join("public", url))
        if os.path.isfile(path):
            app.register_error_handler(code, lambda e: (send_from_directory(".", path), code))

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
    return cache_wrap(flask.send_from_directory("public/src", ref), 3600)

@app.route(basedir + "assets/<path:ref>")
def send_assets(ref):
    return cache_wrap(flask.send_from_directory("public/assets", ref), 3600)

@app.route(basedir + "songs/<path:ref>")
def send_songs(ref):
    return cache_wrap(flask.send_from_directory(str(SONGS_DIR), ref), 604800)

@app.route(basedir + "notice_uploads/<path:ref>")
def send_notice_uploads(ref):
    return cache_wrap(flask.send_from_directory(str(NOTICE_UPLOADS_DIR), ref), 604800)

@app.route(basedir + "manifest.json")
def send_manifest():
    return cache_wrap(flask.send_from_directory("public", "manifest.json"), 3600)


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
    if not any(tja.courses.values()):
        raise UploadValidationError('missing_tja_courses')

    normalized_lines = [line.strip().upper() for line in tja_text.splitlines()]
    if not any(line.startswith('#START') for line in normalized_lines):
        raise UploadValidationError('missing_tja_start')
    if not any(line.startswith('#END') for line in normalized_lines):
        raise UploadValidationError('missing_tja_end')

    wave_type = pathlib.Path((tja.wave or '').replace('\\', '/')).suffix.lower().lstrip('.')
    if wave_type and wave_type != music_type:
        raise UploadValidationError('music_type_mismatch')


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


def process_song_upload():
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

        song_type = request.form.get('song_type')
        if song_type != CUSTOM_CATEGORY['title']:
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
            'uploaded_at': datetime.utcnow(),
            'upload_source': 'web_upload'
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


@app.route("/upload/", defaults={"ref": "index.html"})
@app.route("/upload/<path:ref>")
def send_upload(ref):
    return cache_wrap(flask.send_from_directory("public/upload", ref), 3600)

@app.route("/api/upload", methods=["POST"])
@limiter.limit("5 per hour")
def upload_file():
    return process_song_upload()

@app.route("/api/remove", methods=["POST"])
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

