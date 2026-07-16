class PlayerLab {
	constructor(songSelect) {
		this.songSelect = songSelect
		this.opened = false
	}

	static get storageKey() {
		return "taikoPlayerLab"
	}

	static isMobileDevice() {
		if (typeof navigator === "undefined") return false
		if (navigator.userAgentData && typeof navigator.userAgentData.mobile === "boolean") {
			return navigator.userAgentData.mobile
		}
		if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent || "")) {
			return true
		}
		return !!(navigator.maxTouchPoints > 0 && typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches)
	}

	static loadState() {
		try {
			return Object.assign({practice: null, ghostEnabled: true, virtualDrumEnabled: PlayerLab.isMobileDevice(), dailyRuns: {}}, JSON.parse(localStorage.getItem(PlayerLab.storageKey) || "{}"))
		} catch (_error) {
			return {practice: null, ghostEnabled: true, virtualDrumEnabled: PlayerLab.isMobileDevice(), dailyRuns: {}}
		}
	}

	static saveState(state) {
		localStorage.setItem(PlayerLab.storageKey, JSON.stringify(state))
	}

	static practiceFor(song) {
		var practice = PlayerLab.loadState().practice
		return practice && String(practice.songId) === String(song.id || song.folder) ? practice : null
	}

	static applyPractice(controller) {
		var config = controller.selectedSong.practiceMode
		if (!config) {
			return false
		}
		var start = Math.max(0, Number(config.start) || 0) * 1000
		var end = Math.max(start + 1000, (Number(config.end) || start / 1000 + 15) * 1000)
		var shift = Math.max(0, start - 1500)
		var data = controller.parsedSongData
		var circles = (data.circles || []).filter(circle => circle.ms >= start && circle.ms <= end)
		if (!circles.length) {
			controller.selectedSong.practiceMode = null
			return false
		}
		var shiftItem = item => {
			if (typeof item.ms === "number") item.ms -= shift
			if (typeof item.endTime === "number") item.endTime -= shift
			return item
		}
		data.circles = circles.map(shiftItem)
		;["events", "measures", "timingPoints"].forEach(name => {
			if (Array.isArray(data[name])) {
				data[name] = data[name].filter(item => typeof item.ms !== "number" || (item.ms >= shift && item.ms <= end)).map(shiftItem)
			}
		})
		controller.offset += shift
		controller.saveScore = false
		controller.practiceMode = Object.assign({}, config, {startMS: start, endMS: end, shiftMS: shift})
		return true
	}

	static ghostKey(song) {
		return "taikoGhost:" + String(song.hash || song.folder || song.id || song.title) + ":" + String(song.difficulty || "oni")
	}

	static ghostAvailable(song) {
		try {
			var ghost = JSON.parse(localStorage.getItem(PlayerLab.ghostKey(song)) || "null")
			return !!(ghost && Array.isArray(ghost.events) && ghost.events.length)
		} catch (_error) {
			return false
		}
	}

	static ghostDifficulties(song) {
		var order = ["easy", "normal", "hard", "oni", "ura"]
		return order.filter(diff => song && song.courses && song.courses[diff])
	}

	static async compressGhost(ghost) {
		if (typeof CompressionStream === "undefined") return null
		var stream = new Blob([JSON.stringify(ghost)]).stream().pipeThrough(new CompressionStream("gzip"))
		var buffer = await new Response(stream).arrayBuffer()
		var bytes = new Uint8Array(buffer), binary = ""
		for (var i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
		return btoa(binary)
	}

	static async decompressGhost(payload) {
		if (typeof DecompressionStream === "undefined") return null
		var binary = atob(payload), bytes = new Uint8Array(binary.length)
		for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
		var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))
		return JSON.parse(await new Response(stream).text())
	}

	static async syncGhost(song, ghost) {
		if (typeof account === "undefined" || !account.loggedIn || typeof loader === "undefined" || !loader.getCsrfToken) return false
		var payload = await PlayerLab.compressGhost(ghost)
		if (!payload) return false
		var token = await loader.getCsrfToken()
		var response = await fetch("api/ghost", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRFToken": token}, body: JSON.stringify({hash: song.hash || song.folder || song.id, difficulty: song.difficulty || "oni", encoding: "gzip", payload: payload})})
		return response.ok
	}

	static async pullGhost(song) {
		if (typeof account === "undefined" || !account.loggedIn) return null
		var params = new URLSearchParams({hash: String(song.hash || song.folder || song.id), difficulty: String(song.difficulty || "oni")})
		var response = await fetch("api/ghost?" + params.toString(), {credentials: "same-origin"})
		if (!response.ok) return null
		var data = await response.json()
		if (!data.ghost || data.ghost.encoding !== "gzip") return null
		return PlayerLab.decompressGhost(data.ghost.payload)
	}

	static GhostPlayer = class {
		constructor(controller) {
			this.controller = controller
			this.events = []
			this.index = 0
			try {
				var ghost = JSON.parse(localStorage.getItem(PlayerLab.ghostKey(controller.selectedSong)) || "null")
				this.events = ghost && Array.isArray(ghost.events) ? ghost.events : []
			} catch (_error) {}
		}

		update() {
			var game = this.controller.game
			var circles = game.songData.circles || []
			var circle = circles[game.currentCircle]
			if (!circle || circle.isPlayed || (circle.branch && !circle.branch.active)) return
			var isNote = ["don", "ka", "daiDon", "daiKa"].indexOf(circle.type) !== -1
			if (!isNote) return
			var event = this.events[this.index]
			if (!event) {
				if (game.elapsedTime >= circle.ms + game.rules.bad) {
					game.skipNote(circle)
					game.updateCurrentCircle()
				}
				return
			}
			if (game.elapsedTime < Number(event.t)) return
			this.index++
			var score = event.j === 2 ? 450 : event.j === 1 ? 230 : 0
			if (score) {
				var dai = (circle.type === "daiDon" || circle.type === "daiKa") ? 2 : 0
				this.controller.mekadon.playNow(circle, score, dai, false)
			} else {
				game.skipNote(circle)
				game.updateCurrentCircle()
			}
		}

		clean() {
			this.controller = null
			this.events = []
		}
	}

	static startGhost(controller) {
		var state = PlayerLab.loadState()
		if (!state.ghostEnabled || controller.autoPlayEnabled || controller.multiplayer || controller.practiceMode || controller.selectedSong.dailyChallenge) return null
		var previous = null
		try {
			previous = JSON.parse(localStorage.getItem(PlayerLab.ghostKey(controller.selectedSong)) || "null")
		} catch (_error) {}
		controller.ghostRace = {previous: previous, events: [], index: 0, finished: false}
		return controller.ghostRace
	}

	static recordGhost(controller, score, circle) {
		var race = controller.ghostRace
		if (!race || race.finished || !circle) return
		var event = {
			t: Math.round(circle.ms),
			j: score === 450 ? 2 : score === 230 ? 1 : 0,
			p: Math.max(0, Math.round(controller.game.globalScore.points || 0))
		}
		race.events.push(event)
		var previousEvents = race.previous && race.previous.events || []
		while (race.index + 1 < previousEvents.length && previousEvents[race.index + 1].t <= event.t) race.index++
	}

	static finishGhost(controller) {
		var race = controller.ghostRace
		if (!race || race.finished || !race.events.length) return false
		race.finished = true
		var result = {version: 1, recordedAt: new Date().toISOString(), events: race.events, points: race.events[race.events.length - 1].p}
		var previousPoints = race.previous && Number(race.previous.points) || -1
		if (result.points >= previousPoints) {
			localStorage.setItem(PlayerLab.ghostKey(controller.selectedSong), JSON.stringify(result))
			PlayerLab.syncGhost(controller.selectedSong, result).catch(() => {})
			return true
		}
		return false
	}

	static cleanGhost(controller) {
		controller.ghostRace = null
	}

	static utcDateKey(date) {
		return (date || new Date()).toISOString().slice(0, 10)
	}

	static hashText(text) {
		var hash = 2166136261
		for (var i = 0; i < text.length; i++) {
			hash ^= text.charCodeAt(i)
			hash = Math.imul(hash, 16777619)
		}
		return hash >>> 0
	}

	static dailyChallenge(songs, date) {
		var eligible = (songs || []).filter(song => song && song.courses && !song.action && !song.unloaded)
		if (!eligible.length) return null
		var dateKey = PlayerLab.utcDateKey(date)
		var song = eligible[PlayerLab.hashText("daily:" + dateKey) % eligible.length]
		var preference = ["normal", "hard", "oni", "easy", "ura"]
		var available = preference.filter(diff => song.courses[diff])
		var difficulty = available[PlayerLab.hashText("difficulty:" + dateKey) % available.length]
		return {dateKey: dateKey, song: song, difficulty: difficulty}
	}

	static completeDaily(controller) {
		var daily = controller.selectedSong.dailyChallenge
		if (!daily) return null
		var state = PlayerLab.loadState()
		state.dailyRuns = state.dailyRuns || {}
		if (!state.dailyRuns[daily.dateKey]) {
			state.dailyRuns[daily.dateKey] = {
				points: Math.max(0, Math.round(controller.game.globalScore.points || 0)),
				completedAt: new Date().toISOString()
			}
		}
		var keys = Object.keys(state.dailyRuns).sort().reverse()
		var streak = 0
		var cursor = new Date(daily.dateKey + "T00:00:00.000Z")
		while (state.dailyRuns[PlayerLab.utcDateKey(cursor)]) {
			streak++
			cursor.setUTCDate(cursor.getUTCDate() - 1)
		}
		state.dailyStreak = streak
		state.dailyLast = keys[0] || daily.dateKey
		PlayerLab.saveState(state)
		return streak
	}

	static recommendation(songs, scoreStore) {
		var levels = {easy: 2, normal: 4, hard: 6, oni: 8, ura: 9}
		var candidates = []
		var total = 0
		var count = 0
		;(songs || []).forEach(song => {
			if (!song || song.action || !song.courses) return
			Object.keys(levels).forEach(diff => {
				var course = song.courses[diff]
				if (!course) return
				var score = scoreStore && scoreStore[song.hash || song.id] && scoreStore[song.hash || song.id][diff]
				var accuracy = score ? (Number(score.good || 0) + Number(score.ok || 0) * 0.55) / Math.max(1, Number(score.good || 0) + Number(score.ok || 0) + Number(score.bad || 0)) : 0
				if (score) { total += levels[diff] + Math.min(1, accuracy); count++ }
				candidates.push({song: song, difficulty: diff, level: levels[diff], stars: Number(course.stars) || levels[diff], played: !!score, accuracy: accuracy})
			})
		})
		var skill = count ? total / count : 3.5
		candidates.sort((a, b) => {
			var aDistance = Math.abs(a.level - (skill + 0.7)) + (a.played ? 0.35 : 0)
			var bDistance = Math.abs(b.level - (skill + 0.7)) + (b.played ? 0.35 : 0)
			return aDistance - bDistance || a.stars - b.stars
		})
		var picks = candidates.filter(item => !item.played).slice(0, 3)
		if (picks.length < 3) picks = candidates.slice(0, 3)
		return {skill: Math.round(skill * 100) / 100, picks: picks}
	}

	static analyzeTja(text, musicFile) {
		var source = String(text || "").replace(/^\uFEFF/, "")
		var lines = source.split(/\r?\n/)
		var errors = [], warnings = [], courses = 0, notes = 0, starts = 0, ends = 0
		var title = "", wave = "", offset = null, inChart = false, chartNotes = 0
		lines.forEach(raw => {
			var line = raw.trim()
			var match = line.match(/^([A-Z][A-Z0-9_]*)\s*:\s*(.*)$/i)
			if (match && !inChart) {
				var key = match[1].toUpperCase(), value = match[2].trim()
				if (key === "TITLE") title = value
				if (key === "WAVE") wave = value
				if (key === "OFFSET") offset = Number(value)
				if (key === "COURSE") courses++
				return
			}
			if (/^#START/i.test(line)) { starts++; inChart = true; chartNotes = 0; return }
			if (/^#END/i.test(line)) { ends++; inChart = false; notes += chartNotes; return }
			if (inChart && /^[0-9]/.test(line)) chartNotes += (line.split(",")[0].match(/[1-9]/g) || []).length
		})
		if (!title) errors.push("缺少 TITLE")
		if (!wave) errors.push("缺少 WAVE 音频文件名")
		if (offset !== null && !Number.isFinite(offset)) errors.push("OFFSET 不是有效数字")
		if (!courses) errors.push("没有 COURSE 难度")
		if (!starts || starts !== ends) errors.push("#START/#END 不成对")
		if (!notes) warnings.push("没有解析到可演奏音符")
		if (musicFile && wave && musicFile.name.toLowerCase() !== wave.toLowerCase()) warnings.push("WAVE 与所选音频文件名不一致")
		if (musicFile && !/\.(ogg|mp3)$/i.test(musicFile.name)) errors.push("音频必须是 OGG 或 MP3")
		return {ok: errors.length === 0, errors: errors, warnings: warnings, title: title, courses: courses, notes: notes}
	}

	getSelectedDifficulty() {
		var songSelect = this.songSelect
		if (!songSelect || songSelect.selectedDiff < songSelect.diffOptions.length) return null
		var index = songSelect.selectedDiff - songSelect.diffOptions.length
		if (index === 4) index = 3
		if (index === 3 && songSelect.state.ura) return "ura"
		return songSelect.difficultyId[index] || null
	}

	showDifficultyControls() {
		if (!this.songSelect || !this.songSelect.state || this.songSelect.state.screen !== "difficulty") return
		var song = this.songSelect.songs[this.songSelect.selectedSong]
		if (!song || !song.courses) return
		if (!this.trainingTrigger) {
			this.trainingTrigger = document.createElement("button")
			this.trainingTrigger.id = "difficulty-training-trigger"
			this.trainingTrigger.type = "button"
			this.trainingTrigger.innerHTML = "<span>训练</span>"
			this.trainingTrigger.setAttribute("aria-label", "打开训练选项")
			loader.screen.appendChild(this.trainingTrigger)
			;["mousedown", "mouseup", "touchstart", "touchend", "pointerdown", "pointerup", "click"].forEach(type => this.trainingTrigger.addEventListener(type, event => event.stopPropagation()))
			this.trainingTrigger.addEventListener("click", () => this.openDifficultyControls())
		}
		if (!this.controls) {
			this.controls = document.createElement("section")
			this.controls.id = "difficulty-training-controls"
			this.controls.setAttribute("role", "dialog")
			this.controls.setAttribute("aria-modal", "true")
			this.controls.innerHTML = '<div class="difficulty-training-panel"><div class="difficulty-training-heading"><span>训练选项</span><button type="button" class="difficulty-training-close" aria-label="关闭训练选项">×</button></div>' +
				'<div class="difficulty-training-tabs"><button type="button" data-training-mode="practice">段落练习</button><button type="button" data-training-mode="ghost">幽灵对战</button><button type="button" data-training-mode="daily">每日挑战</button><button type="button" data-training-mode="recommend">推荐</button></div>' +
				'<div class="difficulty-training-body"></div></div>'
			loader.screen.appendChild(this.controls)
			;["mousedown", "mouseup", "touchstart", "touchend", "pointerdown", "pointerup", "click"].forEach(type => this.controls.addEventListener(type, event => event.stopPropagation()))
			this.controls.querySelector(".difficulty-training-close").addEventListener("click", () => this.closeDifficultyControls())
			this.controls.addEventListener("click", event => { if (event.target === this.controls) this.closeDifficultyControls() })
			this.controls.querySelectorAll("[data-training-mode]").forEach(button => button.addEventListener("click", () => this.renderTrainingMode(button.dataset.trainingMode)))
		}
		this.trainingTrigger.hidden = false
		this.controls.hidden = true
		this.currentTrainingSong = song
		this.renderTrainingMode(this.trainingMode || "practice")
	}

	openDifficultyControls() {
		if (!this.controls || !this.songSelect || this.songSelect.state.screen !== "difficulty") return
		this.controls.hidden = false
		this.renderTrainingMode(this.trainingMode || "practice")
	}

	closeDifficultyControls() {
		if (this.controls) this.controls.hidden = true
	}

	hideDifficultyControls() {
		if (this.controls) this.controls.hidden = true
		if (this.trainingTrigger) this.trainingTrigger.hidden = true
	}

	renderTrainingMode(mode) {
		if (!this.controls) return
		this.trainingMode = mode
		this.controls.querySelectorAll("[data-training-mode]").forEach(button => button.classList.toggle("active", button.dataset.trainingMode === mode))
		var song = this.currentTrainingSong || this.songSelect.songs[this.songSelect.selectedSong]
		var body = this.controls.querySelector(".difficulty-training-body")
		var state = PlayerLab.loadState()
		var settingsConflict = this.songSelect.state.options === 1 || this.songSelect.state.options === 2
		var battleConflict = (typeof EasySettings !== "undefined" && EasySettings.isAiBattleEnabled()) || (typeof p2 !== "undefined" && p2.session)
		var trainingConflict = settingsConflict || battleConflict
		if (mode === "practice") {
			var practice = PlayerLab.practiceFor(song) || {start: 0, end: 30, loop: true}
			body.innerHTML = '<p>在当前选中的难度中循环练习一段谱面。</p><div class="difficulty-training-fields"><label>开始 <input data-practice-start type="number" min="0" step="1" value="' + practice.start + '"> 秒</label><label>结束 <input data-practice-end type="number" min="1" step="1" value="' + practice.end + '"> 秒</label><label><input data-practice-loop type="checkbox" ' + (practice.loop !== false ? "checked" : "") + '> 自动循环</label></div><button type="button" data-practice-save>启用练习</button><button type="button" data-practice-clear>清除</button><p class="difficulty-training-status"></p>'
			body.querySelector("[data-practice-save]").addEventListener("click", () => {
				var start = Number(body.querySelector("[data-practice-start]").value), end = Number(body.querySelector("[data-practice-end]").value), status = body.querySelector(".difficulty-training-status")
				if (trainingConflict) { status.textContent = "练习与 AI Battle、自动演奏及多人模式互斥。"; status.className = "difficulty-training-status error"; return }
				if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) { status.textContent = "结束时间必须大于开始时间。"; status.className = "difficulty-training-status error"; return }
				state.practice = {songId: song.id, start: start, end: end, loop: body.querySelector("[data-practice-loop]").checked}; state.activeMode = "practice"; PlayerLab.saveState(state); status.textContent = "已启用，确认当前难度即可开始。"; status.className = "difficulty-training-status success"
			})
			body.querySelector("[data-practice-clear]").addEventListener("click", () => { state.practice = null; if (state.activeMode === "practice") state.activeMode = null; PlayerLab.saveState(state); body.querySelector(".difficulty-training-status").textContent = "已清除练习区间。" })
		} else if (mode === "ghost") {
			var ghostDifficulties = PlayerLab.ghostDifficulties(song)
			var selectedDiff = this.ghostDifficulty && ghostDifficulties.indexOf(this.ghostDifficulty) !== -1 ? this.ghostDifficulty : this.getSelectedDifficulty()
			if (ghostDifficulties.indexOf(selectedDiff) === -1) selectedDiff = ghostDifficulties[0] || null
			this.ghostDifficulty = selectedDiff
			var ghostSong = {hash: song.hash || song.id, id: song.id, difficulty: selectedDiff || "oni"}
			var available = !!selectedDiff && PlayerLab.ghostAvailable(ghostSong)
			var conflict = trainingConflict
			var labels = {easy: (this.songSelect.difficulty && this.songSelect.difficulty[0]) || "简单", normal: (this.songSelect.difficulty && this.songSelect.difficulty[1]) || "普通", hard: (this.songSelect.difficulty && this.songSelect.difficulty[2]) || "困难", oni: (this.songSelect.difficulty && this.songSelect.difficulty[3]) || "魔王", ura: "里"}
			body.innerHTML = '<p>在这里直接选择要挑战的难度，不需要移动外层光标。</p><div class="difficulty-training-ghost-difficulties" role="group" aria-label="幽灵难度"></div><p class="difficulty-training-ghost-info"></p><button type="button" data-ghost-start>' + (conflict ? "查看冲突说明" : (available ? "开始幽灵对战" : "如何生成幽灵")) + '</button><label class="difficulty-training-check"><input data-ghost-record type="checkbox" ' + (state.ghostEnabled !== false ? "checked" : "") + '> 普通游玩时记录新幽灵</label><label class="difficulty-training-check"><input data-ghost-virtual-drum type="checkbox" ' + (state.virtualDrumEnabled ? "checked" : "") + '> 开启虚拟鼓</label><p class="difficulty-training-status"></p>'
			var difficultyButtons = body.querySelector(".difficulty-training-ghost-difficulties")
			ghostDifficulties.forEach(diff => {
				var button = document.createElement("button")
				button.type = "button"
				button.dataset.ghostDifficulty = diff
				button.textContent = labels[diff] || diff.toUpperCase()
				button.className = (diff === selectedDiff ? "active " : "") + (PlayerLab.ghostAvailable({hash: ghostSong.hash, id: song.id, difficulty: diff}) ? "has-ghost" : "")
				button.addEventListener("click", () => { this.ghostDifficulty = diff; this.renderTrainingMode("ghost") })
				difficultyButtons.appendChild(button)
			})
			var ghostInfo = body.querySelector(".difficulty-training-ghost-info")
			ghostInfo.textContent = conflict ? "幽灵对战不能与 AI Battle、自动演奏或实时多人同时使用。" : (available ? labels[selectedDiff] + "难度已有最佳幽灵，可以开始对战。" : (selectedDiff ? labels[selectedDiff] + "难度还没有幽灵记录，请先正常单人游玩一次。" : "当前歌曲没有可用难度。"))
			body.querySelector("[data-ghost-record]").addEventListener("change", event => { state.ghostEnabled = event.target.checked; PlayerLab.saveState(state) })
			body.querySelector("[data-ghost-virtual-drum]").addEventListener("change", event => { state.virtualDrumEnabled = event.target.checked; PlayerLab.saveState(state) })
			body.querySelector("[data-ghost-start]").addEventListener("click", () => {
				if (conflict) body.querySelector(".difficulty-training-status").textContent = "请先关闭 AI Battle、自动演奏或多人模式。"
				else if (!selectedDiff || !available) body.querySelector(".difficulty-training-status").textContent = "先用普通单人模式完成一次所选难度，系统会自动保存幽灵。"
				else this.songSelect.startSelectedTrainingMode("ghost", selectedDiff, state.virtualDrumEnabled)
			})
			var cloudKey = String(ghostSong.hash)
			var missingGhostDifficulties = ghostDifficulties.filter(diff => !PlayerLab.ghostAvailable({hash: ghostSong.hash, id: song.id, difficulty: diff}))
			if (missingGhostDifficulties.length && typeof account !== "undefined" && account.loggedIn && this.ghostSyncKey !== cloudKey) {
				this.ghostSyncKey = cloudKey
				body.querySelector(".difficulty-training-status").textContent = "正在同步登录用户的云端幽灵…"
				Promise.all(missingGhostDifficulties.map(diff => {
					var cloudSong = {hash: ghostSong.hash, id: song.id, difficulty: diff}
					return PlayerLab.pullGhost(cloudSong).then(remote => {
						var localPoints = 0
						try { localPoints = Number(JSON.parse(localStorage.getItem(PlayerLab.ghostKey(cloudSong)) || "{}").points || 0) } catch (_error) {}
						if (remote && Number(remote.points || 0) >= localPoints) {
							localStorage.setItem(PlayerLab.ghostKey(cloudSong), JSON.stringify(remote))
							return true
						}
						return false
					}).catch(() => false)
				})).then(changed => {
					if (changed.some(Boolean) && this.controls && !this.controls.hidden && this.trainingMode === "ghost") this.renderTrainingMode("ghost")
					else if (this.controls && !this.controls.hidden && this.trainingMode === "ghost") body.querySelector(".difficulty-training-status").textContent = "云端没有该歌曲的幽灵记录。"
				})
			}
		} else if (mode === "daily") {
			var daily = PlayerLab.dailyChallenge(this.songSelect.songs), completed = daily && state.dailyRuns && state.dailyRuns[daily.dateKey]
			body.innerHTML = daily ? '<p>' + daily.dateKey + " · " + (daily.song.title || daily.song.originalTitle) + " · " + daily.difficulty.toUpperCase() + " · 连续 " + (state.dailyStreak || 0) + " 天" + (completed ? "（已完成）" : "") + '</p><button type="button" data-daily-start ' + (trainingConflict ? "disabled" : "") + '>' + (trainingConflict ? "当前模式不可用" : "开始今日挑战") + '</button>' : "<p>当前曲库没有可用歌曲。</p>"
			if (daily && !trainingConflict) body.querySelector("[data-daily-start]").addEventListener("click", () => { this.hideDifficultyControls(); this.songSelect.startDailyChallenge(daily) })
		} else {
			var recommendation = PlayerLab.recommendation(this.songSelect.songs, typeof scoreStorage !== "undefined" ? scoreStorage.scores : {})
			body.innerHTML = '<p>' + (trainingConflict ? "推荐训练与 AI Battle、自动演奏及多人模式互斥。" : "当前训练等级约 " + recommendation.skill + "，选择一项开始。") + '</p><ol class="difficulty-training-path"></ol>'
			var path = body.querySelector(".difficulty-training-path")
			recommendation.picks.forEach(pick => { var item = document.createElement("li"); item.textContent = (pick.song.title || pick.song.originalTitle) + " · " + pick.difficulty.toUpperCase() + " · " + pick.stars + "★"; if (!trainingConflict) item.addEventListener("click", () => { this.hideDifficultyControls(); this.songSelect.startRecommendedSong(pick) }); else item.classList.add("disabled"); path.appendChild(item) })
		}
	}

	display() {
		return this.showDifficultyControls()
		if (!this.songSelect || !this.songSelect.state || ["song", "difficulty"].indexOf(this.songSelect.state.screen) === -1) return
		var song = this.songSelect.songs[this.songSelect.selectedSong]
		if (!song || !song.courses) return
		if (typeof EasySettings !== "undefined" && EasySettings.isOpen()) EasySettings.close()
		;[this.songSelect.search, this.songSelect.topSongs, this.songSelect.weeklyChallenge, this.songSelect.uploadModal].forEach(modal => {
			if (modal && modal.opened && typeof modal.remove === "function") modal.remove(false)
		})
		this.opened = true
		var state = PlayerLab.loadState()
		var practice = PlayerLab.practiceFor(song) || {start: 0, end: 30, loop: true}
		this.root = document.createElement("div")
		this.root.id = "player-lab-overlay"
		this.root.innerHTML = '<section id="player-lab" role="dialog" aria-modal="true" aria-labelledby="player-lab-title">' +
			'<button class="player-lab-close" type="button" aria-label="Close">×</button>' +
			'<h2 id="player-lab-title">训练中心</h2>' +
			'<p class="player-lab-song"></p>' +
			'<div class="player-lab-section"><h3>段落练习</h3>' +
			'<label>开始（秒）<input name="practice-start" type="number" min="0" step="1"></label>' +
			'<label>结束（秒）<input name="practice-end" type="number" min="1" step="1"></label>' +
			'<label class="player-lab-check"><input name="practice-loop" type="checkbox"> 自动循环</label>' +
			'<div class="player-lab-actions"><button class="player-lab-practice" type="button">下次游玩启用练习</button><button class="player-lab-practice-clear" type="button">清除练习</button></div><span class="player-lab-practice-status"></span></div>' +
			'<div class="player-lab-section"><h3>幽灵对战</h3>' +
			'<label class="player-lab-check"><input name="ghost-enabled" type="checkbox"> 记录并挑战本谱面最佳幽灵</label>' +
			'<p class="player-lab-ghost-status"></p></div>' +
			'<div class="player-lab-section"><h3>每日挑战</h3><p class="player-lab-daily"></p>' +
			'<button class="player-lab-daily-start" type="button">开始今日挑战</button></div>' +
			'<div class="player-lab-section"><h3>自适应推荐</h3><p class="player-lab-recommendation"></p><ol class="player-lab-path"></ol></div>' +
			'</section>'
		this.root.querySelector(".player-lab-song").textContent = song.title || song.originalTitle || String(song.id)
		this.root.querySelector('[name="practice-start"]').value = practice.start
		this.root.querySelector('[name="practice-end"]').value = practice.end
		this.root.querySelector('[name="practice-loop"]').checked = practice.loop !== false
		if (PlayerLab.practiceFor(song)) this.root.querySelector(".player-lab-practice-status").textContent = "当前歌曲已有待用练习区间。"
		this.root.querySelector('[name="ghost-enabled"]').checked = state.ghostEnabled !== false
		var ghostDifficulties = Object.keys(song.courses || {})
		var ghostCount = ghostDifficulties.filter(diff => localStorage.getItem(PlayerLab.ghostKey({hash: song.hash || song.id, difficulty: diff}))).length
		this.root.querySelector(".player-lab-ghost-status").textContent = ghostCount ? "已有 " + ghostCount + " 个难度的本地幽灵。" : "完成一次正常游玩后会保存首个幽灵。"
		this.root.querySelector('[name="ghost-enabled"]').addEventListener("change", event => {
			state.ghostEnabled = event.target.checked
			PlayerLab.saveState(state)
		})
		var daily = PlayerLab.dailyChallenge(this.songSelect.songs)
		var dailyText = this.root.querySelector(".player-lab-daily")
		var dailyButton = this.root.querySelector(".player-lab-daily-start")
		if (daily) {
			var completed = state.dailyRuns && state.dailyRuns[daily.dateKey]
			dailyText.textContent = daily.dateKey + " · " + (daily.song.title || daily.song.originalTitle) + " · " + daily.difficulty.toUpperCase() + " · 连续 " + (state.dailyStreak || 0) + " 天" + (completed ? "（今日已完成）" : "")
			dailyButton.addEventListener("click", () => {
				this.remove()
				this.songSelect.startDailyChallenge(daily)
			})
		} else {
			dailyText.textContent = "当前曲库没有可用歌曲。"
			dailyButton.disabled = true
		}
		var recommendation = PlayerLab.recommendation(this.songSelect.songs, typeof scoreStorage !== "undefined" ? scoreStorage.scores : {})
		var recommendationText = this.root.querySelector(".player-lab-recommendation")
		var path = this.root.querySelector(".player-lab-path")
		if (recommendation.picks.length) {
			recommendationText.textContent = "当前训练等级约 " + recommendation.skill + "；建议从略高于当前水平的谱面开始。"
			recommendation.picks.forEach((pick, index) => {
				var item = document.createElement("li")
				item.textContent = (index + 1) + ". " + (pick.song.title || pick.song.originalTitle) + " · " + pick.difficulty.toUpperCase() + " · " + pick.stars + "★"
				item.addEventListener("click", () => {
					this.remove()
					this.songSelect.startRecommendedSong(pick)
				})
				path.appendChild(item)
			})
		} else {
			recommendationText.textContent = "暂无可推荐谱面。"
		}
		this.root.querySelector(".player-lab-close").addEventListener("click", () => this.remove())
		this.root.addEventListener("mousedown", event => {
			if (event.target === this.root) this.remove()
		})
		this.root.querySelector(".player-lab-practice").addEventListener("click", () => {
			var start = Number(this.root.querySelector('[name="practice-start"]').value)
			var end = Number(this.root.querySelector('[name="practice-end"]').value)
			var status = this.root.querySelector(".player-lab-practice-status")
			if ((typeof EasySettings !== "undefined" && EasySettings.isAiBattleEnabled()) || (typeof p2 !== "undefined" && p2.session)) {
				status.textContent = "练习模式不能与 AI Battle 或实时多人同时启用。"
				status.className = "player-lab-practice-status error"
				return
			}
			if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
				status.textContent = "结束时间必须晚于开始时间。"
				status.className = "player-lab-practice-status error"
				return
			}
			state.practice = {songId: song.id, start: start, end: end, loop: this.root.querySelector('[name="practice-loop"]').checked}
			PlayerLab.saveState(state)
			status.textContent = "已启用；关闭面板并选择难度开始。"
			status.className = "player-lab-practice-status success"
			this.songSelect.playerLabButton.classList.add("practice-active")
		})
		this.root.querySelector(".player-lab-practice-clear").addEventListener("click", () => {
			state.practice = null
			PlayerLab.saveState(state)
			this.root.querySelector(".player-lab-practice-status").textContent = "练习区间已清除。"
			this.songSelect.playerLabButton.classList.remove("practice-active")
		})
		loader.screen.appendChild(this.root)
		noResizeRoot = true
		cancelTouch = false
	}

	remove() {
		if (!this.opened) return
		this.opened = false
		if (this.root) this.root.remove()
		this.root = null
		noResizeRoot = false
		cancelTouch = true
	}

	clean() {
		this.remove()
		if (this.controls) this.controls.remove()
		if (this.trainingTrigger) this.trainingTrigger.remove()
		this.controls = null
		this.trainingTrigger = null
		this.songSelect = null
	}
}

if (typeof module !== "undefined") {
	module.exports = PlayerLab
}
