
# Taiko Web Beautifal 项目上下文

> 面向后续 AI/开发者的项目说明与路径索引。本文档基于 2026-07-16 工作区实际代码整理；路径均相对于项目根目录，行号是当前快照的参考位置，代码变动后应以函数名和路径为准。

## 0. 给其他 AI 的阅读顺序

1. 先读本文件，再读与任务直接相关的路径。
2. 后端路由、数据结构和安全行为以 app.py、schema.py、multiplayer.py 为准。
3. 前端加载顺序以 public/src/js/assets.js、public/src/js/loader.js、templates/index.html 为准。
4. 部署行为以 docker-compose.yml、Dockerfile、gunicorn.conf.py、setup.sh 为准；README.md 和 PLAN.md 中有部分历史/分支上下文，不能单独当作现状。
5. 修改前先看 git status，保留用户已有改动；不要提交、打印或复制密钥、密码、Session、MongoDB 数据和运行时歌曲文件。

## 1. 项目概览与当前快照

| 项目 | 实际情况 |
|---|---|
| 项目类型 | Flask 3 后端 + 原生 JavaScript/CSS/HTML 前端的浏览器太鼓节奏游戏；MongoDB 持久化，Redis 用于 Session/缓存/限流 |
| 项目入口 | app.py，导出 Flask 对象 app；生产入口为 app:app |
| 前端入口 | templates/index.html 加载基础脚本，public/src/js/main.js 创建 Loader 并启动游戏 |
| 当前 Git | 本次开发分支 ai2；HEAD d279c53（Fix AI and ghost battle pause layers）；远端 origin 为 https://github.com/Superories-D/taiko-web-beautifal.git |
| 当前未跟踪文件 | PROJECT.md、one_second_test.ogg、one_second_test.tja 及本地 flask_session 文件；它们属于本地文档/测试素材/运行时 Session，不应误加入核心源码提交 |
| 运行时数据 | public/songs/ 当前为本地运行数据，.gitignore 忽略；当前约 230 个歌曲目录，每个目录通常为 main.tja + main.ogg/main.mp3 |
| 版本展示 | templates/index.html 当前显示 vLightNova 2.1.0；version.json 被忽略，通常由 tools/get_version.sh 或 Git hooks 生成 |
| 语言 | Python、JavaScript、HTML、CSS、Bash；独立编辑器还使用 PySide/PyQt 与 pygame |

### 当前代码中需要特别注意的事实

- config.py 是本地配置，默认 SECRET_KEY = 'change-me' 只是占位值；app.py 会优先使用有效的 TAIKO_WEB_SECRET_KEY，否则生成/读取 .taiko-secret-key。
- .admin_bootstrap.json 含有管理员引导信息，属于敏感文件；本说明不复述其中的用户名/密码，其他 AI 不应把它们写入日志、回复、Commit 或新文档。
- 多个源文件中的中文字符串已经出现编码错乱（典型表现为 澶紦 等）；修改文案前只改目标范围，避免对整个文件做未经验证的编码转换。
- tools/supervisor.conf、tools/nginx.conf 仍保留旧架构痕迹（例如引用仓库不存在的 server.py、旧的 /p2 本地服务）；当前多人选择逻辑在 app.py + multiplayer.py，真正 WebSocket 服务由外部多人节点提供。
- taiko-editor/requirements.txt 写的是 PySide6，但 taiko-editor/main.py、editor_window.py 实际导入 PyQt5；启动编辑器前应先确认采用哪套 GUI 实现。
- /upload/、/upload/<path>、/api/user-upload、/api/upload 在 app.py 中没有拼接 BASEDIR，如果部署在子目录，需要单独检查这些绝对路径。

## 2. 功能总览：功能 → 实现路径 → 数据/接口

| 功能 | 主要实现路径 | 相关数据/接口 |
|---|---|---|
| 首页、启动、SEO、多语言 | app.py:1878-1916；templates/index.html；public/src/js/main.js；public/src/js/loader.js | /、/<lang_code>、/sitemap.xml、/robots.txt；语言 ja/en/cn/tw/ko |
| 资源加载、失败重试、离线恢复 | public/src/js/loader.js、loader-worker.js、assets.js | 静态 JS/CSS/View/图片/音频；API 保持主线程，静态资源可由 Worker 并发拉取 |
| 标题画面 | public/src/js/titlescreen.js、public/src/views/titlescreen.html、public/src/css/titlescreen.css、logo.js | Loader.changePage('titlescreen') |
| 歌曲选择、分类、难度、排序 | public/src/js/songselect.js、public/src/views/songselect.html、public/src/css/main.css、topsongs.js | GET /api/songs、GET /api/categories、GET /api/songs/top10；分类在 app.py:125-157 |
| 歌曲搜索 | public/src/js/search.js、public/src/views/search.html、public/src/css/search.css | 前端模糊搜索/筛选；使用 fuzzysort.js，搜索历史写入 localStorage |
| 谱面与歌曲加载 | public/src/js/loadsong.js、parsetja.js、parseosu.js、abstractfile.js | 支持 TJA/OSU 解析；服务器歌曲文件由 /songs/<path> 提供 |
| 游戏主循环与判定 | public/src/js/game.js、gamerules.js、controller.js、mekadon.js、circle.js | Don/Ka、大音符、连打、气球、分支、良/可/不可、连击、魂条 |
| 键盘、手柄、触屏输入 | public/src/js/keyboard.js、gamepad.js、gameinput.js、public/src/views/game.html | 键盘/浏览器 Gamepad API/触屏太鼓；controller.js 汇总输入与游戏状态 |
| 音频、音效、延迟校准 | public/src/js/soundbuffer.js、mekadon.js、game.js、public/src/views/settings.html | Web Audio；音乐、SFX、左右声道、延迟校准、播放速度 |
| 游戏画面、动画、背景、成绩板 | public/src/js/view.js、canvasdraw.js、canvasasset.js、canvascache.js、viewassets.js、scoresheet.js、public/src/css/game.css、songbg.css | Canvas/DOM 混合渲染；游戏背景、Don 动画、结果页、AI HUD |
| TJA/OSU 自定义歌曲导入 | public/src/js/customsongs.js、importsongs.js、parseosu.js、parsetja.js、idb.js、public/src/views/customsongs.html | 本地文件夹、拖放、Google Drive（配置开启时）；IndexedDB taiko/store |
| 网页上传歌曲 | public/src/js/uploadmodal.js、public/src/views/upload.html、public/upload/index.html、public/upload/upload.js、app.py:3720-3984 | POST /api/user-upload（仅 Custom）、POST /api/upload（允许全部分类）；TJA + OGG/MP3 |
| Easy Settings | public/src/js/easysettings.js、public/src/css/easysettings.css、public/src/views/songselect.html | localStorage.easySettings；播放速度、倍速、Doron、Abekobe、Detarame、标题排序、选曲速度、AI 难度 |
| AI Battle | public/src/js/aibattle.js、songselect.js、controller.js、game.js、gameinput.js、view.js、public/src/css/game.css | 本地确定性 RNG、5 档 AI、五回合/分段结果、响应式 HUD；与自动演奏/多人互斥；支持 Esc/Q、暂停按钮和暂停菜单 |
| 幽灵对战与训练 | public/src/js/playerlab.js、songselect.js、loadsong.js、controller.js、gameinput.js、view.js、scoresheet.js；app.py:3245-3303 | 训练分段、幽灵最佳记录、幽灵战果双栏显示；登录用户的 gzip+Base64 幽灵数据按歌曲/难度同步，30 天未使用由 MongoDB TTL 清理；支持本地暂停、重来和退出选曲 |
| 外部多人对战 | public/src/js/p2.js、session.js、songselect.js、app.py:2051-2367,2925-2986、multiplayer.py | /api/multiplayer/select 选节点，再通过 WebSocket 连接外部 ws/wss 节点 |
| 账号注册/登录/设置 | public/src/js/account.js、public/src/views/account.html、login.html、app.py:2989-3171 | users 集合；bcrypt 密码、Session、昵称、Don 颜色、改密、删号 |
| 本地成绩与云端同步 | public/src/js/scorestorage.js、account.js、loader.js、app.py:3174-3233 | localStorage.scoreStorage、scores 集合；/api/scores/save|get |
| 播放次数/热度 | public/src/js/playstats.js、songselect.js、app.py:3236-3306 | play_records、song_play_counts；/api/playcount/record|get |
| 月度排行榜 | public/src/js/leaderboard.js、scoresheet.js、app.py:3309-3416 | leaderboard 集合；当前 UTC 月、每首歌/难度取前 100 |
| Top 10 热门歌曲 | public/src/js/topsongs.js、songselect.js、app.py:619-1170,2370-2396,2898-2907 | Redis/Mongo 缓存、top_song_cache；后台可手动刷新 |
| 每周挑战 | public/src/js/weeklychallenge.js、public/src/views/weekly_challenge.html、app.py:3419-3642 | weekly_challenges、weekly_challenge_scores；按 UTC 日期确定性选有 Oni 的启用歌曲 |
| 站内公告/消息 | public/src/js/sitemessages.js、public/src/views/songselect.html、app.py:494-559,2005-2048,2399-2474 | site_messages、site_message_reads；管理员发布，用户读状态 |
| 留言板 | templates/board.html、app.py:1919-1968 | board_posts；限制敏感词、链接、长度和频率；IP 仅存 hash |
| 访问统计 | app.py:1980-2002,1009-1168 | visit_records；visitor/user key，TTL 保留约 400 天 |
| 管理后台 | templates/admin_*.html、public/src/css/admin.css、app.py:2205-2844 | 用户、歌曲、公告、多人节点、Top10；等级 50/100 权限 |
| 调试、诊断、插件、教程、关于、隐私 | public/src/js/debug.js、plugins.js、tutorial.js、about.js、public/src/views/*.html、templates/privacy.txt | 浏览器端诊断、插件 Patch API、教程/隐私页面 |
| 独立桌面谱面编辑器 | taiko-editor/main.py、editor_window.py、editor_pygame.py、models.py、tja_parser.py、widgets/* | 加载/保存 TJA、时间线编辑、BPM/事件、Undo/Redo、音频预览、上传到远端 API |

## 3. 总体架构与请求/数据流

~~~text
浏览器前端
  ├─ Loader + Web Workers ──> Flask app.py ──> MongoDB taiko
  │                                      ├─> Redis Session/cache/limits
  │                                      └─> public/songs、notice_uploads
  ├─ WebSocket ─────────────> 外部多人节点
  └─ IndexedDB/localStorage

taiko-editor ── POST /api/upload ──> Flask ──> MongoDB + 歌曲文件
~~~

### 启动顺序

1. app.py 导入 config.py，计算 SONGS_DIR、NOTICE_UPLOADS_DIR，初始化 Redis/Mongo。
2. Redis 可用时：Session 和 Flask-Caching 使用 Redis；不可用时：Session 回退到 flask_session/，缓存回退 SimpleCache，限流回退进程内内存。
3. 应用启动时创建/校验 Mongo 索引，包含用户、歌曲、成绩、播放记录、排行榜、公告、访问记录、周挑战、多人节点等集合。
4. templates/index.html 先加载 assets.js、strings.js、pageevents.js、loader.js，随后 main.js 创建 Loader。
5. Loader 首先请求 src/views/loader.html 与 /api/config，然后按阶段加载静态 JS/CSS/图片/音频和歌曲列表，最后进入标题页。
6. API 请求默认留在主线程以保持 Cookie/Session/CSRF 稳定；静态资源和歌曲资源可交给 loader-worker.js 并发下载。

## 4. 本地开发、测试和部署

### 4.1 本地开发（Windows/通用 Python）

~~~powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
# 若不存在 config.py：复制 config.example.py 后按环境修改；不要覆盖已有本地配置
python app.py 34801 -b localhost
~~~

也可使用：

~~~bash
flask --app app run --port 5000
gunicorn -c gunicorn.conf.py app:app
~~~

后端启动需要可连接的 MongoDB；Redis 不可用时应用有回退逻辑，但生产环境仍应使用 Redis。app.py 直接运行默认监听 localhost:34801，Gunicorn 配置默认监听 0.0.0.0:80。

### 4.2 Docker Compose

~~~bash
docker compose up -d --build
docker compose logs -f app
~~~

入口：docker-compose.yml、Dockerfile。当前镜像版本/行为：Python 3.13.2-slim、Mongo 7.0、Redis 7-alpine、应用容器端口 80。默认持久化根目录为 /srv/taiko-web-data，可由 TAIKO_WEB_DATA_DIR 覆盖；挂载 songs、notice_uploads、mongo、redis。

### 4.3 Linux 安装/更新脚本

主脚本为 setup.sh，需要 root。命令入口在 setup.sh:1082-1166：

| 命令 | 行为 |
|---|---|
| sudo bash setup.sh install | 首次容器部署，建立 /srv/taiko-web 和 /srv/taiko-web-data，安装/启动 Mongo、Redis、应用 |
| sudo bash setup.sh update | 安全更新：暂停应用写入、先备份 MongoDB，再同步代码并重启 |
| sudo bash setup.sh backup-db | 一致性优先备份 MongoDB |
| sudo bash setup.sh restore-db PATH | 从备份恢复，需显式确认 |
| sudo bash setup.sh repair | 修复容器、环境和权限，不删除数据 |
| sudo bash setup.sh reset-db | 破坏性清空 MongoDB，必须输入完整确认字符串 |
| sudo bash setup.sh deploy-direct | 旧/直装 systemd 模式 |
| sudo bash setup.sh upgrade-direct | 直装模式升级 |
| sudo bash setup.sh uninstall | 删除应用目录，保留持久化数据目录 |

update.sh 自动检测 container/direct 模式并转调 setup.sh upgrade-container 或 upgrade-direct；可用 TAIKO_WEB_UPDATE_MODE 强制模式，用 TAIKO_WEB_UPDATE_DRY_RUN=1 只打印动作。数据库安全约定见 MONGODB_SAFETY.md：正常安装/更新不得 docker compose down -v 或删除 Mongo 数据目录。

### 4.4 相关部署文件

- gunicorn.conf.py：gthread worker；环境变量控制 bind、workers、threads、timeout、keepalive、max requests。
- tools/nginx.conf、tools/nginx_subdir.conf：旧 Nginx 反代/静态文件示例，包含旧的 /p2 端口逻辑，使用前先确认与当前外部多人节点架构一致。
- tools/supervisor.conf：旧 Supervisor 配置，taiko_app 指向 34801，taiko_server 指向不存在的 server.py，不能直接视为当前部署方案。
- .devcontainer/devcontainer.json：目前只有空的 postCreateCommand，没有自动安装依赖。

## 5. 配置与环境变量

### config.py / config.example.py

| 配置项 | 默认/用途 |
|---|---|
| BASEDIR | /，应用 URL 根目录 |
| ASSETS_BASEURL | /assets/ |
| SONGS_BASEURL | /songs/ |
| ERROR_PAGES | 自定义错误页，默认只声明 404 空值 |
| EMAIL | 关于页面展示的邮箱，可为 None |
| ACCOUNTS | 是否启用账号系统，默认 True |
| CUSTOM_JS / PLUGINS | 自定义 JS 与默认插件 |
| PREVIEW_TYPE | mp3 或 ogg，默认 mp3 |
| MONGO | Host 默认 127.0.0.1:27017，数据库默认 taiko |
| REDIS | Redis host/port/password/db 及 Flask-Caching 配置 |
| SECRET_KEY | Session 密钥的配置来源；生产不要使用 change-me |
| URL | 版本 Commit 链接的 Git 仓库基址 |
| GOOGLE_CREDENTIALS | Google Drive 集成开关、API/OAuth 信息与最低用户等级 |

### 应用运行时环境变量（读取位置：app.py）

| 变量 | 默认/作用 |
|---|---|
| TAIKO_WEB_MONGO_HOST | 覆盖 config.MONGO['host'] |
| TAIKO_WEB_REDIS_HOST / REDIS_URI | 覆盖 Redis host 或限流存储 URI |
| TAIKO_WEB_SONGS_DIR | 默认 public/songs；歌曲持久化目录 |
| TAIKO_WEB_NOTICE_UPLOADS_DIR | 默认 public/notice_uploads；公告图片目录 |
| TAIKO_WEB_SESSION_FILE_DIR | Redis 不可用时默认 flask_session |
| TAIKO_WEB_SECRET_KEY / TAIKO_WEB_SECRET_KEY_FILE | Session 密钥或密钥文件路径；有效密钥至少 32 字符 |
| TAIKO_WEB_SITE_URL | SEO 站点 origin，默认 https://taiko.asia |
| TAIKO_WEB_FEATURE_ADMIN | 默认开启管理后台 |
| TAIKO_WEB_FEATURE_SITE_MESSAGES | 默认开启站内公告 |
| TAIKO_WEB_FEATURE_TOP_SONGS | 默认开启 Top10 |
| TAIKO_WEB_UPLOAD_TJA_MAX_BYTES | 默认 2 MiB，实际限制在 64 KiB–10 MiB 之间 |
| TAIKO_WEB_UPLOAD_MUSIC_MAX_BYTES | 默认 32 MiB，实际限制在 1 MiB–128 MiB 之间 |
| TAIKO_WEB_ADMIN_STATS_MAX_TIME_MS | 管理/统计查询最大耗时，默认 2000 ms（最小 500） |
| TAIKO_WEB_TOP_SONGS_CACHE_DAYS | Top10 统计窗口，默认 1 天 |
| TAIKO_WEB_TOP_SONGS_CACHE_ROWS | Top10 缓存行数，默认 50，限制 10–200 |
| TAIKO_WEB_TOP_SONGS_REFRESH_LOCK_SECONDS | Top10 刷新锁默认 900 秒 |
| TAIKO_WEB_TOP_SONGS_SORT_MAX_TIME_MS | Top10 排序最大耗时，默认 2000 ms |
| TAIKO_WEB_TOP_SONGS_BACKFILL_MAX_TIME_MS | 播放次数回填最大耗时，默认 5000 ms |

### Gunicorn 环境变量（读取位置：gunicorn.conf.py）

TAIKO_WEB_BIND（0.0.0.0:80）、TAIKO_WEB_GUNICORN_WORKERS（默认 max(1,min(2,cpu_count))）、TAIKO_WEB_GUNICORN_THREADS（4）、TAIKO_WEB_GUNICORN_TIMEOUT（60）、TAIKO_WEB_GUNICORN_GRACEFUL_TIMEOUT（30）、TAIKO_WEB_GUNICORN_KEEPALIVE（5）、TAIKO_WEB_GUNICORN_MAX_REQUESTS（2000）、TAIKO_WEB_GUNICORN_MAX_REQUESTS_JITTER（200）。

### 部署脚本环境变量

INSTALL_DIR（默认 /srv/taiko-web）、DATA_DIR/TAIKO_WEB_DATA_DIR（默认 /srv/taiko-web-data）、BACKUP_ROOT、APP_USER/APP_GROUP、COMPOSE_PROJECT_NAME、MONGO_ROOT_USERNAME/MONGO_ROOT_PASSWORD、TAIKO_WEB_ADMIN_USERNAME/TAIKO_WEB_ADMIN_PASSWORD、TAIKO_WEB_UPDATE_MODE、TAIKO_WEB_UPDATE_DRY_RUN。管理员密码只通过环境变量或交互输入传递，不应硬编码到文档。

## 6. Flask 页面、静态资源与完整路由表

basedir 来自 config.BASEDIR；以下为当前默认 / 下的实际路由。管理 POST 通常需要 CSRF；API 错误通常返回 {'status':'error','message':...}。

### 页面与静态文件

| 方法 | 路径 | 作用 | 代码 |
|---|---|---|---|
| GET | / | 默认日文首页 | app.py:1878-1880 |
| GET | /<lang_code> | ja/en/cn/tw/ko 多语言首页；别名 301 到规范路径 | app.py:1908-1916 |
| GET | /repair | 前端修复/重新加载入口 | app.py:1970-1972、loader.js |
| GET | /board | 留言板页面 | app.py:1919-1923、templates/board.html |
| GET | /privacy | 隐私文本页 | app.py:3645-3652、templates/privacy.txt |
| GET | /sitemap.xml | 5 个语言页面与 reciprocal hreflang | app.py:1883-1888,1476-1496 |
| GET | /robots.txt | 放行首页、禁止 admin/api/upload，指向 HTTPS sitemap | app.py:1891-1905 |
| GET | /src/<path:ref> | public/src 静态文件，缓存 3600 秒 | app.py:3699-3701 |
| GET | /assets/<path:ref> | public/assets 静态文件，缓存 3600 秒 | app.py:3703-3705 |
| GET | /songs/<path:ref> | SONGS_DIR 歌曲文件，缓存 7 天 | app.py:3707-3709 |
| GET | /notice_uploads/<path:ref> | 公告图片，缓存 7 天 | app.py:3711-3713 |
| GET | /manifest.json | PWA Manifest | app.py:3715-3717、public/manifest.json |
| GET | /upload/、/upload/<path:ref> | 独立上传页静态文件，缓存 3600 秒 | app.py:3960-3963、public/upload/* |

### 公共 API

| 方法 | 路径 | 作用 | 代码 |
|---|---|---|---|
| GET | /api/config | 返回前端配置、功能开关、版本；授权用户可得到 Google credentials | app.py:2918-2922,1370-1410 |
| GET | /api/csrftoken | 返回 CSRF token | app.py:1975-1977 |
| GET | /api/songs | 返回启用歌曲；?type=<12 个 SONG_TYPES> 可过滤分类，带缓存 | app.py:2871-2895 |
| GET | /api/categories | 返回分类；没有 Custom 时补充 12 Custom | app.py:2910-2916 |
| GET | /api/preview?id=... | 生成/重定向 preview.mp3，无预览时回退主音频 | app.py:2847-2868,3655-3669 |
| POST | /api/visits/record | 记录匿名/登录访问，限 30 次/小时 | app.py:1980-2002 |
| GET | /api/board/posts | 获取留言 | app.py:1926-1929 |
| POST | /api/board/posts | 发布留言；限 10 次/分钟，过滤链接/敏感词 | app.py:1932-1968 |
| GET | /api/site-messages | 获取活动公告及当前用户未读数；功能关闭返回空数组 | app.py:2005-2025 |
| POST | /api/site-messages/<message_id>/read | 登录用户标记已读 | app.py:2028-2048 |
| GET | /api/multiplayer/select | 健康检查已启用外部多人节点并按容量/延迟选择；限 60 次/分钟 | app.py:2925-2986 |
| POST | /api/user-upload | 网页 Custom 上传；限 5 次/小时 | app.py:3965-3972 |
| POST | /api/upload | API/编辑器上传，可用全部分类 | app.py:3974-3980 |
| POST | /api/remove | 明确禁用歌曲删除，固定返回 403 | app.py:3982-3984 |

### 账号、成绩和排行 API

| 方法 | 路径 | 作用 | 代码 |
|---|---|---|---|
| POST | /api/register | 注册 3–20 位字母/数字/下划线用户名，bcrypt 密码；限 5 次/小时 | app.py:2989-3030 |
| POST | /api/login | 登录，支持 remember；限 20 次/分钟 | app.py:3033-3065 |
| POST | /api/logout | 清除当前 Session | app.py:3068-3072 |
| POST | /api/account/display_name | 修改昵称，最多 25 字符 | app.py:3075-3092 |
| POST | /api/account/don | 修改 Don 身体/脸色的 #RRGGBB | app.py:3095-3117 |
| POST | /api/account/password | 校验旧密码后改密，旋转 Session ID；限 5 次/小时 | app.py:3120-3149 |
| POST | /api/account/remove | 验证密码并清除个人数据；限 1 次/天 | app.py:3152-3171 |
| GET/POST | /api/ghost | 登录用户读取/保存 gzip 幽灵记录；按歌曲 hash+难度保存最高分，动态接口不得缓存 | app.py:3245-3303 |
| POST | /api/scores/save | 登录用户保存最多 10000 条本地成绩，可 is_import 全量替换 | app.py:3174-3205 |
| GET | /api/scores/get | 返回登录用户成绩、昵称、Don 配置 | app.py:3208-3233 |
| POST | /api/playcount/record | 记录有效歌曲游玩、难度、分数、是否自动；限 120 次/小时 | app.py:3236-3259 |
| GET | /api/playcount/get?hash=... | 返回总播放次数与本周最高非自动分数 | app.py:3262-3306 |
| POST | /api/leaderboard/submit | 提交当前 UTC 月排行榜成绩，裁剪到 Top100；限 30 次/小时 | app.py:3309-3373 |
| GET | /api/leaderboard/get?hash=...&difficulty=... | 返回当前 UTC 月 Top100 | app.py:3376-3416 |

### 周挑战 API

| 方法 | 路径 | 作用 | 代码 |
|---|---|---|---|
| GET | /api/weekly-challenge/current | 返回当天确定性挑战歌曲与 Oni 难度 | app.py:3505-3519 |
| GET | /api/weekly-challenge/leaderboards | 返回当前/上周挑战、歌曲和各自 Top100 | app.py:3522-3548 |
| POST | /api/weekly-challenge/submit | 登录用户提交；只接受当前 challenge，个人只保留更高分 | app.py:3558-3642 |

### 管理后台路由

后台入口是 /1128admin1128，需要用户等级至少 50；用户等级 100 才能创建/删除歌曲或达到最高管理能力。权限装饰器：app.py:1286-1310。

| 方法 | 路径 | 作用 | 代码/模板 |
|---|---|---|---|
| GET/POST | /1128admin1128 | 管理员登录；POST 限 10 次/分钟 | app.py:2205-2234、templates/admin_login.html |
| GET | /admin | 重定向 /admin/overview | app.py:2237-2240 |
| GET | /admin/overview | 总览、用户/歌曲/访问/Top10 统计 | app.py:2243-2249、admin_overview.html |
| GET/POST | /admin/multiplayer | 查看/新增多人节点 | app.py:2251-2289、admin_multiplayer.html |
| POST | /admin/multiplayer/<node_id>/edit | 编辑节点 URL、容量、启用状态 | app.py:2292-2315 |
| POST | /admin/multiplayer/<node_id>/test | 强制健康检查节点 | app.py:2318-2333 |
| POST | /admin/multiplayer/<node_id>/toggle | 启用/禁用节点 | app.py:2336-2351 |
| POST | /admin/multiplayer/<node_id>/remove | 删除节点配置 | app.py:2354-2367 |
| POST | /admin/top-songs/refresh | 强制刷新 Top10 缓存/回填播放计数 | app.py:2370-2396 |
| GET/POST | /admin/messages | 查看/发布站内消息，可上传 5 MiB 内图片 | app.py:2399-2449、admin_messages.html |
| POST | /admin/messages/<message_id>/remove | 删除消息及已读记录 | app.py:2452-2459 |
| POST | /admin/messages/<message_id>/toggle | 切换活动状态 | app.py:2462-2474 |
| GET | /admin/songs | 歌曲总表、分类分组 | app.py:2477-2493、admin_songs.html |
| GET/POST | /admin/songs/<song_id> | 查看/编辑多语言标题、难度、分类、音频元数据、hash 等 | app.py:2496-2631、admin_song_detail.html |
| GET/POST | /admin/songs/new | 等级 100 创建歌曲元数据 | app.py:2514-2575、admin_song_new.html |
| POST | /admin/songs/<song_id>/remove | 等级 100 删除歌曲 DB 记录；非数字上传 ID 同步删除歌曲目录 | app.py:2634-2653 |
| GET/POST | /admin/users | 搜索/分页用户；兼容旧等级编辑入口 | app.py:2656-2732、admin_users.html |
| GET | /admin/users/<username> | 账号详情、统计、最近游玩 | app.py:2735-2760、admin_user_detail.html |
| POST | /admin/users/<username>/level | 修改下属账号等级 | app.py:2763-2785 |
| POST | /admin/users/<username>/password | 重置下属密码并让其现有 Session 失效；限 10 次/小时 | app.py:2788-2819 |
| POST | /admin/users/<username>/delete | 输入完整用户名确认后删除账号与私有数据；限 10 次/天 | app.py:2822-2844 |

## 7. 前端目录与模块索引

### 7.1 加载、基础设施和资源

- public/src/js/assets.js：前端资源 manifest，列出 JS/CSS/图片/音效/页面/歌曲皮肤，并提供 CSS 背景映射。
- public/src/js/main.js：全局状态、全屏、错误记录到 localStorage.lastError、窗口尺寸、初始化 Loader。
- public/src/js/loader.js：分阶段加载、API 配置、页面切换、脚本注入、资源重试、网络状态感知、启动错误诊断。
- public/src/js/loader-worker.js：Worker 侧 fetch，支持 text/blob/arraybuffer、取消、超时、重试消息。
- public/src/js/pageevents.js：统一管理 keyboard/mouse/touch/blur/load 等事件和解绑。
- public/src/js/strings.js：多语言 UI 文案、难度/菜单/错误文本；修改界面文字优先在这里找对应 key。
- public/src/js/browsersupport.js：浏览器能力检测和不支持提示。
- public/src/js/idb.js：IndexedDB 封装，数据库名 taiko、store store。
- public/src/js/abstractfile.js：本地/远程文件抽象，供歌曲导入使用。
- public/src/js/lib/fuzzysort.js、jszip.js、md5.min.js：模糊搜索、ZIP 导入、hash；lib/oggmented-wasm.js + .wasm：Ogg 解码辅助。

### 7.2 游戏引擎、判定和渲染

- public/src/js/loadsong.js：按歌曲 ID/自定义歌曲加载谱面、音乐、背景、歌词和皮肤。
- public/src/js/parsetja.js：浏览器端完整 TJA 解析：BPM、拍号、滚速、Go-Go、分支、歌词、NextSong、音符/测量。
- public/src/js/parseosu.js：OSU Taiko 解析：General/Metadata/Difficulty/TimingPoints/HitObjects 转成内部歌曲结构。
- public/src/js/game.js：游戏循环、音频时间、当前音符、判定、连打、分支、结果、校准和自动演奏。
- public/src/js/gamerules.js：各难度判定窗口、得分、魂条和游戏规则。
- public/src/js/controller.js：连接歌曲数据、Game、View、输入、分数保存、多人/AI/自动演奏模式。
- public/src/js/gameinput.js：把键盘/手柄/触屏映射到 Don/Ka、菜单和暂停。
- public/src/js/keyboard.js、gamepad.js：具体输入设备适配。
- public/src/js/mekadon.js：鼓面输入反馈、音效、动画、即时播放与连打。
- public/src/js/circle.js：单个音符对象/状态。
- public/src/js/view.js：游戏主视图、Canvas/DOM、HUD、暂停、结果和双人画面。
- public/src/js/canvasdraw.js、canvasasset.js、canvascache.js、viewassets.js：Canvas 绘制、资源封装、缓存和游戏资源预加载。
- public/src/js/scoresheet.js：结果分数表、判定统计、皇冠/排行榜/上传分数入口。
- public/src/js/soundbuffer.js：Web Audio buffer、Gain、音量、淡入淡出和音频延迟。
- public/src/js/lyrics.js：TJA/外部歌词事件的显示。
- public/src/js/autoscore.js：自动演奏/自动得分逻辑。
- public/src/js/canvastest.js：Canvas/blur 性能检测，结果可能关闭高成本 blur。

### 7.3 歌曲选择、模式和页面

- public/src/js/songselect.js：最大前端模块；歌曲/分类选择、难度、歌曲 skin、选曲动画、排序、Top10、周挑战、公告、搜索、上传、AI、多人和进入游戏。
- public/src/js/search.js：歌曲搜索 overlay、模糊匹配、难度结果、键盘/触摸操作。
- public/src/js/topsongs.js：读取 /api/songs/top10，准备远程歌曲文件并展示热门歌曲。
- public/src/js/weeklychallenge.js：当前/上一周挑战、挑战歌曲预览、成绩板、锁定选项、SessionStorage 运行态。
- public/src/js/sitemessages.js：公告按钮、未读 badge、消息 overlay、已读 POST。
- public/src/js/easysettings.js：设置读取/清洗/兼容旧 localStorage key、UI overlay、多人/AI 冲突、排行榜资格。
- public/src/js/uploadmodal.js：选 TJA + OGG/MP3、选择歌曲类型、调用 /api/user-upload。
- public/src/js/titlescreen.js、logo.js：标题动画、开始/免责声明。
- public/src/js/settings.js：完整设置页、键位、音频、画面、语言、导入/导出和自定义歌曲入口。
- public/src/js/tutorial.js：教程页面和操作说明。
- public/src/js/about.js：关于、版本、仓库/邮箱信息。
- public/src/js/account.js：登录/注册/注销、账号设置、Don 配色、成绩同步、改密/删号。
- public/src/js/session.js：多人 Session 邀请链接、复制邀请码、连接/取消。
- public/src/js/customsongs.js：本地目录/拖放/Google Drive 入口和自定义歌曲浏览。
- public/src/js/importsongs.js：扫描 TJA/TJF/OSU、音频、songtitle.txt、genre.ini、插件和 Taiko Web assets，组合为歌曲。
- public/src/js/gpicker.js：Google Drive Picker 集成。
- public/src/js/plugins.js：.taikoweb.js 插件加载、权限/警告、动态资源和 Patch/Edit API。
- public/src/js/debug.js：调试 overlay、输入滑块、诊断数据和性能状态。
- public/src/js/p2.js：多人 WebSocket 客户端、节点选择、RTT/jitter、消息序列、同步分数、分支、皇冠和 Session 状态。
- public/src/js/aibattle.js：可被 Node require 的 AI 核心；状态权重 excellent/great/normal/poor/awful 为 0.08/0.27/0.45/0.15/0.05，并提供回合/胜负判定。
- public/src/js/playstats.js：查询/记录歌曲播放次数。
- public/src/js/leaderboard.js：读取当前歌曲/难度排行榜。
- public/src/js/scorestorage.js：本地成绩、皇冠、P2 成绩、登录后云端保存失败重试。
- public/src/js/mekadon.js、viewassets.js 等视觉模块依赖 assets.js 的资源命名，不要随意重命名静态文件。

### 7.4 前端页面模板（运行时由 Loader 注入）

public/src/views/loader.html（启动加载）、titlescreen.html（标题）、songselect.html（选曲）、game.html（游戏）、loadsong.html（歌曲加载）、search.html（搜索）、upload.html（弹窗上传）、session.html（多人 Session）、weekly_challenge.html（周挑战）、account.html（账号）、settings.html（设置）、customsongs.html（自定义歌曲）、tutorial.html（教程）、about.html（关于）、debug.html（调试）、login.html（登录）。它们由 public/src/js/assets.js 的 pages 列表和 Loader.changePage() 使用。

服务端模板另有 templates/index.html（首页壳）、templates/board.html（留言板）、templates/privacy.txt（隐私文本）以及 templates/admin.html（后台公共布局）和 templates/admin_*.html（后台各页面）。

### 7.5 CSS 文件职责

public/src/css/main.css（全局/页面/多人提示）、titlescreen.css（标题）、loader.css（启动/错误页）、loadsong.css（歌曲加载）、game.css（游戏 HUD/AI HUD/结果）、songbg.css（游戏背景和响应式）、view.css（通用 view/按钮）、search.css（搜索/上传）、easysettings.css（Easy Settings）、debug.css（调试）；后台另用 public/src/css/admin.css。

## 8. 后端 Python 模块索引

### app.py

单体 Flask 应用，职责包括：配置读取、Redis/Mongo 初始化、索引、Session/CSRF/限流、安全 Header、SEO、用户/管理员、歌曲序列化、歌曲/成绩/播放统计/排行榜/周挑战/公告/留言板/访问统计、多人节点健康检查、静态文件、预览生成、上传原子安装。关键区段：

- 1-118：导入、路径、环境变量、Secret Key。
- 121-331：功能开关、分类、Redis、限流、Mongo、SEO、Session/CSRF。
- 332-480：Mongo 索引、缓存和上传大小限制。
- 494-1234：公告、歌曲热度、Top10、访问/留言板辅助函数。
- 1247-1310：API 错误、hash、登录/管理员权限装饰器。
- 1332-1465：请求前 Session 校验、响应 Header、配置/版本/SEO。
- 1499-1875：用户、歌曲、课程、分类、管理员歌曲辅助函数。
- 1878-2060：公共页面、留言板、访问、公告 API。
- 2061-2396：多人节点管理和 Top10 刷新。
- 2399-2844：公告、歌曲、账号管理后台。
- 2847-3416：预览、歌曲、分类、配置、多人选择、账号、成绩、播放次数、排行榜 API。
- 3419-3642：周挑战。
- 3645-3717：隐私、预览、错误页、静态资源。
- 3720-3984：上传验证、原子文件安装、网页/API 上传、删除禁用。

### tjaf.py

项目内置的轻量 TJA 元数据解析器，替代外部 tjaf 依赖。Tja 读取标题、日文标题、subtitle、WAVE、OFFSET、COURSE、LEVEL、BRANCHSTART，并通过 to_mongo() 生成歌曲 Mongo 文档。它不是浏览器的完整谱面解析器；完整演奏解析在 public/src/js/parsetja.js。

### schema.py

用 jsonschema 验证 register、login、update_display_name、update_don、update_password、delete_account、scores_save、playcount_record、visit_record、weekly_challenge_submit。注意这些 schema 多数只负责类型/字段形状，业务长度、权限和数值范围还在 app.py 额外检查。

### multiplayer.py

只负责外部多人节点：规范化 ws/wss origin、拒绝本机/内网/保留 IP、DNS 解析安全校验、无重定向 /health 探测、TLS hostname 校验、连接数/容量校验，以及按容量利用率→延迟→稳定 hash 选择节点。它不实现 WebSocket 房间服务器。

## 9. MongoDB 数据模型和索引

数据库名默认 taiko。索引初始化在 app.py:384-465；以下是代码实际使用的主要字段，新增字段前先搜索读写方。

| Collection | 主要字段/用途 | 关键索引 |
|---|---|---|
| users | username、username_lower、bcrypt password、display_name、don/Don 色、user_level、session_id、创建/登录/改密时间 | username 唯一、username_lower 唯一 |
| songs | id、type、标题/副标题及 *_lang、courses、enabled、category_id/song_type、music_type、offset、skin_id、preview、volume、maker_id、hash、order、上传元数据 | id 唯一，hash、title、song_type |
| categories | 分类 id、title、多语言标题、skin、aliases | id（代码只显式查询） |
| song_skins | 歌曲/舞台/Don 背景皮肤配置 | id（代码只显式查询） |
| makers | 制作者 id/name/url | id（代码只显式查询） |
| scores | 登录用户的 username/hash/score，score 可能是前端序列化字符串 | username、username+hash |
| play_records | song_hash、difficulty、username、score、is_auto、played_at | song/time、user、time |
| song_play_counts | _id = song_hash、play_count、last_played_at，Top10/播放次数缓存 | play_count desc + last_played_at desc |
| leaderboard | song_hash、difficulty、display_name、score_value、UTC month、created_at | song+difficulty+score，含 month 版本 |
| weekly_challenges | challenge_id/date_key/week_key/week_start、song_id/song_hash、difficulty、created_at | challenge_id 唯一、date_key 唯一、week_key |
| weekly_challenge_scores | week_key/username、挑战成绩、良可不可、最大连击、连打、歌曲元数据、updated_at | week_key+username 唯一、week+score |
| ghost_records | username/song_hash/difficulty、gzip payload、points、updated_at、last_used_at | username+song_hash+difficulty 唯一；last_used_at TTL 30 天 |
| site_messages | title/body/image_url/active/created_at/created_by | active+created_at |
| site_message_reads | username/message_id/read_at | username+message_id 唯一、message_id |
| board_posts | name/message/created_at/username/user_display_name/ip_hash | username |
| visit_records | visitor_id/visitor_key/username/ip_hash/user_agent_hash/entered_at | TTL entered_at 400 天、visitor_key+entered_at |
| multiplayer_servers | node_id/name/ws_url/health_url/enabled/max_connections/last_health、创建/更新信息 | node_id 唯一、enabled+node_id |
| top_song_cache | Top10 聚合缓存文档，由 refresh_top_songs_cache() 管理 | 逻辑缓存；具体字段以函数为准 |
| seq | 后台手工创建歌曲的 songs 自增序列 | name 查询 |
| migrations | tools/migrate_db.py 的 SQLite→Mongo 一次性迁移标记 | 迁移脚本管理 |

### 歌曲文件约定

- 内置/上传歌曲目录：SONGS_DIR/<song_id>/。
- 标准文件：main.tja + main.ogg 或 main.mp3；预览生成 preview.mp3。
- 网页上传 ID：sha256(UTF-8 规范化 TJA 内容)-sha256(音乐二进制)，形如 64 hex + - + 64 hex。
- tjaf.Tja.to_mongo() 令 DB offset 固定为 0，避免与前端 TJA 自带 OFFSET 双重应用；前端 ParseTja 会将 offset 转成毫秒。
- 上传验证：TJA 上限、编码尝试 utf-8-sig/cp932/shift_jis/euc-jp/iso-2022-jp、必须有标题/课程/#START/#END，音乐只允许 OGG/MP3 并检查文件签名，TJA 的 WAVE 扩展名要与音乐匹配。
- 文件安装采用 staging 目录 + fsync + backup/rollback，避免 DB 写入失败留下半成品；详见 app.py:3776-3864。

## 10. 关键业务规则、缓存和安全约束

- 认证：普通登录/注册用 bcrypt；Session 通过 Redis 或文件存储，before_request 会用 session_id 与用户记录交叉校验，不一致就清空 Session。
- 权限：user_level < 50 不能进后台；等级 50 可管理公告、节点、歌曲元数据、下属用户；等级 100 才可新建/删除歌曲。管理员不能管理同级或自己。
- CSRF：管理登录及所有 route_admin_* 的 POST/PUT/PATCH/DELETE 在 before_request 中保护；前端可从 /api/csrftoken 获取 token。
- 限流：Flask-Limiter 使用 Redis URI；Redis 暂时故障时启用每 worker 的内存 fallback。Cloudflare CF-Connecting-IP 只有在连接地址属于内置 Cloudflare 网段时才可信。
- 安全 Header：所有响应至少设置 X-Content-Type-Options: nosniff、Referrer-Policy: strict-origin-when-cross-origin；后台及多人选择接口 no-store。
- 删除：公共 /api/remove 永远 403；管理员歌曲删除仍可用，账号删除会清理私有成绩/周挑战/公告已读/访问记录并匿名化历史游玩/留言。
- 排行榜资格：easysettings.js 将非标准玩法（播放速度、倍速、Doron、Abekobe、Detarame、AI）标记为不可上榜；多人会强制标准设置并保留标题排序。后端排行榜接口主要验证歌曲、分数和字段，若调整资格策略要同时审查前端和后端。
- AI 与多人互斥：AI 开启会断开/禁用 P2；多人开启会强制关闭 AI、倍速及其他修改玩法。
- AI/幽灵对战虽然内部复用双玩家渲染（主控制器为 multiplayer=1，AI/幽灵控制器为 multiplayer=2），但仍属于本地对战。`controller.pauseEnabled` 只对本地单人/AI/幽灵主画面开启，真正联机保持关闭。
- 暂停入口由 `gameinput.js` 处理 Esc/Q、手柄和暂停菜单输入；`view.js` 绘制原有暂停页面并处理鼠标/触屏菜单。AI/幽灵暂停时，2P 视图不得覆盖主暂停层，`game.css` 将暂停 Canvas 提升到 AI HUD 之上。
- 多人节点安全：只接受公开可路由的 ws/wss origin，不允许 credentials、path、query、fragment 或 localhost；健康接口必须返回合法的 status=ok、connections。
- 缓存：公开歌曲缓存 15 秒，Top10 缓存 30 秒；歌曲变化会递增 public songs cache version 并失效派生缓存。cache_ignore_urls.txt 应明确排除登录、账号、成绩、排行榜、播放、幽灵、上传、公告、多人选择和后台等动态路径；部署新前端后按 cache_flush_urls.txt 清理静态资源。
- 访问记录：只存 hash 化 IP/User-Agent，不存明文；visit_records.entered_at TTL 约 400 天。
- MongoDB：更新/备份优先使用 MONGODB_SAFETY.md 和 setup.sh；除非用户明确确认，不要 reset 数据或删除 volume。

## 11. 独立 Taiko Editor

这是与 Web 前端并列的桌面谱面编辑器，不是 Flask Blueprint。

| 路径 | 职责 |
|---|---|
| taiko-editor/main.py | PyQt GUI 入口，加载 resources/style.qss，创建 EditorWindow |
| taiko-editor/editor_window.py | 主编辑窗口、菜单/快捷键、最近文件、Undo/Redo、元数据/BPM/属性面板、保存/自动保存、上传线程；UPLOAD_URL 当前硬编码为 https://taiko.asia/api/upload |
| taiko-editor/editor_pygame.py | 另一套 pygame 编辑器实现：1280×720、60 FPS、时间线、音符放置和 SFX |
| taiko-editor/models.py | Song/Course/Measure/Note/Keyframe dataclass，NoteType 0–9，KeyframeType BPM/SCROLL/MEASURE/GoGo/BARLINE/DELAY |
| taiko-editor/tja_parser.py | parse_tja()/serialize_tja()，将 TJA 元数据、课程、测量、命令、音符转换为模型/文本 |
| taiko-editor/audio_engine.py | pygame 音频加载、播放/暂停/Seek、速度、SFX、波形峰值 |
| taiko-editor/widgets/timeline.py | 时间线/波形/网格/音符/关键帧绘制、框选、拖动、吸附、BPM 编辑 |
| taiko-editor/widgets/note_palette.py | 音符按钮和图标 |
| taiko-editor/widgets/metadata_panel.py | 歌曲标题、音频、offset 等元数据 |
| taiko-editor/widgets/course_tabs.py | easy/normal/hard/oni/ura 切换 |
| taiko-editor/widgets/properties.py | 选中音符/气球属性（如 hits） |
| taiko-editor/resources/style.qss、resources/sfx/*、ico/ico.png | 编辑器皮肤、Don/Ka/Balloon 音效、图标 |
| taiko-editor/TaikoEditor.spec | PyInstaller 打包规格 |

## 12. 工具、脚本和运维辅助路径

- scripts/reparse_uploaded_categories.py：扫描上传歌曲的 TJA，重新解析分类；支持 --categories、--songs-dir、--dry-run、--limit，可由 TAIKO_WEB_UPDATE_REPARSE_CATEGORIES 控制。
- tools/migrate_db.py：旧 SQLite taiko.db 导入 MongoDB，迁移 songs/makers/categories/song_skins，并写 migrations 标记；只在确有旧 SQLite 时使用。
- tools/generate_previews.py：从站点 /api/songs 读取歌曲，在另一台机器用 ffmpeg 生成 preview.ogg；与当前应用默认 preview.mp3 需核对。
- tools/set_previews.py：旧 SQLite 工具，从 TJA DEMOSTART/OSU PreviewTime 写 preview。
- tools/taikodb_hash.py：旧 SQLite/数字歌曲 ID 的 MD5 hash 工具。
- tools/categories.json：分类配置/导入辅助数据。
- tools/get_version.sh、get_version.bat：用 Git HEAD 生成根目录 version.json；tools/hooks/post-checkout/post-commit/post-merge/post-rewrite 自动调用 shell 版本脚本。
- tools/merge_image.htm：浏览器端图片合并辅助页；tools/setup.sh：旧直装依赖/NGINX/Supervisor 安装脚本。
- cache_ignore_urls.txt：CDN 不应缓存的动态接口列表。
- cache_flush_urls.txt：部署后需要刷新 CDN 的线上 URL 清单，当前包含 taiko.asia/www.taiko.asia 的首页、语言页和核心 JS/CSS/音频。
- update.sh：识别当前 container/direct 部署，执行 setup.sh upgrade-container 或 upgrade-direct。

## 13. 测试、检查和验证

### 测试文件

- tests/test_admin_accounts.py：管理员权限、账号清理、密码重置、Session 旋转、敏感字段不渲染、删除确认。
- tests/test_multiplayer.py：WebSocket URL 规范化、私网/路径拒绝、健康接口校验、DNS 安全、稳定节点选择、容量优先。
- tests/test_seo.py：5 语言 meta/JSON-LD、canonical/hreflang、sitemap、robots、别名 301。
- tests/test_ai_battle.js：AI RNG/权重、难度阈值、回合结果、密集音符、AI/多人冲突、HUD CSS 响应式、Easy Settings 规则，以及幽灵结果标签。
- tests/test_playerlab.js：训练区间、幽灵记录、虚拟鼓、每日挑战、推荐路径和 GhostPlayer。

### 建议命令

~~~bash
python -m compileall -q app.py schema.py multiplayer.py tjaf.py tests scripts tools
python -m unittest discover -s tests -p "test_*.py" -v

node --check public/src/js/aibattle.js
node --test tests/test_ai_battle.js
node --test tests/test_playerlab.js

git diff --check
~~~

若测试环境没有 Mongo/Redis，app.py 导入可能在索引/连接阶段变慢或失败；不要为了通过测试删除索引初始化或改成静默吞掉真实生产错误。需要隔离 DB 时应在测试中 mock app.db/外部服务。

## 14. 修改任务时的推荐定位方式

| 任务 | 首先查看 |
|---|---|
| 改首页、SEO、语言 | app.py:237-309,1441-1496、templates/index.html、tests/test_seo.py |
| 改歌曲分类/排序/选曲 | app.py:125-157,2871-2916、public/src/js/songselect.js、topsongs.js、assets.js |
| 改谱面判定/音符 | parsetja.js、parseosu.js、game.js、gamerules.js、controller.js |
| 改 Easy Settings | easysettings.js、easysettings.css、songselect.js、tests/test_ai_battle.js 中相关测试 |
| 改 AI | aibattle.js、controller.js、game.js、game.css、tests/test_ai_battle.js |
| 改多人 | p2.js、session.js、app.py:2061-2367,2925-2986、multiplayer.py、tests/test_multiplayer.py；先确认是否涉及外部节点协议 |
| 改上传/导入 | uploadmodal.js、public/upload/upload.js、customsongs.js、importsongs.js、app.py:3720-3984、tjaf.py |
| 改账号/成绩 | account.js、scorestorage.js、playstats.js、leaderboard.js、schema.py、app.py:2989-3416 |
| 改周挑战 | weeklychallenge.js、weekly_challenge.html、app.py:3419-3642 |
| 改公告/留言板 | sitemessages.js、templates/board.html、admin_messages.html、app.py:1919-2048,2399-2474 |
| 改后台 | app.py:2205-2844、对应 templates/admin_*.html、public/src/css/admin.css、管理员测试 |
| 改部署/数据安全 | docker-compose.yml、Dockerfile、gunicorn.conf.py、setup.sh、update.sh、MONGODB_SAFETY.md |

### 完成任务前后应检查

- 是否同时修改了后端路由、前端调用、schema、模板/CSS、缓存失效和测试。
- 是否保持 config.BASEDIR（代码变量为 basedir）与硬编码 /upload 路由的现状兼容。
- 是否误把 public/songs/、flask_session/、.taiko-secret-key、.admin_bootstrap.json 或日志加入输出/提交。
- 是否需要清理 CDN：参考 cache_flush_urls.txt，不要把动态 API 加入公共缓存。
- 是否需要更新 PLAN.md：它是当前仓库历史续作提示，不是本项目唯一任务清单；更新前先确认用户是否要求。
