"""Personal song library, public profiles, follows and asynchronous challenges."""

from datetime import datetime, timedelta
from functools import wraps
import hashlib
import json
import math
import re
import secrets
import uuid

from flask import Blueprint, abort, jsonify, request, session
from pymongo.errors import DuplicateKeyError


DIFFICULTIES = ('easy', 'normal', 'hard', 'oni', 'ura')
ACTIVE_CHALLENGE_STATES = ('pending', 'active')
PLAYLIST_MAX_COUNT = 50
PLAYLIST_MAX_SONGS = 200
CHALLENGE_DAYS = 7
CHALLENGE_HISTORY_DAYS = 30
GHOST_ENCODING = 'gzip'
PUBLIC_ID_RE = re.compile(r'^[a-f0-9]{32}$')
DELETED_USER_PREFIX = '__deleted_user__:'


def utcnow():
    return datetime.utcnow()


def iso(value):
    return value.isoformat() + 'Z' if isinstance(value, datetime) else None


def no_store(response):
    response.headers['Cache-Control'] = 'private, no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def register_library_social_routes(
    app,
    db,
    limiter,
    csrf,
    basedir,
    login_required,
    serialize_public_song,
    decode_ghost_payload,
    encode_ghost_payload,
):
    prefix = basedir.rstrip('/') + '/api'
    if not prefix.startswith('/'):
        prefix = '/' + prefix
    bp = Blueprint('library_social', __name__, url_prefix=prefix)

    def fail(message, status=400):
        return jsonify({'status': 'error', 'message': message}), status

    def json_body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def current_username():
        return session.get('username')

    def enabled_song(song_hash):
        if not isinstance(song_hash, str) or not 1 <= len(song_hash) <= 500:
            return None
        candidates = [song_hash]
        if song_hash.isdigit():
            candidates.append(int(song_hash))
        return db.songs.find_one({
            'enabled': True,
            '$or': [
                {'hash': song_hash},
                {'id': {'$in': candidates}},
                {'title': song_hash},
            ]
        })

    def public_song(song):
        return serialize_public_song(song) if song else None

    def public_songs_by_hashes(hashes):
        output = []
        seen = set()
        for value in hashes or []:
            value = str(value)
            if value in seen:
                continue
            seen.add(value)
            song = enabled_song(value)
            serialized = public_song(song)
            if serialized:
                output.append(serialized)
        return output

    def ensure_public_id(user):
        if not user:
            return None
        public_id = user.get('public_id')
        if isinstance(public_id, str) and PUBLIC_ID_RE.fullmatch(public_id):
            return public_id
        for _attempt in range(4):
            public_id = uuid.uuid4().hex
            try:
                query = {'_id': user['_id']} if user.get('_id') is not None else {'username': user['username']}
                db.users.update_one(query, {'$set': {'public_id': public_id}})
                user['public_id'] = public_id
                return public_id
            except DuplicateKeyError:
                continue
        raise RuntimeError('unable to allocate public id')

    def user_by_public_id(public_id):
        if not isinstance(public_id, str) or not PUBLIC_ID_RE.fullmatch(public_id):
            return None
        return db.users.find_one({'public_id': public_id})

    def public_user(user, viewer=None):
        if not user:
            return None
        public_id = ensure_public_id(user)
        username = user.get('username')
        following = False
        blocked = False
        if viewer and username and viewer != username:
            following = db.user_follows.find_one({
                'follower_username': viewer,
                'target_username': username,
            }) is not None
            blocked = db.user_blocks.find_one({
                'blocker_username': viewer,
                'blocked_username': username,
            }) is not None
        return {
            'public_id': public_id,
            'display_name': user.get('display_name') or 'Player',
            'following': following,
            'blocked': blocked,
        }

    def public_user_by_username(username, viewer=None):
        user = db.users.find_one({'username': username}) if username else None
        if user:
            return public_user(user, viewer)
        if isinstance(username, str) and username.startswith(DELETED_USER_PREFIX):
            return {'public_id': None, 'display_name': 'Deleted user', 'following': False, 'blocked': False}
        return None

    def blocked_between(left, right):
        return db.user_blocks.find_one({'$or': [
            {'blocker_username': left, 'blocked_username': right},
            {'blocker_username': right, 'blocked_username': left},
        ]}) is not None

    def playlist_doc(doc, include_songs=True):
        data = {
            'playlist_id': doc.get('playlist_id'),
            'name': doc.get('name') or 'Playlist',
            'description': doc.get('description') or '',
            'visibility': doc.get('visibility') or 'private',
            'shared': bool(doc.get('share_token')),
            'updated_at': iso(doc.get('updated_at')),
        }
        if include_songs:
            data['song_hashes'] = [str(value) for value in doc.get('song_hashes', [])][:PLAYLIST_MAX_SONGS]
            data['songs'] = public_songs_by_hashes(data['song_hashes'])
        return data

    def own_playlist(playlist_id):
        if not isinstance(playlist_id, str) or not PUBLIC_ID_RE.fullmatch(playlist_id):
            return None
        return db.song_playlists.find_one({
            'playlist_id': playlist_id,
            'owner_username': current_username(),
        })

    def validate_playlist_fields(data, partial=False):
        output = {}
        if not partial or 'name' in data:
            name = data.get('name')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
                return None
            output['name'] = name.strip()
        if not partial or 'description' in data:
            description = data.get('description', '')
            if not isinstance(description, str) or len(description.strip()) > 200:
                return None
            output['description'] = description.strip()
        if 'song_hashes' in data:
            hashes = data.get('song_hashes')
            if not isinstance(hashes, list) or len(hashes) > PLAYLIST_MAX_SONGS:
                return None
            normalized = []
            for value in hashes:
                if not isinstance(value, str) or not enabled_song(value):
                    return None
                if value not in normalized:
                    normalized.append(value)
            output['song_hashes'] = normalized
        return output

    def challenge_status(doc, now=None):
        now = now or utcnow()
        status = doc.get('status') or 'pending'
        if status in ACTIVE_CHALLENGE_STATES and doc.get('expires_at') and doc['expires_at'] <= now:
            db.async_challenges.update_one(
                {'challenge_id': doc.get('challenge_id'), 'status': {'$in': list(ACTIVE_CHALLENGE_STATES)}},
                {'$set': {'status': 'expired'}},
            )
            status = 'expired'
            doc['status'] = status
        return status

    def result_rank(result):
        if not result:
            return (-1, -10**9, -10**9, -1, float('-inf'))
        timestamp = result.get('updated_at')
        seconds = timestamp.timestamp() if isinstance(timestamp, datetime) else float('inf')
        return (
            int(result.get('score', 0)),
            -int(result.get('bad', 0)),
            -int(result.get('ok', 0)),
            int(result.get('max_combo', 0)),
            -seconds,
        )

    def challenge_results(challenge_id):
        return list(db.async_challenge_results.find({'challenge_id': challenge_id}))

    def serialize_result(result, include_ghost=False):
        if not result:
            return None
        user = db.users.find_one({'username': result.get('username')})
        output = {
            'player': public_user_by_username(result.get('username')),
            'score': int(result.get('score', 0)),
            'good': int(result.get('good', 0)),
            'ok': int(result.get('ok', 0)),
            'bad': int(result.get('bad', 0)),
            'max_combo': int(result.get('max_combo', 0)),
            'drumroll': int(result.get('drumroll', 0)),
            'clear': bool(result.get('clear')),
            'updated_at': iso(result.get('updated_at')),
            'has_ghost': bool(result.get('ghost_payload')),
        }
        if include_ghost and result.get('ghost_payload'):
            output['ghost_payload'] = result.get('ghost_payload')
            output['ghost_encoding'] = result.get('ghost_encoding') or GHOST_ENCODING
        return output

    def challenge_doc(doc, include_ghost=False):
        username = current_username()
        sender = public_user_by_username(doc.get('sender_username'), username)
        recipient = public_user_by_username(doc.get('recipient_username'), username)
        results = challenge_results(doc.get('challenge_id'))
        serialized_results = [serialize_result(item) for item in results]
        serialized_results = [item for item in serialized_results if item]
        ordered = sorted(results, key=result_rank, reverse=True)
        leader = public_user_by_username(ordered[0].get('username')) if ordered else None
        opponent_result = next((item for item in results if item.get('username') != username), None)
        output = {
            'challenge_id': doc.get('challenge_id'),
            'sender': sender,
            'recipient': recipient,
            'role': 'sender' if doc.get('sender_username') == username else 'recipient',
            'song_id': doc.get('song_id'),
            'song_hash': doc.get('song_hash'),
            'difficulty': doc.get('difficulty'),
            'rule_version': doc.get('rule_version') or 'standard-v1',
            'status': challenge_status(doc),
            'created_at': iso(doc.get('created_at')),
            'expires_at': iso(doc.get('expires_at')),
            'results': serialized_results,
            'leader': leader,
        }
        if include_ghost:
            output['opponent_result'] = serialize_result(opponent_result, include_ghost=True)
        return output

    def challenge_for_user(challenge_id):
        if not isinstance(challenge_id, str) or not PUBLIC_ID_RE.fullmatch(challenge_id):
            return None
        username = current_username()
        challenge = db.async_challenges.find_one({
            'challenge_id': challenge_id,
            '$or': [{'sender_username': username}, {'recipient_username': username}],
        })
        if not challenge:
            return None
        other = challenge.get('recipient_username') if challenge.get('sender_username') == username else challenge.get('sender_username')
        if other and blocked_between(username, other):
            return None
        return challenge

    def challenge_visible_to_user(doc, username=None):
        username = username or current_username()
        if not doc or not username:
            return False
        other = doc.get('recipient_username') if doc.get('sender_username') == username else doc.get('sender_username')
        return not other or not blocked_between(username, other)

    @bp.before_request
    def protect_mutations():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and app.config.get('WTF_CSRF_ENABLED', True):
            csrf.protect()

    @bp.after_request
    def protect_private_responses(response):
        return no_store(response)

    @bp.route('/library/favorites')
    @limiter.limit('120 per minute')
    @login_required
    def favorites_get():
        docs = list(db.song_favorites.find({'username': current_username()}).sort('created_at', -1).limit(1000))
        hashes = [doc.get('song_hash') for doc in docs if doc.get('song_hash')]
        return jsonify({'status': 'ok', 'song_hashes': hashes, 'songs': public_songs_by_hashes(hashes)})

    @bp.route('/library/favorites', methods=['POST'])
    @limiter.limit('120 per minute')
    @login_required
    def favorites_add():
        data = json_body()
        song_hash = data.get('song_hash')
        song = enabled_song(song_hash)
        if not song:
            return fail('song_not_found', 404)
        now = utcnow()
        db.song_favorites.update_one(
            {'username': current_username(), 'song_hash': song_hash},
            {'$set': {'song_id': song.get('id'), 'updated_at': now}, '$setOnInsert': {'created_at': now}},
            upsert=True,
        )
        return jsonify({'status': 'ok', 'favorite': True, 'song_hash': song_hash})

    @bp.route('/library/favorites/<path:song_hash>', methods=['DELETE'])
    @limiter.limit('120 per minute')
    @login_required
    def favorites_remove(song_hash):
        db.song_favorites.delete_one({'username': current_username(), 'song_hash': song_hash})
        return jsonify({'status': 'ok', 'favorite': False, 'song_hash': song_hash})

    @bp.route('/library/playlists')
    @limiter.limit('120 per minute')
    @login_required
    def playlists_get():
        docs = db.song_playlists.find({'owner_username': current_username()}).sort('updated_at', -1).limit(PLAYLIST_MAX_COUNT)
        return jsonify({'status': 'ok', 'playlists': [playlist_doc(doc) for doc in docs]})

    @bp.route('/library/playlists', methods=['POST'])
    @limiter.limit('30 per hour')
    @login_required
    def playlists_create():
        if db.song_playlists.count_documents({'owner_username': current_username()}) >= PLAYLIST_MAX_COUNT:
            return fail('playlist_limit_reached', 409)
        data = json_body()
        fields = validate_playlist_fields(data)
        if fields is None:
            return fail('invalid_playlist')
        now = utcnow()
        doc = {
            'playlist_id': uuid.uuid4().hex,
            'owner_username': current_username(),
            'name': fields['name'],
            'description': fields['description'],
            'song_hashes': fields.get('song_hashes', []),
            'visibility': 'private',
            'created_at': now,
            'updated_at': now,
        }
        db.song_playlists.insert_one(doc)
        return jsonify({'status': 'ok', 'playlist': playlist_doc(doc)}), 201

    @bp.route('/library/playlists/<playlist_id>', methods=['PATCH'])
    @limiter.limit('120 per minute')
    @login_required
    def playlists_update(playlist_id):
        playlist = own_playlist(playlist_id)
        if not playlist:
            return fail('playlist_not_found', 404)
        fields = validate_playlist_fields(json_body(), partial=True)
        if fields is None or not fields:
            return fail('invalid_playlist')
        fields['updated_at'] = utcnow()
        db.song_playlists.update_one({'_id': playlist['_id']}, {'$set': fields})
        playlist.update(fields)
        return jsonify({'status': 'ok', 'playlist': playlist_doc(playlist)})

    @bp.route('/library/playlists/<playlist_id>', methods=['DELETE'])
    @limiter.limit('30 per hour')
    @login_required
    def playlists_delete(playlist_id):
        playlist = own_playlist(playlist_id)
        if not playlist:
            return fail('playlist_not_found', 404)
        db.song_playlists.delete_one({'_id': playlist['_id']})
        return jsonify({'status': 'ok'})

    @bp.route('/library/playlists/<playlist_id>/songs', methods=['POST'])
    @limiter.limit('120 per minute')
    @login_required
    def playlist_song_add(playlist_id):
        playlist = own_playlist(playlist_id)
        if not playlist:
            return fail('playlist_not_found', 404)
        song_hash = json_body().get('song_hash')
        if not enabled_song(song_hash):
            return fail('song_not_found', 404)
        hashes = [str(value) for value in playlist.get('song_hashes', [])]
        if song_hash not in hashes and len(hashes) >= PLAYLIST_MAX_SONGS:
            return fail('playlist_song_limit_reached', 409)
        if song_hash not in hashes:
            hashes.append(song_hash)
            db.song_playlists.update_one({'_id': playlist['_id']}, {'$set': {'song_hashes': hashes, 'updated_at': utcnow()}})
        return jsonify({'status': 'ok', 'song_hashes': hashes})

    @bp.route('/library/playlists/<playlist_id>/songs/<path:song_hash>', methods=['DELETE'])
    @limiter.limit('120 per minute')
    @login_required
    def playlist_song_remove(playlist_id, song_hash):
        playlist = own_playlist(playlist_id)
        if not playlist:
            return fail('playlist_not_found', 404)
        hashes = [str(value) for value in playlist.get('song_hashes', []) if str(value) != song_hash]
        db.song_playlists.update_one({'_id': playlist['_id']}, {'$set': {'song_hashes': hashes, 'updated_at': utcnow()}})
        return jsonify({'status': 'ok', 'song_hashes': hashes})

    @bp.route('/library/playlists/<playlist_id>/share', methods=['POST'])
    @limiter.limit('30 per hour')
    @login_required
    def playlist_share(playlist_id):
        playlist = own_playlist(playlist_id)
        if not playlist:
            return fail('playlist_not_found', 404)
        token = secrets.token_urlsafe(24)
        db.song_playlists.update_one({'_id': playlist['_id']}, {'$set': {
            'share_token': token,
            'visibility': 'shared',
            'updated_at': utcnow(),
        }})
        return jsonify({'status': 'ok', 'share_token': token})

    @bp.route('/library/playlists/<playlist_id>/share', methods=['DELETE'])
    @limiter.limit('30 per hour')
    @login_required
    def playlist_unshare(playlist_id):
        playlist = own_playlist(playlist_id)
        if not playlist:
            return fail('playlist_not_found', 404)
        db.song_playlists.update_one({'_id': playlist['_id']}, {
            '$unset': {'share_token': ''},
            '$set': {'visibility': 'private', 'updated_at': utcnow()},
        })
        return jsonify({'status': 'ok'})

    @bp.route('/library/shared/<share_token>')
    @limiter.limit('120 per minute')
    def playlist_shared(share_token):
        if not isinstance(share_token, str) or not 20 <= len(share_token) <= 80:
            return fail('playlist_not_found', 404)
        playlist = db.song_playlists.find_one({'share_token': share_token, 'visibility': 'shared'})
        if not playlist:
            return fail('playlist_not_found', 404)
        owner = db.users.find_one({'username': playlist.get('owner_username')})
        data = playlist_doc(playlist)
        data['owner'] = public_user(owner)
        data.pop('song_hashes', None)
        return jsonify({'status': 'ok', 'playlist': data})

    @bp.route('/library/import', methods=['POST'])
    @limiter.limit('10 per hour')
    @login_required
    def library_import():
        data = json_body()
        favorites = data.get('favorites', [])
        playlists = data.get('playlists', [])
        if not isinstance(favorites, list) or len(favorites) > 1000 or not isinstance(playlists, list) or len(playlists) > PLAYLIST_MAX_COUNT:
            return fail('invalid_library_import')
        canonical = json.dumps({'favorites': favorites, 'playlists': playlists}, sort_keys=True, separators=(',', ':'))
        import_key = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        username = current_username()
        if db.library_imports.find_one({'username': username, 'import_key': import_key}):
            return jsonify({'status': 'ok', 'already_imported': True, 'favorites': 0, 'playlists': 0})
        favorite_count = 0
        now = utcnow()
        for song_hash in favorites:
            song = enabled_song(song_hash) if isinstance(song_hash, str) else None
            if song:
                result = db.song_favorites.update_one(
                    {'username': username, 'song_hash': song_hash},
                    {'$set': {'song_id': song.get('id'), 'updated_at': now}, '$setOnInsert': {'created_at': now}},
                    upsert=True,
                )
                if result.upserted_id is not None:
                    favorite_count += 1
        existing_count = db.song_playlists.count_documents({'owner_username': username})
        playlist_count = 0
        existing_names = {doc.get('name') for doc in db.song_playlists.find({'owner_username': username}, {'name': True})}
        for index, item in enumerate(playlists):
            if existing_count + playlist_count >= PLAYLIST_MAX_COUNT or not isinstance(item, dict):
                break
            fields = validate_playlist_fields(item)
            if fields is None:
                continue
            source_key = '{}:{}'.format(import_key, item.get('local_id') or index)
            if db.song_playlists.find_one({'owner_username': username, 'source_import_key': source_key}):
                continue
            base_name = fields['name']
            name = base_name
            suffix = 2
            while name in existing_names:
                tail = ' ({})'.format(suffix)
                name = base_name[:40 - len(tail)] + tail
                suffix += 1
            existing_names.add(name)
            doc = {
                'playlist_id': uuid.uuid4().hex,
                'owner_username': username,
                'name': name,
                'description': fields['description'],
                'song_hashes': fields.get('song_hashes', []),
                'visibility': 'private',
                'source_import_key': source_key,
                'created_at': now,
                'updated_at': now,
            }
            try:
                db.song_playlists.insert_one(doc)
                playlist_count += 1
            except DuplicateKeyError:
                # A concurrent retry of the same local import is harmless;
                # the partial unique index on source_import_key owns it.
                continue
        db.library_imports.update_one(
            {'username': username, 'import_key': import_key},
            {'$setOnInsert': {'created_at': now}},
            upsert=True,
        )
        return jsonify({'status': 'ok', 'favorites': favorite_count, 'playlists': playlist_count})

    @bp.route('/library/discover')
    @limiter.limit('120 per minute')
    @login_required
    def library_discover():
        username = current_username()
        favorites = {doc.get('song_hash') for doc in db.song_favorites.find({'username': username}, {'song_hash': True})}
        recent_docs = list(db.play_records.find({'username': username, 'is_auto': False}).sort('played_at', -1).limit(500))
        recent_hashes = []
        for doc in recent_docs:
            value = doc.get('song_hash')
            if value and value not in recent_hashes:
                recent_hashes.append(value)
        played = set(recent_hashes)
        category_weights = {}
        maker_weights = {}
        difficulty_levels = {'easy': 2, 'normal': 4, 'hard': 6, 'oni': 8, 'ura': 10}
        stable_attempts = {}
        for record in recent_docs:
            difficulty = record.get('difficulty')
            if difficulty in difficulty_levels:
                stable_attempts.setdefault(difficulty, []).append(float(record.get('score') or 0))
        stable_level = 4
        for difficulty, scores in stable_attempts.items():
            if len(scores) >= 3 and sorted(scores)[len(scores) // 2] >= 600000:
                stable_level = max(stable_level, difficulty_levels[difficulty])
        all_songs = list(db.songs.find({'enabled': True}).limit(2000))
        favorite_songs = [enabled_song(value) for value in favorites]
        for song in favorite_songs:
            if not song:
                continue
            category_weights[song.get('category_id')] = category_weights.get(song.get('category_id'), 0) + 3
            maker_weights[song.get('maker_id')] = maker_weights.get(song.get('maker_id'), 0) + 2
        seed = int(hashlib.sha256((username + utcnow().strftime('%Y-%m-%d')).encode('utf-8')).hexdigest()[:8], 16)

        def score_song(song):
            identity = str(song.get('hash') or song.get('id'))
            score = 20 if identity not in played else 0
            score += category_weights.get(song.get('category_id'), 0)
            score += maker_weights.get(song.get('maker_id'), 0)
            course_levels = [
                difficulty_levels[difficulty]
                for difficulty, course in (song.get('courses') or {}).items()
                if course and difficulty in difficulty_levels and isinstance(course, dict)
            ]
            if course_levels:
                nearest = min(course_levels, key=lambda level: abs(level - stable_level))
                score += max(0, 12 - abs(nearest - stable_level) * 2)
            if identity in favorites:
                score -= 12
            # A very high recent score on a stale chart is less useful than a
            # new route for the player.  The rule is deterministic and does
            # not remove such songs from favorites or recent history.
            best_score = max([float(item.get('score') or 0) for item in recent_docs if item.get('song_hash') == identity] or [0])
            updated = song.get('updated_at') or song.get('created_at')
            if best_score >= 950000 and isinstance(updated, datetime) and updated < utcnow() - timedelta(days=90):
                score -= 18
            score += ((seed ^ int(hashlib.sha256(identity.encode('utf-8')).hexdigest()[:8], 16)) % 1000) / 1000
            return score

        ranked = sorted(all_songs, key=score_song, reverse=True)
        serialized = []
        for song in ranked[:100]:
            item = public_song(song)
            if item:
                item['recommendation_reason'] = 'unplayed' if str(song.get('hash') or song.get('id')) not in played else 'similar difficulty'
                serialized.append(item)
        return jsonify({
            'status': 'ok',
            'recommended': [song for song in serialized if song],
            'recent': public_songs_by_hashes(recent_hashes[:100]),
        })

    @bp.route('/social/profile/<public_id>')
    @limiter.limit('120 per minute')
    def social_profile(public_id):
        user = user_by_public_id(public_id)
        if not user:
            return fail('user_not_found', 404)
        username = user.get('username')
        viewer = current_username()
        if viewer and blocked_between(viewer, username):
            return fail('user_not_found', 404)
        wins = losses = draws = 0
        challenge_rows = db.async_challenges.find({'$or': [
            {'sender_username': username}, {'recipient_username': username},
        ]}).sort('created_at', -1).limit(200)
        for challenge in challenge_rows:
            results = challenge_results(challenge.get('challenge_id'))
            if len(results) < 2:
                continue
            ordered = sorted(results, key=result_rank, reverse=True)
            if result_rank(ordered[0]) == result_rank(ordered[1]):
                draws += 1
            elif ordered[0].get('username') == username:
                wins += 1
            else:
                losses += 1
        top_scores = []
        for row in db.leaderboard.find({'username': username}, {'_id': False, 'song_hash': True, 'difficulty': True, 'score_value': True}).sort('score_value', -1).limit(5):
            top_scores.append({
                'song_hash': row.get('song_hash'),
                'difficulty': row.get('difficulty'),
                'score': int(row.get('score_value') or 0),
            })
        return jsonify({'status': 'ok', 'profile': {
            **public_user(user, viewer),
            'followers': db.user_follows.count_documents({'target_username': username}),
            'following_count': db.user_follows.count_documents({'follower_username': username}),
            'challenge_count': db.async_challenge_results.count_documents({'username': username}),
            'rank_summary': user.get('rank_summary') or user.get('rank') or None,
            'top_scores': top_scores,
            'challenge_stats': {'wins': wins, 'losses': losses, 'draws': draws},
        }})

    @bp.route('/social/users')
    @limiter.limit('60 per minute')
    @login_required
    def social_users():
        query = (request.args.get('q') or '').strip()
        if len(query) < 2 or len(query) > 40:
            return jsonify({'status': 'ok', 'users': []})
        regex = re.compile(re.escape(query), re.IGNORECASE)
        users = db.users.find({'display_name': regex}).limit(20)
        current = current_username()
        output = []
        for user in users:
            username = user.get('username')
            if username == current or blocked_between(current, username):
                continue
            output.append(public_user(user, current))
        return jsonify({'status': 'ok', 'users': output})

    def relation_list(field, other_field):
        current = current_username()
        docs = db.user_follows.find({field: current}).sort('created_at', -1).limit(500)
        output = []
        for doc in docs:
            user = db.users.find_one({'username': doc.get(other_field)})
            if user and not blocked_between(current, user.get('username')):
                output.append(public_user(user, current))
        return output

    @bp.route('/social/following')
    @limiter.limit('120 per minute')
    @login_required
    def social_following():
        return jsonify({'status': 'ok', 'users': relation_list('follower_username', 'target_username')})

    @bp.route('/social/followers')
    @limiter.limit('120 per minute')
    @login_required
    def social_followers():
        return jsonify({'status': 'ok', 'users': relation_list('target_username', 'follower_username')})

    @bp.route('/social/blocked')
    @limiter.limit('120 per minute')
    @login_required
    def social_blocked():
        current = current_username()
        users = []
        docs = db.user_blocks.find({'blocker_username': current}).sort('created_at', -1).limit(500)
        for doc in docs:
            user = db.users.find_one({'username': doc.get('blocked_username')})
            profile = public_user(user, current)
            if profile:
                profile['blocked'] = True
                users.append(profile)
        return jsonify({'status': 'ok', 'users': users})

    @bp.route('/social/follow/<public_id>', methods=['POST'])
    @limiter.limit('60 per hour')
    @login_required
    def social_follow(public_id):
        target = user_by_public_id(public_id)
        current = current_username()
        if not target or target.get('username') == current or blocked_between(current, target.get('username')):
            return fail('user_not_found', 404)
        db.user_follows.update_one(
            {'follower_username': current, 'target_username': target['username']},
            {'$setOnInsert': {'created_at': utcnow()}},
            upsert=True,
        )
        return jsonify({'status': 'ok', 'following': True})

    @bp.route('/social/follow/<public_id>', methods=['DELETE'])
    @limiter.limit('60 per hour')
    @login_required
    def social_unfollow(public_id):
        target = user_by_public_id(public_id)
        if target:
            db.user_follows.delete_one({'follower_username': current_username(), 'target_username': target.get('username')})
        return jsonify({'status': 'ok', 'following': False})

    @bp.route('/social/block/<public_id>', methods=['POST'])
    @limiter.limit('30 per hour')
    @login_required
    def social_block(public_id):
        target = user_by_public_id(public_id)
        current = current_username()
        if not target or target.get('username') == current:
            return fail('user_not_found', 404)
        other = target['username']
        db.user_blocks.update_one(
            {'blocker_username': current, 'blocked_username': other},
            {'$setOnInsert': {'created_at': utcnow()}},
            upsert=True,
        )
        db.user_follows.delete_many({'$or': [
            {'follower_username': current, 'target_username': other},
            {'follower_username': other, 'target_username': current},
        ]})
        return jsonify({'status': 'ok', 'blocked': True})

    @bp.route('/social/block/<public_id>', methods=['DELETE'])
    @limiter.limit('30 per hour')
    @login_required
    def social_unblock(public_id):
        target = user_by_public_id(public_id)
        if target:
            db.user_blocks.delete_one({'blocker_username': current_username(), 'blocked_username': target.get('username')})
        return jsonify({'status': 'ok', 'blocked': False})

    @bp.route('/challenges')
    @limiter.limit('120 per minute')
    @login_required
    def challenges_get():
        username = current_username()
        docs = list(db.async_challenges.find({'$or': [
            {'sender_username': username}, {'recipient_username': username},
        ]}).sort('created_at', -1).limit(100))
        return jsonify({'status': 'ok', 'challenges': [challenge_doc(doc) for doc in docs if challenge_visible_to_user(doc, username)]})

    @bp.route('/challenges', methods=['POST'])
    @limiter.limit('20 per day')
    @login_required
    def challenges_create():
        data = json_body()
        if set(data) != {'recipient_public_id', 'song_hash', 'difficulty', 'rule_version'}:
            return fail('invalid_challenge_request')
        recipient = user_by_public_id(data.get('recipient_public_id'))
        sender = current_username()
        if not recipient or recipient.get('username') == sender:
            return fail('user_not_found', 404)
        recipient_name = recipient.get('username')
        if blocked_between(sender, recipient_name):
            return fail('user_not_found', 404)
        if not db.user_follows.find_one({'follower_username': sender, 'target_username': recipient_name}):
            return fail('follow_required', 403)
        song_hash = data.get('song_hash')
        difficulty = data.get('difficulty')
        song = enabled_song(song_hash)
        courses = song.get('courses') if song and isinstance(song.get('courses'), dict) else {}
        if not song or difficulty not in DIFFICULTIES or not isinstance(courses.get(difficulty), dict):
            return fail('invalid_challenge_song')
        if data.get('rule_version') != 'standard-v1':
            return fail('invalid_challenge_rules')
        now = utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if db.async_challenges.count_documents({'sender_username': sender, 'created_at': {'$gte': day_start}}) >= 20:
            return fail('daily_challenge_limit', 429)
        active_query = {
            '$or': [
                {'sender_username': sender, 'recipient_username': recipient_name},
                {'sender_username': recipient_name, 'recipient_username': sender},
            ],
            'status': {'$in': list(ACTIVE_CHALLENGE_STATES)},
            'expires_at': {'$gt': now},
        }
        if db.async_challenges.count_documents(active_query) >= 5:
            return fail('active_challenge_limit', 409)
        public_id = ensure_public_id(db.users.find_one({'username': sender}))
        expires_at = now + timedelta(days=CHALLENGE_DAYS)
        doc = {
            'challenge_id': uuid.uuid4().hex,
            'sender_username': sender,
            'recipient_username': recipient_name,
            'song_id': song.get('id'),
            'song_hash': song_hash,
            'difficulty': difficulty,
            'rule_version': 'standard-v1',
            'created_at': now,
            'expires_at': expires_at,
            'purge_at': expires_at + timedelta(days=CHALLENGE_HISTORY_DAYS),
            'status': 'pending',
            'created_by_public_id': public_id,
        }
        db.async_challenges.insert_one(doc)
        return jsonify({'status': 'ok', 'challenge': challenge_doc(doc, include_ghost=True)}), 201

    @bp.route('/challenges/<challenge_id>')
    @limiter.limit('120 per minute')
    @login_required
    def challenge_get(challenge_id):
        doc = challenge_for_user(challenge_id)
        if not doc:
            return fail('challenge_not_found', 404)
        return jsonify({'status': 'ok', 'challenge': challenge_doc(doc, include_ghost=True)})

    def bounded_int(data, name, maximum=1000000000):
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(name)
        value = int(value)
        if value < 0 or value > maximum or value != data.get(name):
            raise ValueError(name)
        return value

    @bp.route('/challenges/<challenge_id>/result', methods=['POST'])
    @limiter.limit('60 per hour')
    @login_required
    def challenge_result(challenge_id):
        challenge = challenge_for_user(challenge_id)
        if not challenge:
            return fail('challenge_not_found', 404)
        if challenge_status(challenge) not in ACTIVE_CHALLENGE_STATES:
            return fail('challenge_closed', 409)
        data = json_body()
        if set(data) != {'score', 'good', 'ok', 'bad', 'max_combo', 'drumroll', 'clear', 'ghost_payload', 'ghost_encoding'}:
            return fail('invalid_challenge_result')
        try:
            result = {
                'score': bounded_int(data, 'score'),
                'good': bounded_int(data, 'good', 1000000),
                'ok': bounded_int(data, 'ok', 1000000),
                'bad': bounded_int(data, 'bad', 1000000),
                'max_combo': bounded_int(data, 'max_combo', 1000000),
                'drumroll': bounded_int(data, 'drumroll', 10000000),
            }
        except ValueError:
            return fail('invalid_challenge_result')
        if not isinstance(data.get('clear'), bool):
            return fail('invalid_challenge_result')
        payload = data.get('ghost_payload')
        if data.get('ghost_encoding') != GHOST_ENCODING or not isinstance(payload, str):
            return fail('invalid_ghost_payload')
        try:
            canonical = decode_ghost_payload(payload, GHOST_ENCODING)
            payload = encode_ghost_payload(canonical)
        except (TypeError, ValueError):
            return fail('invalid_ghost_payload')
        judged_notes = result['good'] + result['ok'] + result['bad']
        if len(canonical.get('events', [])) != judged_notes or result['max_combo'] > result['good'] + result['ok']:
            return fail('invalid_challenge_result')
        username = current_username()
        now = utcnow()
        result.update({
            'challenge_id': challenge_id,
            'username': username,
            'clear': data['clear'],
            'ghost_payload': payload,
            'ghost_encoding': GHOST_ENCODING,
            'updated_at': now,
            'purge_at': challenge.get('purge_at'),
        })
        existing = db.async_challenge_results.find_one({'challenge_id': challenge_id, 'username': username})
        saved = existing is None or result_rank(result) > result_rank(existing)
        if saved:
            db.async_challenge_results.update_one(
                {'challenge_id': challenge_id, 'username': username},
                {'$set': result},
                upsert=True,
            )
        if username == challenge.get('recipient_username') and challenge.get('status') == 'pending':
            db.async_challenges.update_one({'_id': challenge['_id']}, {'$set': {'status': 'active'}})
            challenge['status'] = 'active'
        return jsonify({'status': 'ok', 'saved': saved, 'challenge': challenge_doc(challenge, include_ghost=True)})

    @bp.route('/challenges/<challenge_id>/decline', methods=['POST'])
    @limiter.limit('60 per hour')
    @login_required
    def challenge_decline(challenge_id):
        challenge = challenge_for_user(challenge_id)
        if not challenge or challenge.get('recipient_username') != current_username():
            return fail('challenge_not_found', 404)
        if challenge_status(challenge) != 'pending':
            return fail('challenge_not_pending', 409)
        db.async_challenges.update_one({'_id': challenge['_id']}, {'$set': {'status': 'declined'}})
        return jsonify({'status': 'ok', 'status_value': 'declined'})

    @bp.route('/challenges/<challenge_id>/cancel', methods=['POST'])
    @limiter.limit('60 per hour')
    @login_required
    def challenge_cancel(challenge_id):
        challenge = challenge_for_user(challenge_id)
        if not challenge or challenge.get('sender_username') != current_username():
            return fail('challenge_not_found', 404)
        recipient_result = db.async_challenge_results.find_one({
            'challenge_id': challenge_id,
            'username': challenge.get('recipient_username'),
        })
        if challenge_status(challenge) != 'pending' or recipient_result:
            return fail('challenge_cannot_cancel', 409)
        db.async_challenges.update_one({'_id': challenge['_id']}, {'$set': {'status': 'cancelled'}})
        return jsonify({'status': 'ok', 'status_value': 'cancelled'})

    app.register_blueprint(bp)
    return bp
