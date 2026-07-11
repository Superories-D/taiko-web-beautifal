import jsonschema

def validate(data, schema):
    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.exceptions.ValidationError:
        return False

register = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'username': {'type': 'string', 'minLength': 3, 'maxLength': 20},
        'password': {'type': 'string', 'minLength': 6, 'maxLength': 72}
    },
    'required': ['username', 'password'],
    'additionalProperties': False
}

login = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'username': {'type': 'string', 'minLength': 1, 'maxLength': 20},
        'password': {'type': 'string', 'minLength': 1, 'maxLength': 5000},
        'remember': {'type': 'boolean'}
    },
    'required': ['username', 'password'],
    'additionalProperties': False
}

update_display_name = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'display_name': {'type': 'string', 'maxLength': 25}
    },
    'required': ['display_name'],
    'additionalProperties': False
}

update_don = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'body_fill': {'type': 'string'},
        'face_fill': {'type': 'string'}
    },
    'required': ['body_fill', 'face_fill'],
    'additionalProperties': False
}

update_password = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'current_password': {'type': 'string', 'minLength': 1, 'maxLength': 5000},
        'new_password': {'type': 'string', 'minLength': 6, 'maxLength': 72}
    },
    'required': ['current_password', 'new_password'],
    'additionalProperties': False
}

delete_account = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'password': {'type': 'string', 'minLength': 1, 'maxLength': 5000}
    },
    'required': ['password'],
    'additionalProperties': False
}

scores_save = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
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
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'hash': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'difficulty': {'type': 'string', 'minLength': 1, 'maxLength': 32},
        'score': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000},
        'is_auto': {'type': 'boolean'}
    },
    'required': ['hash', 'difficulty', 'score', 'is_auto'],
    'additionalProperties': False
}

visit_record = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'visitor_id': {'type': 'string', 'maxLength': 128}
    },
    'additionalProperties': False
}

weekly_challenge_submit = {
    '$schema': 'http://json-schema.org/draft-07/schema#',
    'type': 'object',
    'properties': {
        'challenge_id': {'type': 'string', 'minLength': 1, 'maxLength': 32},
        'hash': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'song_hash': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'difficulty': {'type': 'string', 'minLength': 1, 'maxLength': 32},
        'score': {'type': 'integer', 'minimum': 0, 'maximum': 1000000000},
        'good': {'type': 'integer', 'minimum': 0, 'maximum': 10000000},
        'ok': {'type': 'integer', 'minimum': 0, 'maximum': 10000000},
        'bad': {'type': 'integer', 'minimum': 0, 'maximum': 10000000},
        'max_combo': {'type': 'integer', 'minimum': 0, 'maximum': 10000000},
        'drumroll': {'type': 'integer', 'minimum': 0, 'maximum': 10000000}
    },
    'required': ['challenge_id', 'difficulty', 'score'],
    'anyOf': [
        {'required': ['hash']},
        {'required': ['song_hash']}
    ],
    'additionalProperties': False
}
