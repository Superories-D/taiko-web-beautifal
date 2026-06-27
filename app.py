#!/usr/bin/env python3

import base64
import bcrypt
import hashlib
try:
    import config
except ModuleNotFoundError:
    raise FileNotFoundError('No such file or directory: \'config.py\'. Copy the example config file config.example.py to config.py')
import json
import re
import requests
import schema
import os
import time
import uuid
from datetime import datetime, timedelta

# -- カスタム --
import traceback
import pprint
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
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from redis import Redis
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

app = Flask(__name__)
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

def get_remote_address() -> str:
    return flask.request.headers.get("CF-Connecting-IP") or flask.request.headers.get("X-Forwarded-For") or flask.request.remote_addr or "127.0.0.1"

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

app.secret_key = take_config('SECRET_KEY') or 'change-me'
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
#csrf = CSRFProtect(app)

db = client[take_config('MONGO', required=True)['database']]
db.users.create_index('username', unique=True)
db.songs.create_index('id', unique=True)
db.songs.create_index('song_type')
db.scores.create_index('username')
db.play_records.create_index('song_hash')
db.play_records.create_index('played_at')
db.play_records.create_index([('song_hash', 1), ('played_at', -1)])
db.leaderboard.create_index([('song_hash', 1), ('difficulty', 1), ('score_value', -1)])
db.leaderboard.create_index('username')
db.site_messages.create_index([('active', 1), ('created_at', -1)])
db.site_message_reads.create_index([('username', 1), ('message_id', 1)], unique=True)
db.site_message_reads.create_index('message_id')

VISIT_RETENTION_DAYS = 400
VISIT_RETENTION_SECONDS = VISIT_RETENTION_DAYS * 24 * 60 * 60
VISIT_ENTERED_AT_INDEX = 'entered_at_1'
PUBLIC_TOP_SONGS_CACHE_SECONDS = 30


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


def song_period_counts(song_hash, periods):
    counts = {}
    for name, start in periods.items():
        counts[name] = db.play_records.count_documents({
            'song_hash': song_hash,
            'played_at': {'$gte': start}
        })
    return counts


def total_period_counts(collection, datetime_field, periods):
    counts = {}
    for name, start in periods.items():
        counts[name] = collection.count_documents({
            datetime_field: {'$gte': start}
        })
    return counts


def unique_visit_counts(periods):
    counts = {}
    for name, start in periods.items():
        counts[name] = len(db.visit_records.distinct('visitor_key', {
            'entered_at': {'$gte': start}
        }))
    return counts


def get_song_heat_rows(limit=30):
    limit = max(1, min(int(limit), 100))
    periods = utc_period_starts()
    songs = list(db.songs.find({}))
    songs_by_hash = {song.get('hash'): song for song in songs if song.get('hash')}
    songs_by_id = {str(song.get('id')): song for song in songs if song.get('id') is not None}
    rows = []

    grouped = db.play_records.aggregate([
        {'$group': {'_id': '$song_hash', 'play_count': {'$sum': 1}}},
        {'$sort': {'play_count': -1}},
        {'$limit': limit}
    ])
    for item in grouped:
        song_hash = item.get('_id')
        song = songs_by_hash.get(song_hash) or songs_by_id.get(str(song_hash))
        rows.append({
            'song': song,
            'song_id': song.get('id') if song else None,
            'song_hash': song_hash,
            'title': song_display_title(song),
            'total': item.get('play_count', 0),
            'periods': song_period_counts(song_hash, periods)
        })

    return rows


def get_public_top_songs(limit=10):
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10

    songs = list(db.songs.find(
        {'enabled': True},
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
    songs_by_hash = {song.get('hash'): song for song in songs if song.get('hash')}
    songs_by_id = {str(song.get('id')): song for song in songs if song.get('id') is not None}

    rows = []
    grouped = db.play_records.aggregate([
        {'$match': {'song_hash': {'$nin': [None, '']}}},
        {'$group': {
            '_id': '$song_hash',
            'play_count': {'$sum': 1},
            'last_played_at': {'$max': '$played_at'}
        }},
        {'$sort': {'play_count': -1, 'last_played_at': -1}},
        {'$limit': limit * 5}
    ])

    for item in grouped:
        song_hash = item.get('_id')
        song = songs_by_hash.get(song_hash) or songs_by_id.get(str(song_hash))
        if not song:
            continue

        rows.append({
            'rank': len(rows) + 1,
            'song_id': song.get('id'),
            'song_hash': song.get('hash') or song_hash,
            'title': song.get('title') or '',
            'title_lang': song.get('title_lang') or {},
            'subtitle': song.get('subtitle') or '',
            'subtitle_lang': song.get('subtitle_lang') or {},
            'category_id': song.get('category_id'),
            'song_type': song.get('song_type') or '',
            'play_count': item.get('play_count', 0)
        })
        if len(rows) >= limit:
            break

    return rows


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
        'heat_rows': get_song_heat_rows(20),
        'retention_days': VISIT_RETENTION_DAYS
    }


def get_admin_song_stats(song):
    periods = utc_period_starts()
    song_hash = song.get('hash') or str(song.get('id'))
    return {
        'song_hash': song_hash,
        'total': db.play_records.count_documents({'song_hash': song_hash}),
        'periods': song_period_counts(song_hash, periods),
        'recent_records': list(db.play_records.find(
            {'song_hash': song_hash}
        ).sort('played_at', -1).limit(25))
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
    md5 = hashlib.md5()
    if form['type'] == 'tja':
        urls = ['%s%s/main.tja' % (take_config('SONGS_BASEURL', required=True), id)]
    else:
        urls = []
        for diff in ['easy', 'normal', 'hard', 'oni', 'ura']:
            if form['course_' + diff]:
                urls.append('%s%s/%s.osu' % (take_config('SONGS_BASEURL', required=True), id, diff))

    for url in urls:
        if url.startswith("http://") or url.startswith("https://"):
            resp = requests.get(url)
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
            if not session.get('username'):
                return abort(403)
            
            user = db.users.find_one({'username': session.get('username')})
            if not user or user.get('user_level', 0) < level:
                return abort(403)

            return f(*args, **kwargs)
        return wrapper
    return decorated_function


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    return api_error('invalid_csrf')


@app.before_request
def before_request_func():
    if session.get('session_id'):
        if not db.users.find_one({'session_id': session.get('session_id')}):
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
        'multiplayer_url': take_config('MULTIPLAYER_URL')
    }
    relative_urls = ['songs_baseurl', 'assets_baseurl']
    for name in relative_urls:
        if not config_out[name].startswith("/") and not config_out[name].startswith("http://") and not config_out[name].startswith("https://"):
            config_out[name] = basedir + config_out[name]
    if credentials:
        google_credentials = take_config('GOOGLE_CREDENTIALS')
        min_level = google_credentials['min_level'] or 0
        if not session.get('username'):
            user_level = 0
        else:
            user = db.users.find_one({'username': session.get('username')})
            user_level = user['user_level']
        if user_level >= min_level:
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


def get_db_don(user):
    don_body_fill = user['don_body_fill'] if 'don_body_fill' in user else get_default_don('body_fill')
    don_face_fill = user['don_face_fill'] if 'don_face_fill' in user else get_default_don('face_fill')
    return {'body_fill': don_body_fill, 'face_fill': don_face_fill}

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
        'user_display_name': user.get('display_name') if user else None,
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
def route_secret_admin_login():
    if request.method == 'GET' and get_current_admin(50):
        return redirect(basedir + 'admin/overview')

    username = ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').encode('utf-8')
        user = db.users.find_one({'username_lower': username.lower()})
        try:
            password_ok = bool(user) and bcrypt.checkpw(password, user.get('password', b''))
        except (TypeError, ValueError):
            password_ok = False
        if (
            user and
            user.get('user_level', 0) >= 50 and
            password_ok
        ):
            session_id = user.get('session_id') or os.urandom(24).hex()
            if not user.get('session_id'):
                db.users.update_one({'_id': user['_id']}, {'$set': {'session_id': session_id}})
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
    songs = sorted(list(db.songs.find({})), key=lambda x: x['id'])
    categories = db.categories.find({})
    user = db.users.find_one({'username': session['username']})
    return render_template('admin_songs.html', songs=songs, admin=user, categories=list(categories), config=get_config())


@app.route(basedir + 'admin/songs/<int:id>')
@admin_required(level=50)
def route_admin_songs_id(id):
    song = db.songs.find_one({'id': id})
    if not song:
        return abort(404)

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
    seq = db.seq.find_one({'name': 'songs'})
    seq_new = seq['value'] + 1 if seq else 1

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

    for course in ['easy', 'normal', 'hard', 'oni', 'ura']:
        if request.form.get('course_%s' % course):
            output['courses'][course] = {'stars': int(request.form.get('course_%s' % course)),
                                         'branch': True if request.form.get('branch_%s' % course) else False}
        else:
            output['courses'][course] = None
    
    output['category_id'] = int(request.form.get('category_id')) or None
    output['type'] = request.form.get('type')
    output['music_type'] = request.form.get('music_type')
    output['offset'] = float(request.form.get('offset')) or None
    output['skin_id'] = int(request.form.get('skin_id')) or None
    output['preview'] = float(request.form.get('preview')) or None
    output['volume'] = float(request.form.get('volume')) or None
    output['maker_id'] = int(request.form.get('maker_id')) or None
    output['lyrics'] = True if request.form.get('lyrics') else False
    output['hash'] = request.form.get('hash')
    
    seq = db.seq.find_one({'name': 'songs'})
    seq_new = seq['value'] + 1 if seq else 1
    
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
    
    return redirect(basedir + 'admin/songs/%s' % str(seq_new))


@app.route(basedir + 'admin/songs/<int:id>', methods=['POST'])
@admin_required(level=50)
def route_admin_songs_id_post(id):
    song = db.songs.find_one({'id': id})
    if not song:
        return abort(404)

    user = db.users.find_one({'username': session['username']})
    user_level = user['user_level']

    output = {'title_lang': {}, 'subtitle_lang': {}, 'courses': {}}
    if user_level >= 100:
        output['enabled'] = True if request.form.get('enabled') else False

    output['title'] = request.form.get('title') or None
    output['subtitle'] = request.form.get('subtitle') or None
    for lang in ['ja', 'en', 'cn', 'tw', 'ko']:
        output['title_lang'][lang] = request.form.get('title_%s' % lang) or None
        output['subtitle_lang'][lang] = request.form.get('subtitle_%s' % lang) or None

    for course in ['easy', 'normal', 'hard', 'oni', 'ura']:
        if request.form.get('course_%s' % course):
            output['courses'][course] = {'stars': int(request.form.get('course_%s' % course)),
                                         'branch': True if request.form.get('branch_%s' % course) else False}
        else:
            output['courses'][course] = None
    
    output['category_id'] = int(request.form.get('category_id')) or None
    output['type'] = request.form.get('type')
    output['music_type'] = request.form.get('music_type')
    output['offset'] = float(request.form.get('offset')) or None
    output['skin_id'] = int(request.form.get('skin_id')) or None
    output['preview'] = float(request.form.get('preview')) or None
    output['volume'] = float(request.form.get('volume')) or None
    output['maker_id'] = int(request.form.get('maker_id')) or None
    output['lyrics'] = True if request.form.get('lyrics') else False
    output['hash'] = request.form.get('hash')
    
    hash_error = False
    if request.form.get('gen_hash'):
        try:
            output['hash'] = generate_hash(id, request.form)
        except HashException as e:
            hash_error = True
            flash('An error occurred: %s' % str(e), 'error')
    
    db.songs.update_one({'id': id}, {'$set': output})
    if not hash_error:
        flash('Changes saved.')
    
    return redirect(basedir + 'admin/songs/%s' % id)


@app.route(basedir + 'admin/songs/<int:id>/remove', methods=['POST'])
@limiter.limit("1 per day")
@admin_required(level=100)
def route_admin_songs_id_remove(id):
    song = db.songs.find_one({'id': id})
    if not song:
        return abort(404)

    db.songs.delete_one({'id': id})
    try:
        app.cache.delete_memoized(route_api_songs)
    except Exception:
        pass
    flash('Song removed.')
    return redirect(basedir + 'admin/songs')


@app.route(basedir + 'admin/users')
@admin_required(level=50)
def route_admin_users():
    user = db.users.find_one({'username': session.get('username')})
    max_level = user['user_level'] - 1
    return render_template('admin_users.html', config=get_config(), max_level=max_level, username='', level='')


@app.route(basedir + 'admin/users', methods=['POST'])
@admin_required(level=50)
def route_admin_users_post():
    admin_name = session.get('username')
    admin = db.users.find_one({'username': admin_name})
    max_level = admin['user_level'] - 1
    
    username = request.form.get('username')
    try:
        level = int(request.form.get('level')) or 0
    except ValueError:
        level = 0
    
    user = db.users.find_one({'username_lower': username.lower()})
    if not user:
        flash('Error: User was not found.')
    elif admin['username'] == user['username']:
        flash('Error: You cannot modify your own level.')
    else:
        user_level = user['user_level']
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
    if not song_id or not re.match('^[0-9]{1,9}$', song_id):
        abort(400)

    song_id = int(song_id)
    song = db.songs.find_one({'id': song_id})
    if not song:
        abort(400)

    song_type = song['type']
    song_ext = song['music_type'] if song['music_type'] else "mp3"
    prev_path = make_preview(song_id, song_type, song_ext, song['preview'])
    if not prev_path:
        return redirect(get_config()['songs_baseurl'] + '%s/main.%s' % (song_id, song_ext))

    return redirect(get_config()['songs_baseurl'] + '%s/preview.mp3' % song_id)


@app.route(basedir + 'api/songs')
@app.cache.cached(timeout=15, query_string=True)
def route_api_songs():
    type_q = flask.request.args.get('type')
    query = {'enabled': True}
    if type_q:
        if type_q not in SONG_TYPES:
            return abort(400)
        query['song_type'] = type_q
    songs = list(db.songs.find(query, {'_id': False, 'enabled': False}))
    for song in songs:
        if song['maker_id']:
            if song['maker_id'] == 0:
                song['maker'] = 0
            else:
                song['maker'] = db.makers.find_one({'id': song['maker_id']}, {'_id': False})
        else:
            song['maker'] = None
        del song['maker_id']

        if song['category_id']:
            category = db.categories.find_one({'id': song['category_id']})
            song['category'] = category['title'] if category else None
        else:
            song['category'] = None
        #del song['category_id']

        if song['skin_id']:
            song['song_skin'] = db.song_skins.find_one({'id': song['skin_id']}, {'_id': False, 'id': False})
        else:
            song['song_skin'] = None
        del song['skin_id']

    return cache_wrap(flask.jsonify(songs), 60)


@app.route(basedir + 'api/songs/top10')
@app.cache.cached(timeout=PUBLIC_TOP_SONGS_CACHE_SECONDS, query_string=True)
def route_api_songs_top10():
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
    if not bcrypt.checkpw(password, result['password']):
        return api_error('invalid_username_password')
    
    don = get_db_don(result)
    
    session['session_id'] = result['session_id']
    session['username'] = result['username']
    session.permanent = True if data.get('remember') else False

    return jsonify({'status': 'ok', 'username': result['username'], 'display_name': result['display_name'], 'don': don})


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
@login_required
def route_api_account_password():
    data = request.get_json()
    if not schema.validate(data, schema.update_password):
        return abort(400)

    user = db.users.find_one({'username': session.get('username')})
    current_password = data.get('current_password', '').encode('utf-8')
    if not bcrypt.checkpw(current_password, user['password']):
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
    password = data.get('password', '').encode('utf-8')
    if not bcrypt.checkpw(password, user['password']):
        return api_error('verify_password_invalid')

    db.scores.delete_many({'username': session.get('username')})
    db.users.delete_one({'username': session.get('username')})

    session.clear()
    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/scores/save', methods=['POST'])
@login_required
def route_api_scores_save():
    data = request.get_json()
    if not schema.validate(data, schema.scores_save):
        return abort(400)

    username = session.get('username')
    if data.get('is_import'):
        db.scores.delete_many({'username': username})

    scores = data.get('scores', [])
    for score in scores:
        db.scores.update_one({'username': username, 'hash': score['hash']},
        {'$set': {
            'username': username,
            'hash': score['hash'],
            'score': score['score']
        }}, upsert=True)

    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/scores/get')
@login_required
def route_api_scores_get():
    username = session.get('username')

    scores = []
    for score in db.scores.find({'username': username}):
        scores.append({
            'hash': score['hash'],
            'score': score['score']
        })

    user = db.users.find_one({'username': username})
    don = get_db_don(user)
    return jsonify({'status': 'ok', 'scores': scores, 'username': user['username'], 'display_name': user['display_name'], 'don': don})


@app.route(basedir + 'api/playcount/record', methods=['POST'])
def route_api_playcount_record():
    data = request.get_json()
    if not schema.validate(data, schema.playcount_record):
        return abort(400)

    username = session.get('username') if session.get('username') else None
    
    db.play_records.insert_one({
        'song_hash': data.get('hash'),
        'difficulty': data.get('difficulty'),
        'username': username,
        'score': data.get('score'),
        'is_auto': data.get('is_auto'),
        'played_at': datetime.utcnow()
    })

    return jsonify({'status': 'ok'})


@app.route(basedir + 'api/playcount/get')
def route_api_playcount_get():
    song_hash = request.args.get('hash', None)
    if not song_hash:
        return abort(400)

    # Get total play count for this song
    play_count = db.play_records.count_documents({'song_hash': song_hash})

    # Get weekly high score (non-auto mode only)
    # Calculate the start of current week (Monday 00:00:00 UTC)
    today = datetime.utcnow()
    start_of_week = today - timedelta(days=today.weekday(), hours=today.hour, minutes=today.minute, seconds=today.second, microseconds=today.microsecond)
    
    weekly_records = list(db.play_records.find({
        'song_hash': song_hash,
        'is_auto': False,
        'played_at': {'$gte': start_of_week}
    }).sort('score', -1).limit(1))

    weekly_high_score = weekly_records[0]['score'] if weekly_records else None

    return jsonify({
        'status': 'ok',
        'play_count': play_count,
        'weekly_high_score': weekly_high_score
    })


@app.route(basedir + 'api/leaderboard/submit', methods=['POST'])
def route_api_leaderboard_submit():
    data = request.get_json()
    if not data:
        return abort(400)
    
    song_hash = data.get('hash')
    difficulty = data.get('difficulty')
    score_value = data.get('score', 0)
    display_name = data.get('display_name', 'Anonymous')
    
    if not song_hash or not difficulty:
        return abort(400)
    
    if not display_name or not display_name.strip():
        display_name = 'Anonymous'
    
    # Get current month for monthly reset
    current_month = datetime.utcnow().strftime('%Y-%m')
    
    # Insert new score (allow duplicate names)
    result = db.leaderboard.insert_one({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'display_name': display_name.strip()[:20],  # Limit name length
        'score_value': score_value,
        'month': current_month,
        'created_at': datetime.utcnow()
    })
    
    # Calculate rank
    higher_count = db.leaderboard.count_documents({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'month': current_month,
        'score_value': {'$gt': score_value}
    })
    rank = higher_count + 1
    
    # Keep only top 100 per song/difficulty/month
    all_scores = list(db.leaderboard.find({
        'song_hash': song_hash,
        'difficulty': difficulty,
        'month': current_month
    }).sort('score_value', -1).skip(100))
    
    if all_scores:
        ids_to_delete = [s['_id'] for s in all_scores]
        db.leaderboard.delete_many({'_id': {'$in': ids_to_delete}})
    
    return jsonify({
        'status': 'ok',
        'rank': rank,
        'in_top_100': rank <= 100
    })


@app.route(basedir + 'api/leaderboard/get')
def route_api_leaderboard_get():
    song_hash = request.args.get('hash')
    difficulty = request.args.get('difficulty')
    
    if not song_hash:
        return abort(400)
    
    # Get current month for monthly leaderboard
    current_month = datetime.utcnow().strftime('%Y-%m')
    
    query = {
        'song_hash': song_hash,
        'month': current_month
    }
    if difficulty:
        query['difficulty'] = difficulty
    
    # Get top 100 scores
    scores = list(db.leaderboard.find(query).sort('score_value', -1).limit(100))
    
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
        resp = requests.get(url)
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

@app.route("/upload/", defaults={"ref": "index.html"})
@app.route("/upload/<path:ref>")
def send_upload(ref):
    return cache_wrap(flask.send_from_directory("public/upload", ref), 3600)

@app.route("/api/upload", methods=["POST"])
def upload_file():
    try:
        # POSTリクエストにファイルの部分がない場合
        if 'file_tja' not in flask.request.files or 'file_music' not in flask.request.files:
            return flask.jsonify({'error': 'リクエストにファイルの部分がありません'})

        file_tja = flask.request.files['file_tja']
        file_music = flask.request.files['file_music']

        # ファイルが選択されておらず空のファイルを受け取った場合
        if file_tja.filename == '' or file_music.filename == '':
            return flask.jsonify({'error': 'ファイルが選択されていません'})

        # TJAファイルをテキストUTF-8/LFに変換
        tja_data = file_tja.read()
        # 尝试检测编码并转换为UTF-8
        try:
            # 首先尝试UTF-8解码
            tja_text = tja_data.decode("utf-8")
        except UnicodeDecodeError:
            # 如果UTF-8失败，尝试其他常见编码
            for encoding in ['shift_jis', 'euc-jp', 'iso-2022-jp', 'cp932']:
                try:
                    tja_text = tja_data.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                # 如果所有编码都失败，使用错误处理
                tja_text = tja_data.decode("utf-8", errors="replace")
        
        # 删除回车符（CR），只保留换行符（LF）
        tja_text = tja_text.replace('\r', '')
        print("TJAのサイズ:",len(tja_text))
        # TJAファイルの内容を解析
        tja = tjaf.Tja(tja_text)
        # TJAファイルのハッシュ値を生成
        msg = hashlib.sha256()
        msg.update(tja_data)
        tja_hash = msg.hexdigest()
        print("TJA:",tja_hash)
        # 音楽ファイルのハッシュ値を生成
        music_data = file_music.read()
        msg2 = hashlib.sha256()
        msg2.update(music_data)
        music_hash = msg2.hexdigest()
        print("音楽:",music_hash)
        # IDを生成
        generated_id = f"{tja_hash}-{music_hash}"
        # MongoDBのデータも作成
        db_entry = tja.to_mongo(generated_id, time.time_ns())
        # アップロード直後に有効化
        db_entry['enabled'] = True
        pprint.pprint(db_entry)

        # 必要な歌曲类型
        song_type = flask.request.form.get('song_type')
        if not song_type or song_type not in SONG_TYPES:
            return flask.jsonify({'error': 'invalid_song_type'})
        db_entry['song_type'] = song_type

        # mongoDBにデータをぶち込む（重複IDは部分更新で上書きし、_id を不変に保つ）
        coll = client['taiko']["songs"]
        try:
            coll.insert_one(db_entry)
        except DuplicateKeyError:
            coll.update_one({"id": db_entry["id"]}, {"$set": db_entry}, upsert=True)
        # キャッシュ削除（/api/songs）
        try:
            app.cache.delete_memoized(route_api_songs)
        except Exception:
            pass

        SONGS_DIR.mkdir(parents=True, exist_ok=True)
        target_dir = SONGS_DIR / generated_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # TJAを保存
        (target_dir / "main.tja").write_bytes(tja_data)
        # 曲ファイルも保存
        (target_dir / f"main.{db_entry['music_type']}").write_bytes(music_data)
    except Exception as e:
        error_str = ''.join(traceback.TracebackException.from_exception(e).format())
        return flask.jsonify({'error': error_str})

    return flask.jsonify({'success': True})

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

