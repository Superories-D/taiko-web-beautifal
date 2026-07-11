#!/usr/bin/env python3
"""Read-only audit for legacy Weekly Challenge conflicts."""

import argparse
import json
import os
import pathlib
import sys
from collections import defaultdict
from datetime import datetime

from pymongo import MongoClient

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
import config


def derive_week_key(challenge):
    week_key = challenge.get("week_key")
    if isinstance(week_key, str) and week_key:
        return week_key
    date_key = challenge.get("date_key")
    if not isinstance(date_key, str):
        return None
    try:
        iso = datetime.strptime(date_key, "%Y-%m-%d").isocalendar()
    except ValueError:
        return None
    return "{}-W{:02d}".format(iso.year, iso.week)


def identity(document):
    return (
        document.get("challenge_id"),
        document.get("song_hash"),
        document.get("difficulty") or "oni",
    )


def audit(database):
    challenges_by_week = defaultdict(list)
    invalid_challenges = 0
    for challenge in database.weekly_challenges.find(
        {},
        {
            "challenge_id": True,
            "date_key": True,
            "week_key": True,
            "song_hash": True,
            "difficulty": True,
            "canonical": True,
        },
    ):
        week_key = derive_week_key(challenge)
        if not week_key:
            invalid_challenges += 1
            continue
        challenges_by_week[week_key].append(challenge)

    conflicts = []
    known_identities = set()
    for week_key, challenges in sorted(challenges_by_week.items()):
        identities = {identity(challenge) for challenge in challenges}
        known_identities.update(identities)
        if len(identities) > 1:
            conflicts.append(
                {
                    "week_key": week_key,
                    "challenge_count": len(challenges),
                    "distinct_identity_count": len(identities),
                    "canonical_count": sum(
                        1 for challenge in challenges if challenge.get("canonical") is True
                    ),
                }
            )

    ambiguous_scores = 0
    missing_identity_scores = 0
    for score in database.weekly_challenge_scores.find(
        {},
        {
            "challenge_id": True,
            "song_hash": True,
            "difficulty": True,
        },
    ):
        score_identity = identity(score)
        if not score_identity[0] or not score_identity[1]:
            missing_identity_scores += 1
        elif score_identity not in known_identities:
            ambiguous_scores += 1

    return {
        "mode": "read-only",
        "weeks": len(challenges_by_week),
        "challenges": sum(len(items) for items in challenges_by_week.values()),
        "conflicting_weeks": conflicts,
        "invalid_challenges": invalid_challenges,
        "scores": database.weekly_challenge_scores.count_documents({}),
        "scores_without_identity": missing_identity_scores,
        "scores_without_matching_challenge": ambiguous_scores,
        "strategy": (
            "Keep legacy documents unchanged. The application creates one canonical ISO-week "
            "challenge and scopes every new leaderboard row by challenge_id, song_hash, and difficulty."
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Report legacy Weekly Challenge conflicts without changing MongoDB."
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("TAIKO_WEB_MONGO_DATABASE")
        or config.MONGO.get("database")
        or "taiko",
    )
    args = parser.parse_args()

    host = os.environ.get("TAIKO_WEB_MONGO_HOST") or config.MONGO.get("host")
    client = MongoClient(host=host, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
        report = audit(client[args.database])
    finally:
        client.close()
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))


if __name__ == "__main__":
    main()
