#!/usr/bin/env python3
# .ogg preview generator for use when app and songs are on two different machines

import argparse
import requests
import os
import pathlib
import re
import uuid
from ffmpy import FFmpeg


parser = argparse.ArgumentParser(description='Generate song previews.')
parser.add_argument('site', help='Instance URL, eg. https://taiko.bui.pm')
parser.add_argument('song_dir', help='Path to songs directory, eg. /srv/taiko/public/taiko/songs')
parser.add_argument('--overwrite', action='store_true', help='Overwrite existing previews')
args = parser.parse_args()


if __name__ == '__main__':
    response = requests.get('{}/api/songs'.format(args.site), timeout=30)
    response.raise_for_status()
    songs = response.json()
    song_root = pathlib.Path(args.song_dir).resolve()
    for i, song in enumerate(songs):
        print('{}/{} {} (id: {})'.format(i + 1, len(songs), song['title'], song['id']))

        song_id = str(song.get('id', ''))
        if not re.fullmatch(r'(?:[0-9]{1,9}|[a-f0-9]{64}-[a-f0-9]{64})', song_id):
            print('Skipping invalid song id')
            continue
        song_dir = (song_root / song_id).resolve()
        if song_dir.parent != song_root:
            print('Skipping unsafe song path')
            continue
        song_path = song_dir / 'main.{}'.format(song.get('music_type') or 'mp3')
        prev_path = song_dir / 'preview.ogg'

        if song_path.is_file():
            if not prev_path.is_file() or args.overwrite:
                if not song['preview'] or song['preview'] <= 0:
                    print('Skipping due to no preview')
                    continue

                print('Making preview.ogg')
                temp_path = song_dir / '.preview-{}.ogg'.format(uuid.uuid4().hex)
                try:
                    ff = FFmpeg(
                        inputs={str(song_path): '-ss %s' % song['preview']},
                        outputs={str(temp_path): '-codec:a libvorbis -b:a 64k -ar 32000 -y -loglevel panic'}
                    )
                    ff.run()
                    os.replace(temp_path, prev_path)
                finally:
                    temp_path.unlink(missing_ok=True)
            else:
                print('Preview already exists')
        else:
            print('song file not found')
