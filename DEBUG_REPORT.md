# Deep Debug Report: roll-challenge4

## Scope

This audit covered Flask APIs, MongoDB/Redis configuration, account and admin
flows, regular and weekly leaderboards, score import, announcements, uploads,
TJA parsing, preview generation, frontend state/network handling, loader
workers, subdirectory deployment, SEO URLs, static assets, shell scripts, and
the Taiko editor. Multiplayer/WebSocket code was intentionally left unchanged:
the feature is disabled by product decision.

## Findings And Fixes

| Area | Root cause | Fix |
| --- | --- | --- |
| Weekly Challenge | A UTC `date_key` selected a new song every day while the score identity used an ISO `week_key`, mixing different songs in one weekly board. | Current challenge creation, lookup, seed, submission and leaderboard scope now use a UTC ISO week. The deterministic seed is `weekly-challenge:<week_key>`, and the canonical `challenge_id` is the week key. |
| Weekly concurrency/history | First access used a non-atomic create path; legacy daily documents could be ambiguous. | Mongo `find_one_and_update(..., upsert=True)` plus duplicate-key retry creates one canonical challenge. Historical legacy weeks select one exact challenge deterministically without merging incompatible scores. `scripts/audit_weekly_data.py` is read-only and reports conflicts before any manual migration. |
| Weekly validation | The client could submit a stale ID or a song/course differing from the active challenge. | The server verifies current week, challenge ID, song hash, difficulty, enabled storage, and the actual course. Scores are keyed by challenge plus user and only a higher valid score overwrites an older score. |
| Stored XSS | Leaderboard titles and display names were assembled into `innerHTML`. | `leaderboard.js` now builds DOM nodes and uses `textContent`; browser regression submits an XSS payload and verifies it cannot create an element or execute. |
| CSRF and privileged upload | State-changing API coverage was incomplete and `/api/upload` did not require a durable privileged identity. | Unsafe requests are CSRF-protected by default. High-privilege upload requires an authenticated administrator or a constant-time checked Bearer upload token, with rate, size, extension, signature, filename and path validation. |
| Config cache disclosure | Identity-dependent configuration could be cached across users. | `/api/config` is not cached, emits `Cache-Control: no-store` and `Vary: Cookie`, and only returns Google credentials to a sufficiently privileged admin. |
| Session and response hardening | Cookie/security policy was implicit. | Session cookies are HttpOnly and Lax; Secure is environment-controlled. Normal responses receive nosniff, frame, referrer and permissions headers; sensitive endpoints are no-store. |
| Score import consistency | Import deleted old scores before new writes had succeeded. | All input is validated and upserted first; obsolete rows are removed only after successful writes. Failure preserves the old dataset. |
| Mongo identity/sequence data | Username casing and song sequence allocation had race and legacy-data failure modes. | Case-normalized user lookup/backfill and partial unique indexes are added defensively. Sequence allocation uses atomic `$inc` with malformed legacy-value repair and non-fatal index creation warnings. |
| Account/announcement cleanup | Account deletion left related rows; announcement files could outlive failed database writes or be deleted outside their directory. | Account-related data is deleted or anonymized by retention role. Announcement image writes use staging and rollback; only validated local notice-upload paths are removed. |
| Missing song files | Enabled database songs whose local storage was absent reached the public API and caused runtime 404s. | Public APIs and song file routes require enabled, available storage and an actual course. Admin overview exposes playable versus missing counts. |
| Frontend state/networking | Indexes could become invalid after filter/sort, random selection could loop forever, and many fetches treated a resolved promise as success. | Selection is normalized and bounded; random selection chooses from a finite candidate list. Leaderboard, stats, upload, account, score and weekly calls validate response/status/content, abort on timeout and preserve usable old state on failure. |
| Subdirectory/SEO/cache | Several client URLs assumed `/`; SEO links trusted host-derived values; changed assets could retain old cached logic. | URLs respect normalized `basedir`; site origin is configured and validated rather than read from Host. Asset versioning and `cache_flush_urls.txt` cover modified frontend resources. |
| Loader/preview/filesystem paths | Worker timeout ended before fallback body reads; preview generation used shared temporary names and relative paths assumed the current working directory. | The worker timeout spans full response reads and retries safely. Preview output uses per-run staging, fsync/atomic replace and cleanup. Application/tools use paths rooted at `Path(__file__)`. |
| Update deployment | `rsync --delete` did not preserve a generated Flask secret or filesystem-session fallback; `update.sh` also never switches a Git branch by design. | Source sync now excludes `.taiko-secret-key` and `flask_session`. Documentation requires an explicit fetch/switch/fast-forward pull to `roll-challenge4` before `update.sh` is run. |
| TJA/admin form validation | Upload and editor parsing accepted inconsistent encodings/content and server validation trusted too much client form state. | TJA supports BOM, CRLF/LF, Shift-JIS/CP932, comments, numeric/text courses and subtitle prefixes. Uploads validate content, WAVE safety, audio signatures and bounds; admin song forms validate types, references, ranges, hashes and files server-side. |
| Editor dependencies | Editor modules mixed PyQt and PySide imports. | The editor consistently uses PyQt5, its parser handles BOM, and an offscreen GUI smoke test succeeds. |
| Tracked credentials/cache | A tracked bootstrap file contained an active administrator credential and a tracked filesystem session cache was modified at runtime. | `.admin_bootstrap.json` is removed and ignored. The tracked session cache is removed from Git while preserving local runtime behavior; session/cache paths are ignored. The historical administrator credential must be rotated because removing a file does not erase Git history. |

## Changed Files

* Backend/configuration: `.gitignore`, `app.py`, `schema.py`, `tjaf.py`,
  `config.py`, `config.example.py`, `docker-compose.yml`, `setup.sh`,
  `README.md`, `cache_flush_urls.txt`, `public/manifest.json`.
* Templates/admin: `templates/index.html`, `templates/board.html`,
  `templates/admin.html`, `templates/admin_login.html`,
  `templates/admin_overview.html`, `templates/admin_song_detail.html`,
  `templates/admin_song_new.html`, `templates/admin_songs.html`.
* Browser UI: `public/src/js/customsongs.js`, `leaderboard.js`,
  `loader-worker.js`, `loader.js`, `loadsong.js`, `playstats.js`,
  `scoresheet.js`, `scorestorage.js`, `search.js`, `songselect.js`,
  `uploadmodal.js`, `weeklychallenge.js`, `public/upload/upload.js`,
  `public/src/views/weekly_challenge.html`, `public/src/css/admin.css`,
  `main.css`, and `search.css`.
* Tools/scripts: `tools/generate_previews.py`, `tools/migrate_db.py`,
  `tools/set_previews.py`, `tools/taikodb_hash.py`,
  `scripts/reparse_uploaded_categories.py`, and new
  `scripts/audit_weekly_data.py`.
* Editor: `taiko-editor/diagnostic.py`, `editor_pygame.py`,
  `editor_window.py`, `requirements.txt`, `tja_parser.py`, and widgets
  `course_tabs.py`, `metadata_panel.py`, `note_palette.py`, `properties.py`.
* Tests/report: new `tests/conftest.py`, `tests/test_regressions.py`,
  `tests/test_weekly_challenge.py`, `tests/test_security_and_uploads.py`,
  `tests/test_data_and_frontend.py`, `tests/browser_regression.js`, and this
  `DEBUG_REPORT.md`.
* Removed from version control: `.admin_bootstrap.json` and
  `flask_session/2029240f6d1128be89ddc32729463129` (the latter remains a local
  ignored runtime file rather than being deleted).

## Database Compatibility And Migration

No production collection was deleted or rewritten by this change. The new
canonical challenge stores `week_key`, ISO-week `challenge_id`, Monday
`date_key` for compatibility, and exact song/difficulty fields. Existing daily
documents and their scores remain intact. Current-week boards accept only the
canonical current challenge; historic conflict weeks are read as one exact,
deterministically selected challenge, never as an implicit merge.

Before deployment, run `python scripts/audit_weekly_data.py` against a database
copy or with production read-only credentials. It reports legacy conflicts and
missing keys without modifying data. Resolve reported historical conflicts
explicitly if a different archival policy is desired. Index creation is
best-effort so duplicate legacy `username_lower`, sequence, or hash data does
not prevent startup; warnings identify data that needs manual cleanup.

## Added Regression Coverage

The test suite covers ISO week stability/cross-year boundaries/concurrent
creation, rejected weekly mismatches and stale submissions, historical boards,
score overwrite rules, CSRF and authorization, XSS-safe rendering, config
secrecy, import failure preservation, category ID `0`, course existence,
account and announcement cleanup, malformed/oversized audio and TJA uploads,
Shift-JIS TJA, atomic sequence repair, Redis/basedir/SEO normalization, static
asset references, frontend index/random/loader guards, previews and editor
parser behavior, and update preservation of local secret/session files.
`tests/browser_regression.js` exercises desktop and mobile UI,
XSS, admin login, and both root and `/taiko/` deployment modes.

## Verification Results

| Check | Result |
| --- | --- |
| `pytest -q` | Passed: 35 tests. |
| `python -m compileall app.py schema.py tjaf.py tools scripts taiko-editor` | Passed. |
| `node --check` for every `public/**/*.js` and browser regression script | Passed. |
| `ruff check . --select E9,F63,F7,F82` | Passed. |
| `bandit -r app.py schema.py tjaf.py tools scripts -ll` | Passed: no issues, 4,251 lines scanned. |
| `pip-audit -r requirements.txt` | Passed: no known vulnerabilities. |
| `bash -n setup.sh update.sh tools/get_version.sh tools/setup.sh` | Passed with Git Bash. |
| `TAIKO_WEB_UPDATE_DRY_RUN=1 bash update.sh --skip-backup` | Passed. |
| Compose YAML parse | Passed: `app`, `mongo`, `redis`. |
| Playwright, root deployment | Passed: desktop 1440x900 and mobile 390x844, 230 available songs, no captured frontend errors. |
| Playwright, `/taiko/` deployment | Passed with the same checks and no root-path API regressions. |
| Taiko editor | PyQt5 offscreen GUI smoke test passed at 1400x820. |

## Not Run Or Remaining Risk

Docker CLI is not installed on this machine, so `docker compose config` and a
containerized Mongo/Redis integration run were not possible; YAML was parsed as
a substitute. Real production Redis, proxy/CDN behavior, replica-set
transactions, external Google APIs and production migration data were not used.
The read-only audit tool must be reviewed before any historical-data policy is
applied. WebSocket/multiplayer remains deliberately disabled and was not
modified or enabled.

## Deployment Notes

Set a strong `TAIKO_WEB_SECRET_KEY`, `TAIKO_WEB_SITE_ORIGIN`, and (when
applicable) normalized `TAIKO_WEB_BASEDIR`. In HTTPS production set
`TAIKO_WEB_SESSION_COOKIE_SECURE=1`. Configure Mongo/Redis through their
environment settings; prefer a complete `REDIS_URI` over separate fields. If
machine upload is required, set a long random `TAIKO_WEB_UPLOAD_TOKEN` and
rotate it independently. Rotate the previously committed administrator
credential immediately. Do not commit `.env`, bootstrap credentials, tokens,
or session/cache files.

Deploy the backend and purge the paths listed in `cache_flush_urls.txt` through
the CDN, especially changed `src/js`, `src/css`, weekly view, manifest and index
resources. The new frontend asset version is `20260711.1` unless overridden by
`TAIKO_WEB_ASSET_VERSION`.

When updating from `roll-challenge2`, explicitly fetch, switch, and
fast-forward-pull `roll-challenge4` in the source checkout before running
`update.sh`; the update script intentionally synchronizes its current source
directory and does not alter Git branches itself.
