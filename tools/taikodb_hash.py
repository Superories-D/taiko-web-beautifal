import os
import sys
import hashlib
import base64
import sqlite3

def update_hash(file_hash, filename):
    with open(filename, "rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            file_hash.update(chunk)

def get_hashes(root):
    hashes = {}
    diffs = ["easy", "normal", "hard", "oni", "ura"]
    for directory in os.listdir(root):
        dir_path = os.path.join(root, directory)
        if directory.isdigit() and os.path.isdir(dir_path):
            files = os.listdir(dir_path)
            file_hash = hashlib.md5(usedforsecurity=False)
            if "main.tja" in files:
                update_hash(file_hash, os.path.join(dir_path, "main.tja"))
            else:
                for diff in diffs:
                    if diff + ".osu" in files:
                        update_hash(file_hash, os.path.join(dir_path, diff + ".osu"))
            hashes[directory] = base64.b64encode(file_hash.digest())[:-2]
    return hashes

def write_db(database, songs):
    db = sqlite3.connect(database)
    hashes = get_hashes(songs)
    added = 0
    for song_id, song_hash in hashes.items():
        added += 1
        cur = db.cursor()
        cur.execute(
            "update songs set hash = ? where id = ?",
            (song_hash.decode(), int(song_id))
        )
        cur.close()
    db.commit()
    db.close()
    if added:
        print("{0} hashes have been added to the database.".format(added))
    else:
        print("Error: No songs were found in the given directory.")

if len(sys.argv) >= 3:
    write_db(sys.argv[1], sys.argv[2])
else:
    print("Usage: taikodb_hash.py ../taiko.db ../public/songs")
