import importlib
import os
import sys
import uuid
from pathlib import Path

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    import config

    probe = MongoClient(host=config.MONGO["host"], serverSelectionTimeoutMS=1000)
    try:
        probe.admin.command("ping")
    except PyMongoError:
        pytest.skip("MongoDB is required for application integration tests")
    finally:
        probe.close()

    bootstrap_db = "taiko_codex_test_bootstrap_{}".format(uuid.uuid4().hex)
    config.MONGO = dict(config.MONGO, database=bootstrap_db)
    os.environ["TAIKO_WEB_SECRET_KEY"] = "codex-test-secret-key-0123456789abcdef"
    os.environ["TAIKO_WEB_SONGS_DIR"] = str(
        tmp_path_factory.mktemp("bootstrap-songs")
    )

    module = importlib.import_module("app")
    module.app.config.update(TESTING=True)
    module.limiter.enabled = False
    yield module

    module.client.drop_database(bootstrap_db)
    module.client.close()


@pytest.fixture
def isolated_app(app_module, tmp_path):
    database_name = "taiko_codex_test_{}".format(uuid.uuid4().hex)
    app_module.db = app_module.client[database_name]
    app_module.db.users.create_index("username", unique=True)
    app_module.db.users.create_index("username_lower", unique=True)
    app_module.db.songs.create_index("id", unique=True)
    app_module.db.weekly_challenges.create_index("challenge_id", unique=True)
    app_module.db.weekly_challenges.create_index("date_key")
    app_module.db.weekly_challenges.create_index(
        [("week_key", 1), ("canonical", 1)],
        unique=True,
        partialFilterExpression={"canonical": True},
    )
    app_module.db.weekly_challenge_scores.create_index(
        [("challenge_id", 1), ("username", 1)],
        unique=True,
        partialFilterExpression={
            "challenge_id": {"$type": "string"},
            "username": {"$type": "string"},
        },
    )
    app_module.db.site_message_reads.create_index(
        [("username", 1), ("message_id", 1)], unique=True
    )
    app_module.SONGS_DIR = tmp_path / "songs"
    app_module.SONGS_DIR.mkdir()
    app_module.NOTICE_UPLOADS_DIR = tmp_path / "notice_uploads"
    app_module.app.cache.clear()

    yield app_module

    app_module.app.cache.clear()
    app_module.client.drop_database(database_name)
