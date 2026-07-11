import io
from pathlib import Path

import bcrypt
import pytest
from pymongo.collection import Collection
from pymongo.errors import PyMongoError


def csrf_token(client):
    return client.get("/api/csrftoken").get_json()["token"]


def register(client, username="upload_user"):
    token = csrf_token(client)
    response = client.post(
        "/api/register",
        json={"username": username, "password": "secret123"},
        headers={"X-CSRFToken": token},
    )
    assert response.get_json()["status"] == "ok"
    return token


def add_song(module, song_id=1):
    song = {
        "id": song_id,
        "enabled": True,
        "title": "Course Test",
        "hash": "course-test-hash",
        "type": "tja",
        "music_type": "ogg",
        "courses": {"oni": {"stars": 5, "branch": False}},
    }
    module.db.songs.insert_one(song)
    song_dir = module.SONGS_DIR / str(song_id)
    song_dir.mkdir()
    (song_dir / "main.tja").write_text(
        "TITLE:Test\nWAVE:main.ogg\nCOURSE:3\nLEVEL:5\n#START\n1000,\n#END\n",
        encoding="utf-8",
    )
    (song_dir / "main.ogg").write_bytes(b"OggS")
    return song


def upload_song(client, tja, music, music_name="song.ogg"):
    return client.post(
        "/api/user-upload",
        data={
            "song_type": "12 Custom",
            "file_tja": (io.BytesIO(tja), "chart.tja"),
            "file_music": (io.BytesIO(music), music_name),
        },
        headers={"X-CSRFToken": csrf_token(client)},
        content_type="multipart/form-data",
    )


def valid_tja(title="Upload Test", wave="song.ogg", level="5"):
    return (
        "TITLE:{}\nWAVE:{}\nCOURSE:3\nLEVEL:{}\n#START\n1000,\n#END\n".format(
            title, wave, level
        )
    )


def test_public_api_upload_accepts_anonymous_requests_without_csrf(isolated_app):
    module = isolated_app
    with module.app.test_client() as client:
        response = client.post("/api/upload")
    assert response.status_code == 400
    assert response.get_json()["error"] == "missing_files"


def test_regular_user_cannot_open_admin_pages(isolated_app):
    module = isolated_app
    with module.app.test_client() as client:
        register(client)
        assert client.get("/admin/overview").status_code == 403


@pytest.mark.parametrize(
    "tja,music,music_name,error",
    [
        (valid_tja().encode(), b"not-an-ogg", "song.ogg", "invalid_music_file"),
        (valid_tja(wave="song.mp3").encode(), b"not-an-mp3", "song.mp3", "invalid_music_file"),
        (b"", b"OggSdata", "song.ogg", "empty_file"),
        (b"TITLE:X\nWAVE:song.ogg\nCOURSE:3\nLEVEL:5\n", b"OggSdata", "song.ogg", "missing_tja_start"),
        (b"TITLE:X\nWAVE:song.ogg\nCOURSE:3\nLEVEL:5\n#START\n1000,\n", b"OggSdata", "song.ogg", "missing_tja_end"),
        (valid_tja(level="11").encode(), b"OggSdata", "song.ogg", "invalid_tja_level"),
        (valid_tja(wave="../song.ogg").encode(), b"OggSdata", "song.ogg", "unsafe_tja_wave"),
    ],
)
def test_upload_validation_rejects_invalid_content(
    isolated_app, tja, music, music_name, error
):
    with isolated_app.app.test_client() as client:
        response = upload_song(client, tja, music, music_name)
    assert response.status_code == 400
    assert response.get_json()["error"] == error
    assert isolated_app.db.songs.count_documents({}) == 0


def test_upload_size_limit_is_enforced(isolated_app, monkeypatch):
    module = isolated_app
    monkeypatch.setattr(module, "UPLOAD_MUSIC_MAX_BYTES", 8)
    with module.app.test_client() as client:
        response = upload_song(client, valid_tja().encode(), b"OggS12345")
    assert response.status_code == 400
    assert response.get_json()["error"] == "music_too_large"


def test_shift_jis_tja_upload_is_normalized_to_utf8(isolated_app):
    module = isolated_app
    title = "\u30c6\u30b9\u30c8"
    tja = valid_tja(title=title).encode("cp932")
    with module.app.test_client() as client:
        response = upload_song(client, tja, b"OggSvalid")

    assert response.status_code == 201
    song_id = response.get_json()["id"]
    assert module.db.songs.find_one({"id": song_id})["title"] == title
    stored = (module.SONGS_DIR / song_id / "main.tja").read_text(encoding="utf-8")
    assert title in stored


def test_score_import_failure_preserves_existing_scores(
    isolated_app, monkeypatch
):
    module = isolated_app
    original_bulk_write = Collection.bulk_write

    def fail_score_write(collection, *args, **kwargs):
        if collection.name == "scores":
            raise PyMongoError("simulated write failure")
        return original_bulk_write(collection, *args, **kwargs)

    monkeypatch.setattr(Collection, "bulk_write", fail_score_write)
    with module.app.test_client() as client:
        token = register(client, username="score_user")
        module.db.scores.insert_one(
            {"username": "score_user", "hash": "old", "score": "old-score"}
        )
        response = client.post(
            "/api/scores/save",
            json={
                "scores": [{"hash": "new", "score": "new-score"}],
                "is_import": True,
            },
            headers={"X-CSRFToken": token},
        )

    assert response.status_code == 503
    assert module.db.scores.count_documents({"username": "score_user"}) == 1
    assert module.db.scores.find_one({"username": "score_user"})["hash"] == "old"


def test_invalid_course_is_rejected_by_play_and_leaderboard(isolated_app):
    module = isolated_app
    song = add_song(module)
    with module.app.test_client() as client:
        token = csrf_token(client)
        play = client.post(
            "/api/playcount/record",
            json={
                "hash": song["hash"],
                "difficulty": "hard",
                "score": 100,
                "is_auto": False,
            },
            headers={"X-CSRFToken": token},
        )
        board = client.post(
            "/api/leaderboard/submit",
            json={
                "hash": song["hash"],
                "difficulty": "hard",
                "score": 100,
                "display_name": "Player",
            },
            headers={"X-CSRFToken": token},
        )

    assert play.status_code == 400
    assert board.status_code == 400
    assert module.db.play_records.count_documents({}) == 0
    assert module.db.leaderboard.count_documents({}) == 0


def test_site_message_image_rolls_back_when_database_insert_fails(
    isolated_app, monkeypatch
):
    module = isolated_app
    module.db.users.insert_one(
        {
            "username": "admin",
            "username_lower": "admin",
            "password": bcrypt.hashpw(b"password", bcrypt.gensalt()),
            "display_name": "Admin",
            "user_level": 100,
            "session_id": "admin-session",
        }
    )
    original_insert = Collection.insert_one

    def fail_message_insert(collection, *args, **kwargs):
        if collection.name == "site_messages":
            raise PyMongoError("simulated insert failure")
        return original_insert(collection, *args, **kwargs)

    monkeypatch.setattr(Collection, "insert_one", fail_message_insert)
    with module.app.test_client() as client:
        token = csrf_token(client)
        with client.session_transaction() as session:
            session["username"] = "admin"
            session["session_id"] = "admin-session"
        response = client.post(
            "/admin/messages",
            data={
                "csrf_token": token,
                "title": "Notice",
                "body": "Body",
                "active": "on",
                "image_file": (
                    io.BytesIO(b"\x89PNG\r\n\x1a\nminimal"),
                    "notice.png",
                ),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    assert not module.NOTICE_UPLOADS_DIR.exists() or not list(
        module.NOTICE_UPLOADS_DIR.iterdir()
    )


def test_leaderboard_dom_uses_text_nodes_for_untrusted_values():
    source = (
        Path(__file__).resolve().parents[1]
        / "public"
        / "src"
        / "js"
        / "leaderboard.js"
    ).read_text(encoding="utf-8")
    assert "name.textContent = String(entry.display_name" in source
    assert "${entry.display_name}" not in source
    assert "escapeHtml" not in source
