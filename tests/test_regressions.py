from datetime import datetime
import shutil
import subprocess

import bcrypt
import pytest


def add_song(module, song_id, *, files=True, title=None):
    song = {
        "id": song_id,
        "enabled": True,
        "title": title or "Song {}".format(song_id),
        "hash": "song-hash-{}".format(song_id),
        "type": "tja",
        "music_type": "ogg",
        "preview": 0,
        "volume": 1,
        "song_type": "01 Pop",
        "courses": {"oni": {"stars": 5, "branch": False}},
    }
    module.db.songs.insert_one(song)
    if files:
        song_dir = module.SONGS_DIR / str(song_id)
        song_dir.mkdir()
        (song_dir / "main.tja").write_text(
            "TITLE:Test\n#START\n1000,\n#END\n", encoding="utf-8"
        )
        (song_dir / "main.ogg").write_bytes(b"OggS")
    return song


def csrf_token(client):
    return client.get("/api/csrftoken").get_json()["token"]


def register(client, username="test_user", password="secret123"):
    token = csrf_token(client)
    response = client.post(
        "/api/register",
        json={"username": username, "password": password},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    return token


def test_privileged_config_is_not_shared_with_anonymous_users(
    isolated_app, monkeypatch
):
    module = isolated_app
    monkeypatch.setattr(
        module.config,
        "GOOGLE_CREDENTIALS",
        {
            "gdrive_enabled": True,
            "api_key": "private-test-key",
            "oauth_client_id": "private-test-client",
            "project_number": "42",
            "min_level": 50,
        },
    )
    module.db.users.insert_one(
        {
            "username": "admin",
            "username_lower": "admin",
            "password": bcrypt.hashpw(b"password", bcrypt.gensalt()),
            "user_level": 100,
            "session_id": "admin-session",
        }
    )

    with module.app.test_client() as admin:
        with admin.session_transaction() as session:
            session["username"] = "admin"
            session["session_id"] = "admin-session"
        privileged = admin.get("/api/config")

    with module.app.test_client() as anonymous:
        public = anonymous.get("/api/config")

    assert privileged.get_json()["google_credentials"]["api_key"] == "private-test-key"
    assert public.get_json()["google_credentials"] == {"gdrive_enabled": False}
    assert public.headers["Cache-Control"] == "private, no-store"


def test_public_song_surfaces_ignore_missing_storage(isolated_app):
    module = isolated_app
    add_song(module, 1, files=True)
    add_song(module, 2, files=False)

    with module.app.test_client() as client:
        songs = client.get("/api/songs").get_json()

    assert [song["id"] for song in songs] == [1]
    stats = module.get_admin_overview_stats()
    assert stats["enabled_song_count"] == 2
    assert stats["playable_song_count"] == 1
    assert stats["missing_song_file_count"] == 1
    assert module.find_enabled_song_by_identity("song-hash-2") is None


def test_weekly_challenge_is_stable_for_the_entire_week(isolated_app):
    module = isolated_app
    add_song(module, 1)
    add_song(module, 2)

    monday = datetime(2026, 7, 6, 1, 0, 0)
    sunday = datetime(2026, 7, 12, 23, 59, 59)
    next_monday = datetime(2026, 7, 13, 0, 0, 0)

    first = module.current_weekly_challenge(monday)
    same_week = module.current_weekly_challenge(sunday)
    following = module.current_weekly_challenge(next_monday)

    assert first["_id"] == same_week["_id"]
    assert first["challenge_id"] == "2026-W28"
    assert first["date_key"] == "2026-07-06"
    assert following["challenge_id"] == "2026-W29"
    assert module.db.weekly_challenges.count_documents({}) == 2


def test_account_mutations_require_csrf_and_cleanup_reads(isolated_app):
    module = isolated_app
    with module.app.test_client() as client:
        rejected = client.post(
            "/api/register",
            json={"username": "test_user", "password": "secret123"},
        )
        assert rejected.status_code == 400
        assert rejected.get_json()["message"] == "invalid_csrf"

        token = register(client)
        module.db.site_message_reads.insert_one(
            {"username": "test_user", "message_id": "message-1"}
        )
        module.db.play_records.insert_one({"username": "test_user", "song_hash": "x"})
        module.db.visit_records.insert_one(
            {"username": "test_user", "visitor_key": "user:test_user"}
        )
        module.db.board_posts.insert_one(
            {
                "username": "test_user",
                "user_display_name": "Test User",
                "message": "hello",
            }
        )
        removed = client.post(
            "/api/account/remove",
            json={"password": "secret123"},
            headers={"X-CSRFToken": token},
        )

    assert removed.get_json()["status"] == "ok"
    assert module.db.users.find_one({"username": "test_user"}) is None
    assert module.db.site_message_reads.find_one({"username": "test_user"}) is None
    assert module.db.play_records.find_one({})["username"] is None
    visit = module.db.visit_records.find_one({})
    assert visit["username"] is None
    assert visit["visitor_key"].startswith("deleted:")
    board_post = module.db.board_posts.find_one({})
    assert board_post["username"] is None
    assert "user_display_name" not in board_post


def test_preview_paths_fail_cleanly_and_use_generation_route(isolated_app):
    module = isolated_app
    add_song(module, 1, files=True)
    add_song(module, 2, files=False)

    with module.app.test_client() as client:
        missing = client.get("/api/preview?id=2")
        generated_route = client.get("/songs/1/preview.mp3")
        no_preview_offset = client.get("/api/preview?id=1")
        private_file = client.get("/songs/1/.upload-state")

    assert missing.status_code == 404
    assert generated_route.status_code == 302
    assert "/api/preview?id=1" in generated_route.headers["Location"]
    assert no_preview_offset.status_code == 302
    assert no_preview_offset.headers["Location"].endswith("/songs/1/main.ogg")
    assert private_file.status_code == 404


def test_weekly_score_schema_rejects_unbounded_numbers(isolated_app):
    module = isolated_app
    add_song(module, 1)

    with module.app.test_client() as client:
        token = register(client)
        challenge = client.get("/api/weekly-challenge/current").get_json()[
            "challenge"
        ]
        response = client.post(
            "/api/weekly-challenge/submit",
            json={
                "challenge_id": challenge["challenge_id"],
                "song_hash": challenge["song_hash"],
                "difficulty": challenge["difficulty"],
                "score": 10**100,
            },
            headers={"X-CSRFToken": token},
        )

    assert response.status_code == 400


def test_ffmpeg_preview_generation_is_atomic(isolated_app):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is not installed")
    module = isolated_app
    add_song(module, 1, files=True)
    source = module.SONGS_DIR / "1" / "main.ogg"
    subprocess.run(
        [
            ffmpeg,
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "libvorbis",
            "-y",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    result = module.make_preview(1, "tja", "ogg", 0.1)
    preview = module.SONGS_DIR / "1" / "preview.mp3"
    assert result == str(preview)
    assert preview.is_file() and preview.stat().st_size > 0
    assert list(preview.parent.glob(".preview-*.mp3")) == []
