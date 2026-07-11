from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import bcrypt


def add_song(module, song_id, title=None):
    song = {
        "id": song_id,
        "enabled": True,
        "title": title or "Song {}".format(song_id),
        "hash": "weekly-hash-{}".format(song_id),
        "type": "tja",
        "music_type": "ogg",
        "preview": 0,
        "volume": 1,
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


def csrf_token(client):
    return client.get("/api/csrftoken").get_json()["token"]


def register(client, module, username="weekly_user"):
    token = csrf_token(client)
    response = client.post(
        "/api/register",
        json={"username": username, "password": "secret123"},
        headers={"X-CSRFToken": token},
    )
    assert response.get_json()["status"] == "ok"
    return token


def submit(client, token, challenge, score, **overrides):
    payload = {
        "challenge_id": challenge["challenge_id"],
        "song_hash": challenge["song_hash"],
        "difficulty": challenge["difficulty"],
        "score": score,
        "good": 10,
        "ok": 1,
        "bad": 0,
        "max_combo": 11,
        "drumroll": 2,
    }
    payload.update(overrides)
    return client.post(
        "/api/weekly-challenge/submit",
        json=payload,
        headers={"X-CSRFToken": token},
    )


def test_iso_week_stability_cross_week_and_year_boundary(isolated_app):
    module = isolated_app
    add_song(module, 1)
    add_song(module, 2)

    monday = module.current_weekly_challenge(datetime(2020, 12, 28, 0, 0))
    sunday = module.current_weekly_challenge(datetime(2021, 1, 3, 23, 59, 59))
    next_monday = module.current_weekly_challenge(datetime(2021, 1, 4, 0, 0))

    assert monday["_id"] == sunday["_id"]
    assert monday["challenge_id"] == "2020-W53"
    assert next_monday["challenge_id"] == "2021-W01"
    assert next_monday["_id"] != monday["_id"]


def test_concurrent_first_access_creates_one_canonical_challenge(isolated_app):
    module = isolated_app
    add_song(module, 1)
    add_song(module, 2)
    now = datetime(2026, 7, 6, 12, 0)

    with ThreadPoolExecutor(max_workers=12) as executor:
        challenges = list(
            executor.map(lambda _: module.current_weekly_challenge(now), range(24))
        )

    assert len({challenge["_id"] for challenge in challenges}) == 1
    assert module.db.weekly_challenges.count_documents(
        {"week_key": "2026-W28", "canonical": True}
    ) == 1


def test_invalid_and_old_challenge_submissions_are_rejected(
    isolated_app, monkeypatch
):
    module = isolated_app
    add_song(module, 1)
    fixed_now = datetime(2026, 7, 8, 12, 0)
    monkeypatch.setattr(module, "utc_now", lambda: fixed_now)

    with module.app.test_client() as client:
        token = register(client, module)
        challenge = client.get("/api/weekly-challenge/current").get_json()[
            "challenge"
        ]

        cases = [
            {"challenge_id": "2026-W27"},
            {"song_hash": "another-song"},
            {"difficulty": "hard"},
        ]
        for override in cases:
            response = submit(client, token, challenge, 100, **override)
            assert response.get_json() == {
                "status": "error",
                "message": "challenge_not_active",
            }

    assert module.db.weekly_challenge_scores.count_documents({}) == 0


def test_score_only_updates_when_higher(isolated_app, monkeypatch):
    module = isolated_app
    add_song(module, 1)
    monkeypatch.setattr(module, "utc_now", lambda: datetime(2026, 7, 8, 12, 0))

    with module.app.test_client() as client:
        token = register(client, module)
        challenge = client.get("/api/weekly-challenge/current").get_json()[
            "challenge"
        ]
        assert submit(client, token, challenge, 500).get_json()["status"] == "ok"
        assert submit(client, token, challenge, 300).get_json()["status"] == "ok"
        stored = module.db.weekly_challenge_scores.find_one({})
        assert stored["score_value"] == 500
        assert submit(client, token, challenge, 800).get_json()["status"] == "ok"

    assert module.db.weekly_challenge_scores.count_documents({}) == 1
    assert module.db.weekly_challenge_scores.find_one({})["score_value"] == 800


def test_historical_board_is_scoped_to_one_legacy_challenge(
    isolated_app, monkeypatch
):
    module = isolated_app
    song = add_song(module, 1)
    fixed_now = datetime(2026, 7, 8, 12, 0)
    monkeypatch.setattr(module, "utc_now", lambda: fixed_now)
    previous_start = module.week_start_for(fixed_now) - timedelta(weeks=1)
    previous_key = module.week_key_for(previous_start)

    first = {
        "challenge_id": "legacy-first",
        "date_key": previous_start.strftime("%Y-%m-%d"),
        "week_key": previous_key,
        "week_start": previous_start,
        "song_id": song["id"],
        "song_hash": song["hash"],
        "difficulty": "oni",
    }
    second = dict(
        first,
        challenge_id="legacy-second",
        date_key=(previous_start + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    module.db.weekly_challenges.insert_many([first, second])
    module.db.weekly_challenge_scores.insert_many(
        [
            {
                "challenge_id": "legacy-first",
                "week_key": previous_key,
                "username": "first",
                "display_name": "First",
                "song_hash": song["hash"],
                "difficulty": "oni",
                "score_value": 100,
                "updated_at": fixed_now,
            },
            {
                "challenge_id": "legacy-second",
                "week_key": previous_key,
                "username": "second-a",
                "display_name": "Second A",
                "song_hash": song["hash"],
                "difficulty": "oni",
                "score_value": 200,
                "updated_at": fixed_now,
            },
            {
                "challenge_id": "legacy-second",
                "week_key": previous_key,
                "username": "second-b",
                "display_name": "Second B",
                "song_hash": song["hash"],
                "difficulty": "oni",
                "score_value": 150,
                "updated_at": fixed_now,
            },
        ]
    )

    with module.app.test_client() as client:
        data = client.get("/api/weekly-challenge/leaderboards").get_json()

    assert data["previous"]["challenge_id"] == "legacy-second"
    assert [entry["display_name"] for entry in data["previous"]["leaderboard"]] == [
        "Second A",
        "Second B",
    ]
