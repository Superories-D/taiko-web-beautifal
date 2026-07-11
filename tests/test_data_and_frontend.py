import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_category_id_zero_is_preserved(isolated_app):
    module = isolated_app
    module.db.categories.insert_one({"id": 0, "title": "Zero"})
    song = {
        "id": 1,
        "title": "Zero Category",
        "category_id": 0,
        "type": "tja",
        "music_type": "ogg",
        "courses": {"oni": {"stars": 5, "branch": False}},
    }
    serialized = module.serialize_public_song(song, module.get_public_song_context())
    assert serialized["category_id"] == 0
    assert serialized["category"] == "Zero"


def test_admin_form_preserves_zero_reference(isolated_app):
    module = isolated_app
    module.db.categories.insert_one({"id": 0, "title": "Zero"})
    form = {
        "enabled": "",
        "title": "Admin Song",
        "course_oni": "5",
        "category_id": "0",
        "skin_id": "",
        "maker_id": "",
        "type": "tja",
        "music_type": "ogg",
        "offset": "0",
        "preview": "0",
        "volume": "1",
        "hash": "admin-song-hash",
    }
    with module.app.test_request_context(method="POST", data=form):
        output, errors = module.build_admin_song_form(1)
    assert errors == []
    assert output["category_id"] == 0
    assert output["offset"] == 0
    assert output["preview"] == 0


def test_malformed_sequence_is_repaired_and_allocated_atomically(isolated_app):
    module = isolated_app
    module.db.songs.insert_one({"id": 8, "title": "Existing"})
    module.db.seq.insert_one({"name": "songs", "value": "broken"})

    with ThreadPoolExecutor(max_workers=10) as executor:
        values = list(executor.map(lambda _: module.allocate_sequence_value("songs"), range(20)))

    assert sorted(values) == list(range(9, 29))
    assert module.db.seq.find_one({"name": "songs"})["value"] == 28


def test_basedir_resource_urls_redis_uri_and_seo_origin(
    isolated_app, monkeypatch
):
    module = isolated_app
    assert module.normalize_basedir("/taiko//game/") == "/taiko/game/"
    for invalid in ("https://host/taiko", "/taiko?x=1", "/../taiko"):
        try:
            module.normalize_basedir(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid BASEDIR accepted: {}".format(invalid))

    uri = module.redis_uri_from_config(
        {
            "CACHE_REDIS_HOST": "2001:db8::1",
            "CACHE_REDIS_PORT": 6380,
            "CACHE_REDIS_PASSWORD": "p@:/#",
            "CACHE_REDIS_DB": 4,
        }
    )
    assert uri == "redis://:p%40%3A%2F%23@[2001:db8::1]:6380/4"

    monkeypatch.setattr(module, "basedir", "/taiko/")
    monkeypatch.setattr(module, "site_origin", "https://canonical.example")
    with module.app.test_request_context("/taiko/en", base_url="http://poison.invalid"):
        config = module.get_config()
        seo = module.get_seo_meta("en")
    assert config["assets_baseurl"] == "/taiko/assets/"
    assert config["songs_baseurl"] == "/taiko/songs/"
    assert seo["canonical_url"] == "https://canonical.example/taiko/en"
    assert "poison.invalid" not in seo["canonical_url"]


def test_assets_manifest_references_existing_files():
    source = (ROOT / "public" / "src" / "js" / "assets.js").read_text(
        encoding="utf-8"
    )
    blocks = {
        "js": ROOT / "public" / "src" / "js",
        "css": ROOT / "public" / "src" / "css",
        "img": ROOT / "public" / "assets" / "img",
        "audioSfx": ROOT / "public" / "assets" / "audio",
        "audioSfxLR": ROOT / "public" / "assets" / "audio",
        "audioSfxLoud": ROOT / "public" / "assets" / "audio",
        "audioMusic": ROOT / "public" / "assets" / "audio",
        "views": ROOT / "public" / "src" / "views",
    }
    missing = []
    for name, directory in blocks.items():
        match = re.search(r'"{}"\s*:\s*\[(.*?)\]'.format(name), source, re.S)
        assert match, "missing assets block {}".format(name)
        for filename in re.findall(r'"([^"]+)"', match.group(1)):
            if not (directory / filename).is_file():
                missing.append(str(directory / filename))

    object_blocks = {
        "fonts": ROOT / "public" / "assets" / "fonts",
        "cssBackground": ROOT / "public" / "assets" / "img",
    }
    for name, directory in object_blocks.items():
        match = re.search(r'"{}"\s*:\s*\{{(.*?)\}}'.format(name), source, re.S)
        assert match
        for filename in re.findall(r':\s*"([^"]+)"', match.group(1)):
            if not (directory / filename).is_file():
                missing.append(str(directory / filename))
    assert missing == []


def test_frontend_random_index_network_and_loader_guards_are_present():
    songselect = (ROOT / "public" / "src" / "js" / "songselect.js").read_text(
        encoding="utf-8"
    )
    assert "Number.isInteger(songIdx)" in songselect
    assert ".filter(candidate => this.isPlayableSong(candidate.song))" in songselect
    random_block = songselect[songselect.index('currentSong.action === "random"'):]
    random_block = random_block[: random_block.index('currentSong.action === "search"')]
    assert "while" not in random_block

    playstats = (ROOT / "public" / "src" / "js" / "playstats.js").read_text(
        encoding="utf-8"
    )
    assert "if (!response.ok)" in playstats
    assert "data.status !== 'ok'" in playstats

    worker = (ROOT / "public" / "src" / "js" / "loader-worker.js").read_text(
        encoding="utf-8"
    )
    fallback = worker[worker.index("if(!response.body || !response.body.getReader)") :]
    fallback = fallback[: fallback.index("var reader = response.body.getReader()")]
    assert "clearRequestTimeout()" not in fallback
    assert "RESOURCE_EMPTY" in worker


def test_update_sync_preserves_local_secret_and_file_sessions():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "--exclude '.taiko-secret-key'" in setup
    assert "--exclude 'flask_session'" in setup


def test_tjaf_and_editor_parser_handle_numeric_multi_course_and_prefixes():
    import tjaf

    text = (
        "\ufeffTITLE:Parser // comment\r\n"
        "SUBTITLE:--Sub\r\nWAVE:main.ogg\r\n"
        "COURSE:0\r\nLEVEL:2\r\n#START\r\n1000,\r\n#END\r\n"
        "COURSE:Oni\r\nLEVEL:7\r\n#START\r\n1000,\r\n#END\r\n"
    )
    parsed = tjaf.Tja(text)
    assert parsed.title == "Parser"
    assert parsed.subtitle == "Sub"
    assert parsed.courses["easy"]["stars"] == 2
    assert parsed.courses["oni"]["stars"] == 7

    editor_dir = ROOT / "taiko-editor"
    sys.path.insert(0, str(editor_dir))
    try:
        from tja_parser import parse_tja, serialize_tja

        song = parse_tja(text)
        reparsed = parse_tja(serialize_tja(song))
    finally:
        sys.path.remove(str(editor_dir))
    assert reparsed.title == "Parser"
    assert set(reparsed.courses) == {"easy", "oni"}
