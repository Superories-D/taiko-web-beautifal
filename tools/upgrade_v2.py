#!/usr/bin/env python3
"""Idempotent compatibility upgrades for the UX/leaderboard release."""

from datetime import datetime
import time

from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError

import os
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


def mongo_hosts():
    mongo = dict(config.MONGO)
    host = os.environ.get("TAIKO_WEB_MONGO_HOST")
    if host:
        return [host]
    return mongo["host"]


client = MongoClient(mongo_hosts())
db = client[config.MONGO["database"]]


def wait_for_mongo(attempts=60):
    last_error = None
    for _ in range(attempts):
        try:
            client.admin.command("ping")
            return
        except PyMongoError as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError("MongoDB did not become ready") from last_error


def ensure_indexes():
    db.users.create_index("username", unique=True)
    db.songs.create_index("id", unique=True)
    db.songs.create_index("song_type")
    db.scores.create_index("username")
    db.play_records.create_index("song_hash")
    db.play_records.create_index("played_at")
    db.leaderboard.create_index([("song_hash", 1), ("difficulty", 1), ("score_value", -1)])
    db.leaderboard.create_index("username")
    db.leaderboard.create_index([
        ("song_hash", 1),
        ("difficulty", 1),
        ("period", 1),
        ("period_key", 1),
        ("identity_key", 1),
    ])
    db.leaderboard.create_index([
        ("song_hash", 1),
        ("difficulty", 1),
        ("period", 1),
        ("period_key", 1),
        ("score_value", -1),
    ])


def legacy_identity(score):
    if score.get("username"):
        return "user:%s" % score["username"]
    if score.get("anonymous_id"):
        return "anon:%s" % score["anonymous_id"]
    if score.get("identity_key"):
        return score["identity_key"]
    return "legacy:%s" % str(score["_id"])


def backfill_leaderboard_periods():
    now = datetime.utcnow()
    operations = []
    for score in db.leaderboard.find({"period": {"$exists": False}}):
        period_key = score.get("month") or now.strftime("%Y-%m")
        operations.append(UpdateOne({"_id": score["_id"]}, {"$set": {
            "period": "monthly",
            "period_key": period_key,
            "identity_key": legacy_identity(score),
            "updated_at": score.get("created_at") or now,
        }}))
        if len(operations) >= 500:
            db.leaderboard.bulk_write(operations, ordered=False)
            operations = []
    if operations:
        db.leaderboard.bulk_write(operations, ordered=False)


def trim_monthly_leaderboards():
    groups = db.leaderboard.aggregate([
        {"$match": {"period": "monthly"}},
        {"$group": {
            "_id": {
                "song_hash": "$song_hash",
                "difficulty": "$difficulty",
                "period_key": "$period_key",
            }
        }},
    ])
    for group in groups:
        query = {
            "song_hash": group["_id"]["song_hash"],
            "difficulty": group["_id"]["difficulty"],
            "period": "monthly",
            "period_key": group["_id"]["period_key"],
        }
        extra = list(db.leaderboard.find(query).sort("score_value", -1).skip(100))
        if extra:
            db.leaderboard.delete_many({"_id": {"$in": [item["_id"] for item in extra]}})


def ensure_song_type_field():
    # Older deployments may not have the later song_type field. Keep the app usable
    # without guessing a genre by marking missing values as Pop, the first supported type.
    db.songs.update_many(
        {"$or": [{"song_type": {"$exists": False}}, {"song_type": None}, {"song_type": ""}]},
        {"$set": {"song_type": "01 Pop"}},
    )


def mark_complete():
    db.migrations.update_one(
        {"name": "ux_leaderboard_v2"},
        {"$set": {"name": "ux_leaderboard_v2", "applied_at": datetime.utcnow()}},
        upsert=True,
    )


def main():
    wait_for_mongo()
    ensure_indexes()
    backfill_leaderboard_periods()
    trim_monthly_leaderboards()
    ensure_song_type_field()
    mark_complete()
    print("upgrade_v2 migration complete")


if __name__ == "__main__":
    main()
