"""Chart feedback and compact personal performance analytics APIs."""

from collections import Counter
from datetime import datetime
import uuid

from flask import Blueprint, jsonify, request, session


DIFFICULTIES = ('easy', 'normal', 'hard', 'oni', 'ura')
RATING_TAGS = ('sync', 'readability', 'fun', 'difficulty')
REPORT_REASONS = (
    'audio_sync', 'invalid_notes', 'display', 'metadata',
    'copyright', 'inappropriate', 'other',
)
REPORT_STATES = ('open', 'triaged', 'confirmed', 'rejected', 'resolved')
PERFORMANCE_RETENTION_DAYS = 180


def utcnow():
    return datetime.utcnow()


def iso(value):
    return value.isoformat() + 'Z' if isinstance(value, datetime) else None


def calculate_accuracy(good, ok, bad):
    total = good + ok + bad
    return round((good + ok * 0.55) / total, 6) if total else 0


def normalize_song_identity(song):
    return str(song.get('hash') or song.get('id') or song.get('title') or '')


def rating_summary(db, song_hash, difficulty):
    rows = list(db.chart_ratings.find({
        'song_hash': song_hash,
        'difficulty': difficulty,
    }))
    existing = db.chart_rating_summaries.find_one({
        'song_hash': song_hash,
        'difficulty': difficulty,
    }) or {}
    if not rows:
        db.chart_rating_summaries.delete_one({
            'song_hash': song_hash,
            'difficulty': difficulty,
        })
        return {
            'rating_count': 0,
            'rating_avg': None,
            'tag_counts': {},
            'hidden': bool(existing.get('hidden')),
        }
    tag_counts = Counter(row.get('tag') for row in rows if row.get('tag') in RATING_TAGS)
    output = {
        'song_hash': song_hash,
        'difficulty': difficulty,
        'rating_count': len(rows),
        'rating_avg': round(sum(int(row.get('stars', 0)) for row in rows) / len(rows), 2),
        'tag_counts': dict(tag_counts),
        'hidden': bool(existing.get('hidden')),
        'updated_at': utcnow(),
    }
    db.chart_rating_summaries.update_one(
        {'song_hash': song_hash, 'difficulty': difficulty},
        {'$set': output},
        upsert=True,
    )
    return output


def serialize_run(doc):
    return {
        'run_id': doc.get('run_id'),
        'song_hash': doc.get('song_hash'),
        'difficulty': doc.get('difficulty'),
        'score': int(doc.get('score', 0)),
        'good': int(doc.get('good', 0)),
        'ok': int(doc.get('ok', 0)),
        'bad': int(doc.get('bad', 0)),
        'max_combo': int(doc.get('max_combo', 0)),
        'drumroll': int(doc.get('drumroll', 0)),
        'gauge': int(doc.get('gauge', 0)),
        'accuracy': float(doc.get('accuracy', 0)),
        'buckets': doc.get('buckets') or [],
        'finished_at': iso(doc.get('finished_at')),
    }


def register_feedback_analytics_routes(
    app,
    db,
    limiter,
    csrf,
    basedir,
    login_required,
    find_enabled_song,
    schema_module,
):
    prefix = basedir.rstrip('/') + '/api'
    if not prefix.startswith('/'):
        prefix = '/' + prefix
    bp = Blueprint('feedback_analytics', __name__, url_prefix=prefix)

    def no_store(response):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    def fail(message, status=400):
        return jsonify({'status': 'error', 'message': message}), status

    def body():
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else {}

    def song_and_identity(song_hash, difficulty):
        if not isinstance(song_hash, str) or not 1 <= len(song_hash) <= 500:
            return None, None
        if difficulty not in DIFFICULTIES:
            return None, None
        song = find_enabled_song(song_hash)
        if not song or not isinstance(song.get('courses'), dict) or not song['courses'].get(difficulty):
            return None, None
        return song, normalize_song_identity(song)

    def has_eligible_run(username, song_hash, difficulty):
        return db.performance_runs.find_one({
            'username': username,
            'song_hash': song_hash,
            'difficulty': difficulty,
            'eligible': True,
        }, {'_id': True}) is not None

    @bp.before_request
    def protect_writes():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and app.config.get('WTF_CSRF_ENABLED', True):
            csrf.protect()

    @bp.after_request
    def private_dynamic_response(response):
        return no_store(response)

    @bp.route('/chart-feedback')
    @limiter.limit('120 per minute')
    def get_chart_feedback():
        song, song_hash = song_and_identity(request.args.get('hash'), request.args.get('difficulty'))
        if not song:
            return fail('song_not_found', 404)
        difficulty = request.args.get('difficulty')
        summary = db.chart_rating_summaries.find_one({
            'song_hash': song_hash,
            'difficulty': difficulty,
        }) or {}
        if summary.get('hidden'):
            public_summary = {'rating_count': 0, 'rating_avg': None, 'tag_counts': {}, 'hidden': True}
        else:
            public_summary = {
                'rating_count': int(summary.get('rating_count', 0)),
                'rating_avg': summary.get('rating_avg'),
                'tag_counts': summary.get('tag_counts') or {},
                'hidden': False,
            }
        username = session.get('username')
        own = None
        eligible = False
        if username:
            row = db.chart_ratings.find_one({
                'song_hash': song_hash,
                'difficulty': difficulty,
                'username': username,
            })
            if row:
                own = {'stars': int(row.get('stars', 0)), 'tag': row.get('tag')}
            eligible = has_eligible_run(username, song_hash, difficulty)
        return jsonify({'status': 'ok', 'summary': public_summary, 'own_rating': own, 'eligible': eligible})

    @bp.route('/chart-feedback/rating', methods=['PUT'])
    @limiter.limit('30 per hour')
    @login_required
    def put_chart_rating():
        data = body()
        if not schema_module.validate(data, schema_module.chart_rating):
            return fail('invalid_rating')
        song, song_hash = song_and_identity(data.get('song_hash'), data.get('difficulty'))
        if not song:
            return fail('song_not_found', 404)
        username = session['username']
        if not has_eligible_run(username, song_hash, data['difficulty']):
            return fail('play_required', 403)
        now = utcnow()
        existing = db.chart_ratings.find_one({
            'song_hash': song_hash,
            'difficulty': data['difficulty'],
            'username': username,
        })
        db.chart_ratings.update_one({
            'song_hash': song_hash,
            'difficulty': data['difficulty'],
            'username': username,
        }, {
            '$set': {
                'stars': data['stars'],
                'tag': data.get('tag'),
                'updated_at': now,
            },
            '$setOnInsert': {'created_at': now},
        }, upsert=True)
        summary = rating_summary(db, song_hash, data['difficulty'])
        return jsonify({'status': 'ok', 'created': not bool(existing), 'summary': {
            'rating_count': summary['rating_count'],
            'rating_avg': summary['rating_avg'],
            'tag_counts': summary['tag_counts'],
        }})

    @bp.route('/chart-feedback/rating', methods=['DELETE'])
    @limiter.limit('30 per hour')
    @login_required
    def delete_chart_rating():
        data = body()
        song, song_hash = song_and_identity(data.get('song_hash'), data.get('difficulty'))
        if not song:
            return fail('song_not_found', 404)
        db.chart_ratings.delete_one({
            'song_hash': song_hash,
            'difficulty': data['difficulty'],
            'username': session['username'],
        })
        summary = rating_summary(db, song_hash, data['difficulty'])
        return jsonify({'status': 'ok', 'summary': {
            'rating_count': summary['rating_count'],
            'rating_avg': summary['rating_avg'],
            'tag_counts': summary['tag_counts'],
        }})

    @bp.route('/chart-feedback/reports', methods=['POST'])
    @limiter.limit('10 per hour')
    @login_required
    def post_chart_report():
        data = body()
        if not schema_module.validate(data, schema_module.chart_report):
            return fail('invalid_report')
        song, song_hash = song_and_identity(data.get('song_hash'), data.get('difficulty'))
        if not song:
            return fail('song_not_found', 404)
        username = session['username']
        now = utcnow()
        query = {
            'song_hash': song_hash,
            'difficulty': data['difficulty'],
            'reporter_username': username,
            'reason': data['reason'],
            'status': {'$in': ['open', 'triaged']},
        }
        existing = db.chart_reports.find_one(query)
        if existing:
            report_id = existing.get('report_id')
            db.chart_reports.update_one({'report_id': report_id}, {'$set': {
                'position_ms': data.get('position_ms'),
                'description': data.get('description', '').strip(),
                'updated_at': now,
            }})
        else:
            report_id = uuid.uuid4().hex
            db.chart_reports.insert_one({
                'report_id': report_id,
                'song_hash': song_hash,
                'difficulty': data['difficulty'],
                'reporter_username': username,
                'reason': data['reason'],
                'position_ms': data.get('position_ms'),
                'description': data.get('description', '').strip(),
                'status': 'open',
                'priority': 0,
                'created_at': now,
                'updated_at': now,
                'resolution': None,
                'resolved_by': None,
            })
        return jsonify({'status': 'ok', 'report_id': report_id, 'created': not bool(existing)})

    @bp.route('/chart-feedback/reports/me')
    @limiter.limit('60 per minute')
    @login_required
    def get_own_chart_reports():
        rows = db.chart_reports.find({'reporter_username': session['username']}).sort('updated_at', -1).limit(100)
        return jsonify({'status': 'ok', 'reports': [{
            'report_id': row.get('report_id'),
            'song_hash': row.get('song_hash'),
            'difficulty': row.get('difficulty'),
            'reason': row.get('reason'),
            'position_ms': row.get('position_ms'),
            'description': row.get('description') or '',
            'status': row.get('status') or 'open',
            'resolution': row.get('resolution'),
            'updated_at': iso(row.get('updated_at')),
        } for row in rows]})

    @bp.route('/performance/runs', methods=['POST'])
    @limiter.limit('120 per hour')
    @login_required
    def post_performance_run():
        data = body()
        if not schema_module.validate(data, schema_module.performance_run):
            return fail('invalid_run')
        song, song_hash = song_and_identity(data.get('song_hash'), data.get('difficulty'))
        if not song:
            return fail('song_not_found', 404)
        buckets = data['buckets']
        if sum(bucket['good'] for bucket in buckets) != data['good'] or \
                sum(bucket['ok'] for bucket in buckets) != data['ok'] or \
                sum(bucket['bad'] for bucket in buckets) != data['bad']:
            return fail('invalid_bucket_totals')
        if sum(bucket['offset_count'] for bucket in buckets) > data['good'] + data['ok'] + data['bad']:
            return fail('invalid_offset_totals')
        previous_end = -1
        for bucket in buckets:
            if bucket['start_ms'] < previous_end or bucket['end_ms'] <= bucket['start_ms']:
                return fail('invalid_bucket_range')
            previous_end = bucket['end_ms']
        existing = db.performance_runs.find_one({
            'username': session['username'], 'run_id': data['run_id'],
        })
        if existing and ((existing.get('song_hash') and existing.get('song_hash') != song_hash) or
                         (existing.get('difficulty') and existing.get('difficulty') != data['difficulty'])):
            return fail('run_id_conflict', 409)
        now = utcnow()
        doc = {
            'run_id': data['run_id'],
            'username': session['username'],
            'song_hash': song_hash,
            'difficulty': data['difficulty'],
            'mode': 'standard',
            'eligible': True,
            'score': data['score'],
            'good': data['good'],
            'ok': data['ok'],
            'bad': data['bad'],
            'max_combo': data['max_combo'],
            'drumroll': data['drumroll'],
            'gauge': data['gauge'],
            'accuracy': calculate_accuracy(data['good'], data['ok'], data['bad']),
            'buckets': buckets,
            'rule_version': 'standard-v1',
            'finished_at': now,
        }
        result = db.performance_runs.update_one(
            {'username': session['username'], 'run_id': data['run_id']},
            {'$setOnInsert': doc},
            upsert=True,
        )
        stored = db.performance_runs.find_one({
            'username': session['username'],
            'run_id': data['run_id'],
        }) or doc
        return jsonify({'status': 'ok', 'created': result.upserted_id is not None, 'run': serialize_run(stored)})

    @bp.route('/performance/history')
    @limiter.limit('120 per minute')
    @login_required
    def get_performance_history():
        query = {'username': session['username'], 'eligible': True}
        song_hash = request.args.get('hash')
        difficulty = request.args.get('difficulty')
        if song_hash:
            song, canonical = song_and_identity(song_hash, difficulty)
            if not song:
                return fail('song_not_found', 404)
            query['song_hash'] = canonical
            query['difficulty'] = difficulty
        elif difficulty:
            if difficulty not in DIFFICULTIES:
                return fail('invalid_difficulty')
            query['difficulty'] = difficulty
        try:
            limit = max(1, min(int(request.args.get('limit', 60)), 100))
        except (TypeError, ValueError):
            return fail('invalid_limit')
        rows = db.performance_runs.find(query).sort('finished_at', -1).limit(limit)
        return jsonify({'status': 'ok', 'runs': [serialize_run(row) for row in rows]})

    app.register_blueprint(bp)
