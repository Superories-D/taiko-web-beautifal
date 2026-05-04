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
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

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
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from redis import Redis


APP_ROOT = pathlib.Path(__file__).resolve().parent


def path_from_env(name, default):
    return pathlib.Path(os.environ.get(name, str(default))).resolve()


SONGS_DIR = path_from_env('TAIKO_WEB_SONGS_DIR', APP_ROOT / 'public' / 'songs')


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
]
DAILY_CHALLENGE_DIFFICULTY = "oni"

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
db.leaderboard.create_index([('song_hash', 1), ('difficulty', 1), ('score_value', -1)])
db.leaderboard.create_index('username')
db.leaderboard.create_index([('song_hash', 1), ('difficulty', 1), ('period', 1), ('period_key', 1), ('identity_key', 1)])
db.leaderboard.create_index([('song_hash', 1), ('difficulty', 1), ('period', 1), ('period_key', 1), ('score_value', -1)])
db.daily_challenges.create_index('date', unique=True)
db.daily_challenge_scores.create_index([('date', 1), ('score_value', -1), ('played_at', 1)])
db.daily_challenge_scores.create_index('created_at')

DAILY_CHALLENGE_TZ = ZoneInfo(os.environ.get('TAIKO_WEB_DAILY_CHALLENGE_TZ', 'Asia/Shanghai')) if ZoneInfo else None
DAILY_CHALLENGE_KEEP_DAYS = 7


class HashException(Exception):
    pass


def api_error(message):
    return jsonify({'status': 'error', 'message': message})


def leaderboard_period_filter(period, now=None):
    now = now or datetime.utcnow()
    if period == 'all':
        return {'period': 'all', 'period_key': 'all'}
    if period == 'weekly':
        year, week, _ = now.isocalendar()
        return {'period': 'weekly', 'period_key': '%04d-W%02d' % (year, week)}
    return {'period': 'monthly', 'period_key': now.strftime('%Y-%m')}


def legacy_leaderboard_month_filter(now=None):
    now = now or datetime.utcnow()
    return {'month': now.strftime('%Y-%m'), 'period': {'$exists': False}}


def leaderboard_identity(data):
    if session.get('username'):
        user = db.users.find_one({'username': session.get('username')})
        display_name = user.get('display_name') if user else session.get('username')
        return 'user:%s' % session.get('username'), session.get('username'), display_name
    anonymous_id = (data.get('anonymous_id') or '').strip()
    if not re.match(r'^[A-Za-z0-9_-]{8,80}$', anonymous_id):
        anonymous_id = 'guest'
    display_name = (data.get('display_name') or 'Anonymous').strip()[:20] or 'Anonymous'
    return 'anon:%s' % anonymous_id, None, display_name


def song_public_payload(song):
    output = dict(song)
    output.pop('_id', None)
    output.pop('enabled', None)
    if output.get('maker_id') == 0:
        output['maker'] = 0
    elif output.get('maker_id'):
        output['maker'] = db.makers.find_one({'id': output['maker_id']}, {'_id': False})
    else:
        output['maker'] = None
    output.pop('maker_id', None)
    if output.get('category_id'):
        category = db.categories.find_one({'id': output['category_id']})
        output['category'] = category['title'] if category else None
    else:
        output['category'] = None
    if output.get('skin_id'):
        output['song_skin'] = db.song_skins.find_one({'id': output['skin_id']}, {'_id': False, 'id': False})
    else:
        output['song_skin'] = None
    output.pop('skin_id', None)
    return output


def daily_challenge_candidates():
    songs = db.songs.find({
        'enabled': True,
        'courses.%s' % DAILY_CHALLENGE_DIFFICULTY: {'$exists': True, '$ne': None}
    })
    candidates = []
    for song in songs:
        courses = song.get('courses') or {}
        if courses.get(DAILY_CHALLENGE_DIFFICULTY):
            candidates.append((song, DAILY_CHALLENGE_DIFFICULTY))
    return sorted(candidates, key=lambda item: (item[0].get('id', 0), item[1]))


def daily_challenge_now():
    return datetime.now(DAILY_CHALLENGE_TZ) if DAILY_CHALLENGE_TZ else datetime.utcnow()


def daily_challenge_date(now=None):
    return (now or daily_challenge_now()).strftime('%Y-%m-%d')


def daily_challenge_cutoff(now=None):
    current = now or daily_challenge_now()
    return (current.date() - timedelta(days=DAILY_CHALLENGE_KEEP_DAYS - 1)).strftime('%Y-%m-%d')


def cleanup_daily_challenge_data():
    cutoff = daily_challenge_cutoff()
    db.daily_challenges.delete_many({'date': {'$lt': cutoff}})
    db.daily_challenge_scores.delete_many({'date': {'$lt': cutoff}})


def get_or_create_daily_challenge(date_key=None):
    cleanup_daily_challenge_data()
    date_key = date_key or daily_challenge_date()
    challenge = db.daily_challenges.find_one({'date': date_key}, {'_id': False})
    if challenge:
        return challenge

    candidates = daily_challenge_candidates()
    if not candidates:
        return None
    seed = int(hashlib.md5(date_key.encode('utf-8')).hexdigest(), 16)
    song, difficulty = candidates[seed % len(candidates)]
    doc = {
        'date': date_key,
        'song_id': song.get('id'),
        'song_hash': song.get('hash') or song.get('title'),
        'difficulty': difficulty,
        'song': song_public_payload(song),
        'created_at': datetime.utcnow()
    }
    try:
        db.daily_challenges.insert_one(doc)
        doc.pop('_id', None)
        return doc
    except DuplicateKeyError:
        return db.daily_challenges.find_one({'date': date_key}, {'_id': False})


def daily_challenge_rank(date_key, score_value, played_at, score_id):
    return db.daily_challenge_scores.count_documents({
        'date': date_key,
        '$or': [
            {'score_value': {'$gt': score_value}},
            {'score_value': score_value, 'played_at': {'$lt': played_at}},
            {'score_value': score_value, 'played_at': played_at, '_id': {'$lte': score_id}}
        ]
    })


def daily_challenge_scores_for_date(date_key, limit=100):
    scores = list(db.daily_challenge_scores.find({'date': date_key}).sort([
        ('score_value', -1),
        ('played_at', 1),
        ('_id', 1)
    ]).limit(limit))
    return [{
        'rank': i + 1,
        'display_name': score.get('display_name', 'Anonymous'),
        'score_value': score.get('score_value', 0),
        'played_at': score.get('played_at').isoformat() + 'Z' if score.get('played_at') else None
    } for i, score in enumerate(scores)]


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
            if user['user_level'] < level:
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
    version = get_version()
    return render_template('index.html', version=version, config=get_config())


@app.route(basedir + 'api/csrftoken')
def route_csrftoken():
    return jsonify({'status': 'ok', 'token': generate_csrf()})


@app.route(basedir + 'admin')
@admin_required(level=50)
def route_admin():
    return redirect(basedir + 'admin/songs')


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
        song=song, categories=categories, song_skins=song_skins, makers=makers, admin=user, config=get_config())


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


@app.route(basedir + 'admin/songs/<int:id>/delete', methods=['POST'])
@limiter.limit("1 per day")
@admin_required(level=100)
def route_admin_songs_id_delete(id):
    song = db.songs.find_one({'id': id})
    if not song:
        return abort(404)

    db.songs.delete_one({'id': id})
    flash('Song deleted.')
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
    songs = [song_public_payload(song) for song in db.songs.find(query)]

    return cache_wrap(flask.jsonify(songs), 60)

@app.route(basedir + 'api/categories')
@app.cache.cached(timeout=15)
def route_api_categories():
    categories = list(db.categories.find({},{'_id': False}))
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
    try:
        score_value = int(score_value)
    except (TypeError, ValueError):
        return abort(400)
    display_name = data.get('display_name', 'Anonymous')
    
    if not song_hash or difficulty not in ['easy', 'normal', 'hard', 'oni', 'ura']:
        return abort(400)
    
    now = datetime.utcnow()
    identity_key, username, display_name = leaderboard_identity(data)

    saved = False
    rank = None
    for period in ['monthly', 'weekly', 'all']:
        period_query = leaderboard_period_filter(period, now)
        query = {
            'song_hash': song_hash,
            'difficulty': difficulty,
            'identity_key': identity_key,
            **period_query
        }
        existing = db.leaderboard.find_one(query)
        if not existing or score_value > existing.get('score_value', 0):
            db.leaderboard.update_one(query, {'$set': {
                'song_hash': song_hash,
                'difficulty': difficulty,
                'display_name': display_name,
                'username': username,
                'identity_key': identity_key,
                'score_value': score_value,
                'period': period_query['period'],
                'period_key': period_query['period_key'],
                'updated_at': now
            }, '$setOnInsert': {
                'created_at': now
            }}, upsert=True)
            saved = True

    monthly_query = {
        'song_hash': song_hash,
        'difficulty': difficulty,
        **leaderboard_period_filter('monthly', now)
    }
    higher_count = db.leaderboard.count_documents({
        **monthly_query,
        'score_value': {'$gt': score_value}
    })
    rank = higher_count + 1
    
    for period in ['monthly', 'weekly']:
        cleanup_query = {
            'song_hash': song_hash,
            'difficulty': difficulty,
            **leaderboard_period_filter(period, now)
        }
        extra_scores = list(db.leaderboard.find(cleanup_query).sort('score_value', -1).skip(100))
        if extra_scores:
            db.leaderboard.delete_many({'_id': {'$in': [s['_id'] for s in extra_scores]}})
    
    return jsonify({
        'status': 'ok',
        'rank': rank,
        'in_top_100': rank <= 100,
        'saved': saved,
        'period': 'monthly'
    })


@app.route(basedir + 'api/leaderboard/get')
def route_api_leaderboard_get():
    song_hash = request.args.get('hash')
    difficulty = request.args.get('difficulty')
    period = request.args.get('period') or 'monthly'
    
    if not song_hash:
        return abort(400)
    if period not in ['monthly', 'weekly', 'all']:
        return abort(400)
    
    now = datetime.utcnow()
    query = {
        'song_hash': song_hash,
        **leaderboard_period_filter(period, now)
    }
    if difficulty:
        if difficulty not in ['easy', 'normal', 'hard', 'oni', 'ura']:
            return abort(400)
        query['difficulty'] = difficulty
    
    legacy_scores = False
    scores = list(db.leaderboard.find(query).sort('score_value', -1).limit(100))
    if not scores and period == 'monthly':
        legacy_query = {
            'song_hash': song_hash,
            **legacy_leaderboard_month_filter(now)
        }
        if difficulty:
            legacy_query['difficulty'] = difficulty
        scores = list(db.leaderboard.find(legacy_query).sort('score_value', -1).limit(100))
        legacy_scores = bool(scores)
    
    result = []
    for i, score in enumerate(scores):
        result.append({
            'rank': i + 1,
            'display_name': score.get('display_name', 'Anonymous'),
            'score_value': score.get('score_value', 0),
            'difficulty': score.get('difficulty')
        })

    total_scores = len(scores) if legacy_scores else db.leaderboard.count_documents(query)
    my_rank = None
    identity_key = None
    if session.get('username') or request.args.get('anonymous_id'):
        identity_key, _, _ = leaderboard_identity({'anonymous_id': request.args.get('anonymous_id') or ''})
    if identity_key:
        my_score = db.leaderboard.find_one({**query, 'identity_key': identity_key})
        if my_score:
            my_rank = db.leaderboard.count_documents({**query, 'score_value': {'$gt': my_score.get('score_value', 0)}}) + 1
    
    return jsonify({
        'status': 'ok',
        'leaderboard': result,
        'period': period,
        'period_key': leaderboard_period_filter(period, now)['period_key'],
        'total_scores': total_scores,
        'my_rank': my_rank
    })


@app.route(basedir + 'api/daily_challenge')
def route_api_daily_challenge():
    challenge = get_or_create_daily_challenge()
    if not challenge:
        return jsonify({'status': 'ok', 'date': daily_challenge_date(), 'song': None})
    return jsonify({
        'status': 'ok',
        'date': challenge['date'],
        'difficulty': challenge.get('difficulty', DAILY_CHALLENGE_DIFFICULTY),
        'song': challenge.get('song')
    })


@app.route(basedir + 'api/daily-challenge/current')
def route_api_daily_challenge_current():
    challenge = get_or_create_daily_challenge()
    if not challenge:
        return api_error('no_oni_songs')
    return jsonify({
        'status': 'ok',
        'challenge': challenge
    })


@app.route(basedir + 'api/daily-challenge/submit', methods=['POST'])
@limiter.limit("30 per minute")
def route_api_daily_challenge_submit():
    data = request.get_json()
    if not data:
        return abort(400)

    date_key = data.get('date') or daily_challenge_date()
    if not isinstance(date_key, str) or not re.match(r'^\d{4}-\d{2}-\d{2}$', date_key):
        return abort(400)
    cutoff = daily_challenge_cutoff()
    if date_key < cutoff or date_key > daily_challenge_date():
        return abort(400)

    challenge = get_or_create_daily_challenge(date_key) if date_key == daily_challenge_date() else db.daily_challenges.find_one({'date': date_key}, {'_id': False})
    if not challenge:
        return api_error('daily_challenge_not_found')

    song_hash = data.get('hash')
    difficulty = data.get('difficulty')
    try:
        score_value = int(data.get('score', 0))
    except (TypeError, ValueError):
        return abort(400)
    if score_value < 0:
        score_value = 0

    if song_hash != challenge.get('song_hash') or difficulty != DAILY_CHALLENGE_DIFFICULTY:
        return api_error('daily_challenge_mismatch')

    display_name = (data.get('display_name') or 'Anonymous').strip()[:20] or 'Anonymous'
    played_at = datetime.utcnow()
    result = db.daily_challenge_scores.insert_one({
        'date': challenge['date'],
        'song_hash': challenge['song_hash'],
        'song_id': challenge.get('song_id'),
        'difficulty': DAILY_CHALLENGE_DIFFICULTY,
        'display_name': display_name,
        'score_value': score_value,
        'played_at': played_at,
        'created_at': played_at
    })
    rank = daily_challenge_rank(challenge['date'], score_value, played_at, result.inserted_id)
    return jsonify({
        'status': 'ok',
        'rank': rank,
        'in_top_100': rank <= 100,
        'date': challenge['date'],
        'leaderboard': daily_challenge_scores_for_date(challenge['date'])
    })


@app.route(basedir + 'api/daily-challenge/leaderboard')
def route_api_daily_challenge_leaderboard():
    cleanup_daily_challenge_data()
    date_key = request.args.get('date') or daily_challenge_date()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_key):
        return abort(400)
    cutoff = daily_challenge_cutoff()
    if date_key < cutoff or date_key > daily_challenge_date():
        return abort(400)

    challenge = get_or_create_daily_challenge(date_key) if date_key == daily_challenge_date() else db.daily_challenges.find_one({'date': date_key}, {'_id': False})
    dates = []
    for challenge_doc in db.daily_challenges.find({'date': {'$gte': cutoff}}, {'_id': False}).sort('date', -1).limit(DAILY_CHALLENGE_KEEP_DAYS):
        dates.append({
            'date': challenge_doc.get('date'),
            'song': challenge_doc.get('song'),
            'difficulty': challenge_doc.get('difficulty', DAILY_CHALLENGE_DIFFICULTY)
        })

    return jsonify({
        'status': 'ok',
        'date': date_key,
        'challenge': challenge,
        'dates': dates,
        'leaderboard': daily_challenge_scores_for_date(date_key)
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

def asset_cache_wrap(res_from, secs):
    res = cache_wrap(res_from, secs)
    res.headers["Cache-Control"] = f"public, max-age={secs}, s-maxage={secs}, immutable"
    return res

@app.route(basedir + "src/<path:ref>")
def send_src(ref):
    return cache_wrap(flask.send_from_directory("public/src", ref), 3600)

@app.route(basedir + "assets/<path:ref>")
def send_assets(ref):
    return asset_cache_wrap(flask.send_from_directory("public/assets", ref), 604800)

@app.route(basedir + "songs/<path:ref>")
def send_songs(ref):
    return cache_wrap(flask.send_from_directory(str(SONGS_DIR), ref), 604800)

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

@app.route("/api/delete", methods=["POST"])
def delete():
    return flask.jsonify({ "success": False, "reason": "Deletion is disabled" }), 403

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run the taiko-web development server.')
    parser.add_argument('port', type=int, metavar='PORT', nargs='?', default=34801, help='Port to listen on.')
    parser.add_argument('-b', '--bind-address', default='localhost', help='Bind server to address.')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode.')
    args = parser.parse_args()

    app.run(host=args.bind_address, port=args.port, debug=args.debug)

