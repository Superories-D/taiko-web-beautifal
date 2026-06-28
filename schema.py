import jsonschema

def validate(data, schema):
    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.exceptions.ValidationError:
        return False

register = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'username': {'type': 'string'},
        'password': {'type': 'string'}
    }
}

login = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'username': {'type': 'string'},
        'password': {'type': 'string'},
        'remember': {'type': 'boolean'}
    }
}

update_display_name = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'display_name': {'type': 'string'}
    }
}

update_don = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'body_fill': {'type': 'string'},
        'face_fill': {'type': 'string'}
    }
}

update_password = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'current_password': {'type': 'string'},
        'new_password': {'type': 'string'}
    }
}

delete_account = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'password': {'type': 'string'}
    }
}

scores_save = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'scores': {
            'type': 'array',
            'maxItems': 10000,
            'items': {'$ref': '#/definitions/score'}
        },
        'is_import': {'type': 'boolean'}
    },
    'required': ['scores'],
    'additionalProperties': False,
    'definitions': {
        'score': {
            'type': 'object',
            'properties': {
                'hash': {'type': 'string', 'minLength': 1, 'maxLength': 500},
                'score': {'type': 'string', 'maxLength': 100000}
            },
            'required': ['hash', 'score'],
            'additionalProperties': False
        }
    }
}

playcount_record = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'hash': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'difficulty': {'type': 'string', 'minLength': 1, 'maxLength': 32},
        'score': {'type': 'number', 'minimum': 0, 'maximum': 1000000000},
        'is_auto': {'type': 'boolean'}
    },
    'required': ['hash', 'difficulty', 'score', 'is_auto'],
    'additionalProperties': False
}

visit_record = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'visitor_id': {'type': 'string'}
    }
}

weekly_challenge_submit = {
    '$schema': 'http://json-schema.org/schema#',
    'type': 'object',
    'properties': {
        'challenge_id': {'type': 'string'},
        'hash': {'type': 'string'},
        'song_hash': {'type': 'string'},
        'difficulty': {'type': 'string'},
        'score': {'type': 'number'},
        'good': {'type': 'number'},
        'ok': {'type': 'number'},
        'bad': {'type': 'number'},
        'max_combo': {'type': 'number'},
        'drumroll': {'type': 'number'}
    },
    'required': ['challenge_id', 'difficulty', 'score']
}
