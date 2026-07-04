# 接续 Prompt

你是接续本仓库任务的 AI，请继续用中文工作。

仓库路径：

```text
D:\DMH_Files\Python_projects\taiko-codex\taiko-web-beautifal
```

当前分支是 `sort-updated2`。不要修改或推送 `sort-updated`。不要新增、启用或迁移 websocket、multiplayer、online、p2、session、room、matchmaking 相关功能。

## 已完成

- 已实现并推送 Easy Settings 与分类内标题排序修复：
  - commit `d5b90b2`：`Add integrated Easy Settings and fix category sorting`
  - pushed to `origin/sort-updated2`
- Easy Settings 支持 `playbackRate`、`baisoku`、`doron`、`abekobe`、`detarame`、`sortByTitle`、`songSelectingSpeed`。
- Easy Settings 内有“恢复默认配置”按钮。
- 当 `playbackRate != 1`、`baisoku != 1`、`doron`、`abekobe` 或 `detarame` 启用时，面板显示当前配置不支持排行榜，并禁止本地成绩保存和排行榜提交。
- `sortByTitle` 只在分类内排序，不跨分类混排，也不禁用排行榜。
- 已从 `D:\ESE` 导入本地测试曲：
  - Mongo 标记：`upload_source = "codex_ese_test"`
  - 11 个分类每类 10 首，共 110 首
  - 文件写入 `public\songs\<sha256-sha256>\`
- 已新增并推送接续计划：
  - commit `8c4c9f2`：`Add continuation plan`
- 本轮已把首页版本号从 `vLightNova 2.0.5` 改成 `vLightNova 2.0.6`：
  - 文件：`templates/index.html`
- 本轮已更新部署后缓存清理清单：
  - 文件：`cache_flush_urls.txt`
  - 域名：`https://taiko.asia` 和 `https://www.taiko.asia`

## 已验证

此前已通过：

```text
node --check public/src/js/*.js，包括新增 easysettings.js，共 56 个 JS 文件
python -m compileall -q .
git diff --check
assets.js 资源引用检查：JS/CSS/View/图片/音频共 145 项存在
新 Easy Settings 文件无 debugger/TODO/FIXME/console.error
git diff --name-only 未触及 p2/session/websocket/server.py 等在线相关文件
```

服务/API 曾验证：

```text
GET http://127.0.0.1:5000/ => 200
GET http://127.0.0.1:5000/src/js/easysettings.js => 200
GET http://127.0.0.1:5000/src/css/easysettings.css => 200
GET http://127.0.0.1:5000/api/songs?type=<每个分类> => 每类至少 10 首测试曲
```

本轮版本号修改后还需要确认：

```text
Select-String templates\index.html vLightNova
git diff --check
```

## 当前状态

- `PROJECT_MANUAL.md` 和 `PROJECT_OVERVIEW.md` 是既有未跟踪文件，不要误提交。
- 每轮任务完成后都必须更新根目录 `PLAN.md`。
- 本轮修改范围是：
  - `templates/index.html`
  - `cache_flush_urls.txt`
  - `PLAN.md`
- 这些文件用于版本号 `vLightNova 2.0.6` 和部署后缓存清理说明。

## 下一步

1. 部署 `origin/sort-updated2` 最新代码。
2. 部署后按 `cache_flush_urls.txt` 清理 CDN/缓存 URL。
3. 线上检查：
   - `https://taiko.asia/` 页面版本显示 `vLightNova 2.0.6`
   - `https://taiko.asia/src/js/easysettings.js` 返回 200
   - `https://taiko.asia/src/css/easysettings.css` 返回 200
   - 选曲页 Easy Settings 能打开，恢复默认配置按钮可用
4. 每轮任务完成后继续更新根目录 `PLAN.md`。
