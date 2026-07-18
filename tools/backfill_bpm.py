"""Idempotently backfill BPM ranges for songs already in MongoDB.

Run from the project root after the application has been configured.  The
script only writes ``bpm_min``/``bpm_max`` and leaves songs whose chart cannot
be parsed untouched (their values remain null/missing).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tjaf import Tja


def _read_chart(path: Path) -> str | None:
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return None


def backfill(db, songs_dir: Path, dry_run: bool = False) -> tuple[int, int]:
    scanned = updated = 0
    for song in db.songs.find({}, {"id": 1, "bpm_min": 1, "bpm_max": 1}):
        scanned += 1
        chart = songs_dir / str(song.get("id")) / "main.tja"
        text = _read_chart(chart)
        if not text:
            continue
        parsed = Tja(text)
        if not parsed.bpm_values:
            continue
        minimum, maximum = min(parsed.bpm_values), max(parsed.bpm_values)
        if song.get("bpm_min") == minimum and song.get("bpm_max") == maximum:
            continue
        updated += 1
        if not dry_run:
            db.songs.update_one(
                {"_id": song["_id"]},
                {"$set": {"bpm_min": minimum, "bpm_max": maximum}},
            )
    return scanned, updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = parser.parse_args()

    # Importing app applies the normal configuration and database connection.
    import app

    scanned, updated = backfill(app.db, app.SONGS_DIR, args.dry_run)
    mode = "would update" if args.dry_run else "updated"
    print(f"scanned {scanned} songs; {mode} {updated} BPM ranges")


if __name__ == "__main__":
    main()
