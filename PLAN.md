# 接续 Prompt

你是接续本仓库任务的 AI，请继续用中文工作。

当前仓库路径：

```text
D:\DMH_Files\Python_projects\taiko-codex\taiko-web-beautifal
```

当前分支是 `sort-updated2`。不要修改或推送 `sort-updated`。不要新增、启用或迁移 websocket、multiplayer、online、p2、session、room、matchmaking 相关功能。

## 已完成

- 已读取目标文件 `C:\Users\antho\.codex\attachments\ebcfef37-f88c-4506-a0b2-0545e312e9dd\goal-objective.md`。
- 已从 `roll-updated` 创建并使用 `sort-updated2` 分支。
- 已实现 Easy Settings：
  - 入口按钮在选曲页搜索/TOP10 附近。
  - 支持 `playbackRate`、`baisoku`、`doron`、`abekobe`、`detarame`、`sortByTitle`、`songSelectingSpeed`。
  - 增加“恢复默认配置”按钮。
  - 当当前配置不支持排行榜时，Easy Settings 面板显示“当前配置不支持排行榜”并列出原因。
- 已修复标题排序：
  - 旧逻辑会对全量 `this.songs` 做全局 title sort，可能跨分类混排，并且遇到非字符串 title 有崩溃风险。
  - 新逻辑只在分类排序相同且同 `originalCategory` 内按安全标题排序，不做全局 flatten，不影响分类边界。
- 已做排行榜保护：
  - `playbackRate != 1`、`baisoku != 1`、`doron`、`abekobe`、`detarame` 会禁用本地成绩保存和排行榜提交。
  - `sortByTitle` 不算玩法修改，不禁用排行榜。
- 已实现玩法效果：
  - `playbackRate` 影响主音乐播放速度与游戏计时。
  - `baisoku` 影响谱面显示速度。
  - `doron` 隐藏音符/连打/气球视觉，不改谱面判定。
  - `abekobe` 仅交换红蓝音符。
  - `detarame` 仅在同尺寸红蓝音符组内随机，不改连打/气球/分歧等控制符。
- 已提交并推送：
  - commit `d5b90b2`，信息 `Add integrated Easy Settings and fix category sorting`
  - pushed to `origin/sort-updated2`
- 当前本地服务已经启动：
  - URL: `http://127.0.0.1:5000/`
  - Flask PID: `32380`
  - stderr log: `%TEMP%\taiko-web-beautifal-flask-5000.err.log`
  - stdout log: `%TEMP%\taiko-web-beautifal-flask-5000.out.log`
- 已从 `D:\ESE` 导入测试歌曲：
  - Mongo 中 `upload_source = "codex_ese_test"`
  - 11 个分类每类 10 首，共 110 首
  - 文件写入 `public\songs\<sha256-sha256>\`
  - 08 Live Festival Mode、10 Taiko Towers、11 Dan Dojo 中部分 TJA 缺少服务端上传解析器需要的 `COURSE/LEVEL`，导入时按前端默认 oni 规则补了本地测试用元数据。

## 已验证

执行并通过：

```text
node --check public/src/js/*.js，包括新增 easysettings.js，共 56 个 JS 文件
python -m compileall -q .
git diff --check
资源引用检查：assets.js 中 JS/CSS/View/图片/音频共 145 项存在
新 Easy Settings 文件无 debugger/TODO/FIXME/console.error
git diff --name-only 未触及 p2/session/websocket/server.py 等在线相关文件
```

服务/API 验证：

```text
GET http://127.0.0.1:5000/ => 200
GET http://127.0.0.1:5000/src/js/easysettings.js => 200
GET http://127.0.0.1:5000/src/css/easysettings.css => 200
GET http://127.0.0.1:5000/api/songs?type=<每个分类> => 每类至少 10 首测试曲
Mongo codex_ese_test 计数：11 类各 10 首
```

注意：Redis 本机 6379 未开启，但应用已回退到 filesystem session/cache，本地测试不阻塞。MongoDB 127.0.0.1:27017 可用。

## 工作区状态

- `PROJECT_MANUAL.md` 和 `PROJECT_OVERVIEW.md` 是既有未跟踪文件，本轮没有 stage/commit。
- 当前需要把本 `PLAN.md` 作为用户新增要求处理；如果提交，请只 stage `PLAN.md`，不要带入上述两个未跟踪文件。

## 下一步

请按这个顺序继续：

1. 打开 `http://127.0.0.1:5000/` 做浏览器手动 QA。
2. 在选曲页确认 Easy Settings 按钮位置与搜索/TOP10 不重叠。
3. 打开 Easy Settings，检查：
   - 默认状态显示排行榜可用。
   - 修改 `playbackRate`、`baisoku`、`doron`、`abekobe` 或 `detarame` 后，显示“当前配置不支持排行榜”。
   - 点击“恢复默认配置”后恢复排行榜可用。
   - 开启 `sortByTitle` 后只在当前分类内按标题排序，不跨分类混排。
4. 选一首 `D:\ESE` 导入的测试曲实际进游戏：
   - 默认配置下能正常播放。
   - 修改播放速度或玩法 modifier 后能进游戏且不会触发排行榜提交。
5. 如用户确认不再需要测试曲，可清理：
   - Mongo: `db.songs.delete_many({"upload_source": "codex_ese_test"})`
   - 文件：删除这些歌曲对应的 `public\songs\<id>` 目录。删除前必须按 Mongo 的 `id` 精确列出路径并确认都在 `public\songs` 下。
6. 每轮任务完成后，更新根目录 `PLAN.md`，继续用这种接续 Prompt 格式写清楚已完成、验证、当前状态和下一步。
