from __future__ import division
import os
import pathlib
import sqlite3
import re
APP_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATABASE = APP_ROOT / 'taiko.db'
SONGS_DIR = APP_ROOT / 'public' / 'songs'

def parse_osu(osu):
    with open(osu, 'r', encoding='utf-8-sig', errors='replace') as osu_file:
        osu_lines = osu_file.read().replace('\x00', '').split('\n')
    sections = {}
    current_section = None

    for line in osu_lines:
        line = line.strip()
        secm = re.match(r'^\[(\w+)\]$', line)
        if secm:
            if current_section:
                sections[current_section[0]] = current_section[1]
            current_section = (secm.group(1), [])
        else:
            if current_section:
                current_section[1].append(line)
            else:
                current_section = ('Default', [line])
    
    if current_section:
        sections[current_section[0]] = current_section[1]

    return sections


def get_osu_key(osu, section, key, default=None):
    sec = osu.get(section, [])
    for line in sec:
        if ':' not in line:
            continue
        ok, ov = (part.strip() for part in line.split(':', 1))

        if ok.lower() == key.lower():
            return ov

    return default


def get_preview(song_id, song_type):
    preview = 0
    song_dir = SONGS_DIR / str(song_id)

    if song_type == "tja":
        tja_path = song_dir / 'main.tja'
        if tja_path.is_file():
            preview = get_tja_preview(tja_path)
    else:
        if not song_dir.is_dir():
            return preview
        osus = [osu for osu in os.listdir(song_dir) if osu in ['easy.osu', 'normal.osu', 'hard.osu', 'oni.osu']]
        if osus:
            osud = parse_osu(song_dir / osus[0])
            preview = int(get_osu_key(osud, 'General', 'PreviewTime', 0))

    return preview


def get_tja_preview(tja):
    with open(tja, 'r', encoding='utf-8-sig', errors='replace') as tja_file:
        tja_lines = tja_file.read().replace('\x00', '').split('\n')
    
    for line in tja_lines:
        line = line.strip()
        if ':' in line:
            name, value = line.split(':', 1)
            if name.lower() == 'demostart':
                value = value.strip()
                try:
                    value = float(value)
                except ValueError:
                    continue
                else:
                    return int(value * 1000)
        elif line.lower() == '#start':
            break
    return 0


if __name__ == '__main__':
    with sqlite3.connect(DATABASE) as conn:
        curs = conn.cursor()
        songs = curs.execute('select id, type from songs').fetchall()
        for song in songs:
            preview = get_preview(song[0], song[1]) / 1000
            curs.execute('update songs set preview = ? where id = ?', (preview, song[0]))
