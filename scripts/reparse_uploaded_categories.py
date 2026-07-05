#!/usr/bin/env python3
import argparse
import os
import pathlib
import re
import sys
import time
from datetime import datetime

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from pymongo import MongoClient

import tjaf

try:
    import config
except ModuleNotFoundError:
    config = None


DEFAULT_CATEGORIES = (
    "08 Live Festival Mode",
    "10 Taiko Towers",
    "11 Dan Dojo",
)

PARSED_FIELDS = (
    "type",
    "title",
    "subtitle",
    "title_lang",
    "subtitle_lang",
    "courses",
    "music_type",
    "offset",
)

PRESERVED_FIELDS = (
    "enabled",
    "category_id",
    "song_type",
    "skin_id",
    "preview",
    "volume",
    "maker_id",
    "hash",
    "order",
    "created_ns",
    "uploaded_at",
    "upload_source",
    "lyrics",
    "video",
)


def take_config(name, default=None):
    if config is not None and hasattr(config, name):
        return getattr(config, name)
    return default


def mongo_config():
    mongo = take_config("MONGO", {}) or {}
    host = os.environ.get("TAIKO_WEB_MONGO_HOST") or mongo.get("host") or ["127.0.0.1:27017"]
    database = os.environ.get("TAIKO_WEB_MONGO_DATABASE") or mongo.get("database") or "taiko"
    return host, database


def parse_categories(raw):
    if not raw:
        return list(DEFAULT_CATEGORIES)
    categories = [part.strip() for part in raw.split(",") if part.strip()]
    return categories or list(DEFAULT_CATEGORIES)


def decode_tja(data):
    for encoding in ("utf-8-sig", "cp932", "shift_jis", "euc-jp", "iso-2022-jp"):
        try:
            return data.decode(encoding).replace("\r", "")
        except UnicodeDecodeError:
            pass
    raise UnicodeDecodeError("tja", data, 0, 1, "unsupported TJA encoding")


def target_category_ids(db, categories):
    ids = set()
    for category in categories:
        match = re.match(r"\s*(\d+)", category)
        if match:
            ids.add(int(match.group(1)))
            ids.add(match.group(1))

    category_docs = db.categories.find({}, {"_id": False, "id": True, "title": True, "title_lang": True})
    category_set = set(categories)
    for category in category_docs:
        titles = [category.get("title")]
        title_lang = category.get("title_lang")
        if isinstance(title_lang, dict):
            titles.extend(title_lang.values())
        if any(title in category_set for title in titles):
            category_id = category.get("id")
            if category_id is not None:
                ids.add(category_id)
                ids.add(str(category_id))
                try:
                    ids.add(int(category_id))
                except (TypeError, ValueError):
                    pass
    return ids


def build_query(categories, category_ids):
    clauses = [{"song_type": {"$in": list(categories)}}]
    if category_ids:
        clauses.append({"category_id": {"$in": list(category_ids)}})
    return {
        "type": "tja",
        "$or": clauses,
    }


def reparse_song(song, songs_dir, source):
    song_id = song.get("id")
    if song_id is None:
        return None, "missing-id"
    song_id = str(song_id)
    tja_path = songs_dir / song_id / "main.tja"
    if not tja_path.is_file():
        return None, "missing-main.tja"

    text = decode_tja(tja_path.read_bytes())
    parsed = tjaf.Tja(text).to_mongo(song_id, song.get("created_ns") or time.time_ns())

    update = {field: parsed.get(field) for field in PARSED_FIELDS}
    if parsed.get("dan_dojo"):
        update["dan_dojo"] = parsed["dan_dojo"]
    update["reparsed_at"] = datetime.utcnow()
    update["reparse_source"] = source

    for field in PRESERVED_FIELDS:
        if field in song:
            update[field] = song[field]

    unset = {}
    if "dan_dojo" in song and "dan_dojo" not in parsed:
        unset["dan_dojo"] = ""

    operation = {"$set": update}
    if unset:
        operation["$unset"] = unset
    return operation, None


def main():
    parser = argparse.ArgumentParser(description="Reparse uploaded TJA songs in selected categories.")
    parser.add_argument(
        "--categories",
        default=os.environ.get("TAIKO_WEB_UPDATE_REPARSE_CATEGORIES", ",".join(DEFAULT_CATEGORIES)),
        help="Comma-separated category titles to reparse.",
    )
    parser.add_argument(
        "--songs-dir",
        default=os.environ.get("TAIKO_WEB_SONGS_DIR", str(pathlib.Path(__file__).resolve().parents[1] / "public" / "songs")),
        help="Persistent songs directory.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without updating MongoDB.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of matching songs to inspect.")
    args = parser.parse_args()

    categories = parse_categories(args.categories)
    songs_dir = pathlib.Path(args.songs_dir).resolve()
    host, database = mongo_config()
    client = MongoClient(host=host)
    db = client[database]

    category_ids = target_category_ids(db, categories)
    query = build_query(categories, category_ids)
    cursor = db.songs.find(query).sort("id", 1)
    if args.limit > 0:
        cursor = cursor.limit(args.limit)

    scanned = 0
    updated = 0
    skipped = 0
    failed = 0
    for song in cursor:
        scanned += 1
        song_id = song.get("id")
        try:
            operation, skip_reason = reparse_song(song, songs_dir, "update.sh")
            if skip_reason:
                skipped += 1
                print(f"skip {song_id}: {skip_reason}")
                continue
            if args.dry_run:
                updated += 1
                print(f"dry-run {song_id}: {song.get('title') or ''}")
                continue
            result = db.songs.update_one({"_id": song["_id"]}, operation)
            if result.modified_count:
                updated += 1
                print(f"updated {song_id}: {operation['$set'].get('title') or ''}")
            else:
                skipped += 1
                print(f"unchanged {song_id}: {operation['$set'].get('title') or ''}")
        except Exception as error:
            failed += 1
            print(f"failed {song_id}: {error}", file=sys.stderr)

    print(
        "reparse uploaded categories complete: "
        f"scanned={scanned} updated={updated} skipped={skipped} failed={failed} "
        f"categories={','.join(categories)} songs_dir={songs_dir}"
    )
    return 1 if failed and updated == 0 and skipped == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
