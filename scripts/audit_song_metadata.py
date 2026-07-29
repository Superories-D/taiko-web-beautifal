#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import unicodedata

from pymongo import MongoClient


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HTML_TAG = re.compile(
    r"<\s*/?\s*(?:script|iframe|svg|img|object|embed|style|link|meta|[a-z][\w:-]*)\b",
    re.IGNORECASE,
)
EVENT_HANDLER = re.compile(
    r"\bon(?:error|load|click|focus|mouseover|animationstart)\s*=",
    re.IGNORECASE,
)
ACTIVE_SCHEME = re.compile(r"(?:javascript\s*:|data\s*:\s*text/html)", re.IGNORECASE)
DEFAULT_FIELDS = {
    "songs": ("title", "subtitle", "title_lang", "subtitle_lang"),
    "categories": ("title", "title_lang"),
    "makers": ("name",),
    "leaderboard": ("display_name",),
}


def inspect_text(value, max_length=500):
    reasons = []
    if HTML_TAG.search(value):
        reasons.append("html_tag")
    if EVENT_HANDLER.search(value):
        reasons.append("event_handler")
    if ACTIVE_SCHEME.search(value):
        reasons.append("active_scheme")
    if any(unicodedata.category(char) == "Cc" for char in value):
        reasons.append("control_character")
    if len(value) > max_length:
        reasons.append("long_value")
    return reasons


def safe_json(value):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True)
    return (
        encoded.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def iter_text_fields(document, fields):
    for field in fields:
        value = document.get(field)
        if isinstance(value, dict):
            for key, nested in value.items():
                if isinstance(nested, str):
                    yield "{}.{}".format(field, key), nested
        elif isinstance(value, str):
            yield field, value


def scan_database(database, max_findings=1000):
    findings = []
    counts = {}
    for collection_name, fields in DEFAULT_FIELDS.items():
        collection = database[collection_name]
        counts[collection_name] = collection.count_documents({})
        projection = {"_id": True, "id": True, "hash": True}
        projection.update({field: True for field in fields})
        for document in collection.find({}, projection):
            for field, value in iter_text_fields(document, fields):
                reasons = inspect_text(value)
                if not reasons:
                    continue
                record_id = document.get("id") or document.get("hash") or document.get("_id")
                findings.append({
                    "collection": collection_name,
                    "record_id": str(record_id)[:160],
                    "field": field,
                    "reasons": reasons,
                    "length": len(value),
                    "sha256_12": hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12],
                })
                if len(findings) >= max_findings:
                    return counts, findings, True
    return counts, findings, False


def configured_target():
    import config

    mongo = dict(getattr(config, "MONGO", {}))
    host = os.environ.get("TAIKO_WEB_MONGO_HOST") or mongo.get("host") or ["127.0.0.1:27017"]
    database = os.environ.get("TAIKO_WEB_MONGO_DATABASE") or mongo.get("database") or "taiko"
    return host, database


def main():
    parser = argparse.ArgumentParser(
        description="Read-only scan of stored song metadata. Values are never printed or modified."
    )
    parser.add_argument("--host", help="MongoDB host override")
    parser.add_argument("--database", help="MongoDB database override")
    parser.add_argument("--max-findings", type=int, default=1000)
    parser.add_argument("--timeout-ms", type=int, default=3000)
    args = parser.parse_args()

    configured_host, configured_database = configured_target()
    host = args.host or configured_host
    database_name = args.database or configured_database
    if args.max_findings < 1:
        parser.error("--max-findings must be at least 1")

    client = MongoClient(
        host=host,
        serverSelectionTimeoutMS=max(100, args.timeout_ms),
        connectTimeoutMS=max(100, args.timeout_ms),
    )
    client.admin.command("ping")
    counts, findings, truncated = scan_database(
        client[database_name],
        max_findings=args.max_findings,
    )
    print(safe_json({
        "database": database_name,
        "counts": counts,
        "suspicious_count": len(findings),
        "truncated": truncated,
    }))
    for finding in findings:
        print(safe_json(finding))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
