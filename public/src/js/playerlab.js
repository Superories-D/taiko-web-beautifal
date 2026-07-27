class PlayerLab {
	constructor(songSelect) {
		this.songSelect = songSelect
		this.opened = false
		this.armedPractice = null
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
			var state = Object.assign({practice: null, ghostEnabled: true, virtualDrumEnabled: PlayerLab.isMobileDevice(), dailyRuns: {}}, JSON.parse(localStorage.getItem(PlayerLab.storageKey) || "{}"))
			var legacyActiveMode = Object.prototype.hasOwnProperty.call(state, "activeMode")
			delete state.activeMode
			if (legacyActiveMode) localStorage.setItem(PlayerLab.storageKey, JSON.stringify(state))
			return state
		} catch (_error) {
			return {practice: null, ghostEnabled: true, virtualDrumEnabled: PlayerLab.isMobileDevice(), dailyRuns: {}}
		}
	}

	static saveState(state) {
		var storedState = Object.assign({}, state)
		delete storedState.activeMode
		localStorage.setItem(PlayerLab.storageKey, JSON.stringify(storedState))
	}

	static practiceFor(song) {
		if (!song) return null
		var practice = PlayerLab.loadState().practice
		return practice && String(practice.songId) === String(song.id || song.folder) ? practice : null
	}

	static format(message, ...values) {
		return String(message || "").replace(/%(\d+)/g, (_match, index) => {
			var value = values[Number(index) - 1]
			return typeof value === "undefined" || value === null ? "" : String(value)
		})
	}

	armPractice(song, config) {
		if (!song || !config) return null
		this.armedPractice = Object.assign({}, config, {songId: song.id || song.folder})
		return Object.assign({}, this.armedPractice)
	}

	hasArmedPractice(song) {
		return !!(song && this.armedPractice && String(this.armedPractice.songId) === String(song.id || song.folder))
	}

	consumeArmedPractice(song) {
		if (!this.hasArmedPractice(song)) return null
		var practice = Object.assign({}, this.armedPractice)
		this.armedPractice = null
		return practice
	}

	cancelArmedPractice() {
		this.armedPractice = null
	}

	savePractice(song, config) {
		var state = PlayerLab.loadState()
		state.practice = {
			songId: song.id || song.folder,
			start: config.start,
			end: config.end,
			loop: config.loop !== false
		}
		PlayerLab.saveState(state)
		this.armPractice(song, state.practice)
		return Object.assign({}, state.practice)
	}

	clearPractice() {
		var state = PlayerLab.loadState()
		state.practice = null
		PlayerLab.saveState(state)
		this.cancelArmedPractice()
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
				var challenge = controller.asyncChallenge
				var ghost = challenge && challenge.opponentGhost ? challenge.opponentGhost : JSON.parse(localStorage.getItem(PlayerLab.ghostKey(controller.selectedSong)) || "null")
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
		var challenge = controller.asyncChallenge
		if (!challenge && (!state.ghostEnabled || controller.autoPlayEnabled || controller.multiplayer || controller.practiceMode || controller.selectedSong.dailyChallenge)) return null
		var previous = null
		if (challenge && challenge.opponentGhost) previous = challenge.opponentGhost
		else try { previous = JSON.parse(localStorage.getItem(PlayerLab.ghostKey(controller.selectedSong)) || "null") } catch (_error) {}
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
		if (controller.asyncChallenge) {
			controller.challengeGhostResult = result
			return true
		}
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
		var text = strings.playerLab
		if (!this.trainingTrigger) {
			this.trainingTrigger = document.createElement("button")
			this.trainingTrigger.id = "difficulty-training-trigger"
			this.trainingTrigger.type = "button"
			this.trainingTrigger.innerHTML = "<span></span>"
			this.trainingTrigger.querySelector("span").textContent = text.trigger
			this.trainingTrigger.setAttribute("aria-label", text.openOptions)
			loader.screen.appendChild(this.trainingTrigger)
			;["mousedown", "mouseup", "touchstart", "touchend", "pointerdown", "pointerup", "click"].forEach(type => this.trainingTrigger.addEventListener(type, event => event.stopPropagation()))
			this.trainingTrigger.addEventListener("click", () => this.openDifficultyControls())
		}
		if (!this.favoriteTrigger) {
			this.favoriteTrigger = document.createElement("button")
			this.favoriteTrigger.id = "difficulty-favorite-trigger"
			this.favoriteTrigger.type = "button"
			this.favoriteTrigger.setAttribute("aria-pressed", "false")
			loader.screen.appendChild(this.favoriteTrigger)
			;["mousedown", "mouseup", "touchstart", "touchend", "pointerdown", "pointerup"].forEach(type => this.favoriteTrigger.addEventListener(type, event => event.stopPropagation()))
			this.favoriteTrigger.addEventListener("click", () => this.toggleDifficultyFavorite())
		}
		this.updateDifficultyFavorite(song)
		if (this.songSelect.library && this.songSelect.library.syncFavorites) {
			this.songSelect.library.syncFavorites().then(() => this.updateDifficultyFavorite(song)).catch(() => {})
		}
		if (!this.controls) {
			this.controls = document.createElement("section")
			this.controls.id = "difficulty-training-controls"
			this.controls.setAttribute("role", "dialog")
			this.controls.setAttribute("aria-modal", "true")
			this.controls.innerHTML = '<div class="difficulty-training-panel"><div class="difficulty-training-heading"><span>' + text.optionsTitle + '</span><button type="button" class="difficulty-training-close" aria-label="' + text.closeOptions + '">×</button></div>' +
				'<div class="difficulty-training-tabs"><button type="button" data-training-mode="practice">' + text.practiceTab + '</button><button type="button" data-training-mode="ghost">' + text.ghostTab + '</button><button type="button" data-training-mode="daily">' + text.dailyTab + '</button><button type="button" data-training-mode="recommend">' + text.recommendTab + '</button></div>' +
				'<div class="difficulty-training-body"></div></div>'
			loader.screen.appendChild(this.controls)
			;["mousedown", "mouseup", "touchstart", "touchend", "pointerdown", "pointerup", "click"].forEach(type => this.controls.addEventListener(type, event => event.stopPropagation()))
			this.controls.querySelector(".difficulty-training-close").addEventListener("click", () => this.closeDifficultyControls())
			this.controls.addEventListener("click", event => { if (event.target === this.controls) this.closeDifficultyControls() })
			this.controls.querySelectorAll("[data-training-mode]").forEach(button => button.addEventListener("click", () => this.renderTrainingMode(button.dataset.trainingMode)))
		}
		this.trainingTrigger.hidden = false
		this.favoriteTrigger.hidden = false
		this.controls.hidden = true
		this.currentTrainingSong = song
		this.renderTrainingMode(this.trainingMode || "practice")
	}

	updateDifficultyFavorite(song) {
		if (!this.favoriteTrigger) return
		var library = this.songSelect && this.songSelect.library
		if (this.songSelect && this.songSelect.songs) song = this.songSelect.songs[this.songSelect.selectedSong] || song
		var hash = song && (song.hash || song.id)
		var active = !!(library && hash && library.isFavorite && library.isFavorite(String(hash)))
		var labels = (typeof strings !== "undefined" && strings.librarySocial) || {}
		var text = active ? "★" : "☆"
		this.favoriteTrigger.textContent = text
		this.favoriteTrigger.setAttribute("aria-pressed", String(active))
		this.favoriteTrigger.setAttribute("aria-label", active ? (labels.removeFavorite || "Remove favorite") : (labels.favoriteCurrent || labels.favorite || "Favorite"))
		this.favoriteTrigger.title = active ? (labels.removeFavorite || "Remove favorite") : (labels.favoriteCurrent || labels.favorite || "Favorite")
		this.favoriteTrigger.classList.toggle("favorite-active", active)
	}

	toggleDifficultyFavorite() {
		var song = this.songSelect && this.songSelect.songs && this.songSelect.songs[this.songSelect.selectedSong]
		var library = this.songSelect && this.songSelect.library
		var hash = song && (song.hash || song.id)
		if (!song || !hash || !library || !library.toggleFavorite) return
		var result = library.toggleFavorite(String(hash))
		this.updateDifficultyFavorite(song)
		if (result && typeof result.finally === "function") result.finally(() => this.updateDifficultyFavorite(song))
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
		if (this.favoriteTrigger) this.favoriteTrigger.hidden = true
	}

	renderTrainingMode(mode) {
		if (!this.controls) return
		var text = strings.playerLab
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
			body.innerHTML = '<p>' + text.practiceDescription + '</p><div class="difficulty-training-fields"><label>' + text.start + ' <input data-practice-start type="number" min="0" step="1" value="' + practice.start + '"> ' + text.seconds + '</label><label>' + text.end + ' <input data-practice-end type="number" min="1" step="1" value="' + practice.end + '"> ' + text.seconds + '</label><label><input data-practice-loop type="checkbox" ' + (practice.loop !== false ? "checked" : "") + '> ' + text.autoLoop + '</label></div><button type="button" data-practice-save>' + text.enablePractice + '</button><button type="button" data-practice-clear>' + text.clear + '</button><p class="difficulty-training-status"></p>'
			if (this.hasArmedPractice(song)) body.querySelector(".difficulty-training-status").textContent = text.practiceArmed
			else if (PlayerLab.practiceFor(song)) body.querySelector(".difficulty-training-status").textContent = text.practiceDraftSaved
			body.querySelector("[data-practice-save]").addEventListener("click", () => {
				var start = Number(body.querySelector("[data-practice-start]").value), end = Number(body.querySelector("[data-practice-end]").value), status = body.querySelector(".difficulty-training-status")
				if (trainingConflict) { status.textContent = text.modeConflict; status.className = "difficulty-training-status error"; return }
				if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) { status.textContent = text.invalidRange; status.className = "difficulty-training-status error"; return }
				var config = this.savePractice(song, {start: start, end: end, loop: body.querySelector("[data-practice-loop]").checked})
				state.practice = config
				status.textContent = text.practiceArmed
				status.className = "difficulty-training-status success"
			})
			body.querySelector("[data-practice-clear]").addEventListener("click", () => {
				this.clearPractice()
				state.practice = null
				body.querySelector(".difficulty-training-status").textContent = text.practiceCleared
			})
		} else if (mode === "ghost") {
			var ghostDifficulties = PlayerLab.ghostDifficulties(song)
			var selectedDiff = this.ghostDifficulty && ghostDifficulties.indexOf(this.ghostDifficulty) !== -1 ? this.ghostDifficulty : this.getSelectedDifficulty()
			if (ghostDifficulties.indexOf(selectedDiff) === -1) selectedDiff = ghostDifficulties[0] || null
			this.ghostDifficulty = selectedDiff
			var ghostSong = {hash: song.hash || song.id, id: song.id, difficulty: selectedDiff || "oni"}
			var available = !!selectedDiff && PlayerLab.ghostAvailable(ghostSong)
			var conflict = trainingConflict
			var difficultyLabels = {easy: this.songSelect.difficulty[0] || strings.easy, normal: this.songSelect.difficulty[1] || strings.normal, hard: this.songSelect.difficulty[2] || strings.hard, oni: this.songSelect.difficulty[3] || strings.oni, ura: text.ura}
			body.innerHTML = '<p>' + text.ghostDescription + '</p><div class="difficulty-training-ghost-difficulties" role="group" aria-label="' + text.ghostDifficulty + '"></div><p class="difficulty-training-ghost-info"></p><button type="button" data-ghost-start>' + (conflict ? text.showConflict : (available ? text.startGhost : text.howToCreateGhost)) + '</button><label class="difficulty-training-check"><input data-ghost-record type="checkbox" ' + (state.ghostEnabled !== false ? "checked" : "") + '> ' + text.recordGhost + '</label><label class="difficulty-training-check"><input data-ghost-virtual-drum type="checkbox" ' + (state.virtualDrumEnabled ? "checked" : "") + '> ' + text.virtualDrum + '</label><p class="difficulty-training-status"></p>'
			var difficultyButtons = body.querySelector(".difficulty-training-ghost-difficulties")
			ghostDifficulties.forEach(diff => {
				var button = document.createElement("button")
				button.type = "button"
				button.dataset.ghostDifficulty = diff
				button.textContent = difficultyLabels[diff] || diff.toUpperCase()
				button.className = (diff === selectedDiff ? "active " : "") + (PlayerLab.ghostAvailable({hash: ghostSong.hash, id: song.id, difficulty: diff}) ? "has-ghost" : "")
				button.addEventListener("click", () => { this.ghostDifficulty = diff; this.renderTrainingMode("ghost") })
				difficultyButtons.appendChild(button)
			})
			var ghostInfo = body.querySelector(".difficulty-training-ghost-info")
			ghostInfo.textContent = conflict ? text.ghostModeConflict : (available ? PlayerLab.format(text.ghostReady, difficultyLabels[selectedDiff]) : (selectedDiff ? PlayerLab.format(text.ghostMissing, difficultyLabels[selectedDiff]) : text.noDifficulty))
			body.querySelector("[data-ghost-record]").addEventListener("change", event => { state.ghostEnabled = event.target.checked; PlayerLab.saveState(state) })
			body.querySelector("[data-ghost-virtual-drum]").addEventListener("change", event => { state.virtualDrumEnabled = event.target.checked; PlayerLab.saveState(state) })
			body.querySelector("[data-ghost-start]").addEventListener("click", () => {
				if (conflict) body.querySelector(".difficulty-training-status").textContent = text.closeConflictingModes
				else if (!selectedDiff || !available) body.querySelector(".difficulty-training-status").textContent = text.playToCreateGhost
				else this.songSelect.startSelectedTrainingMode("ghost", selectedDiff, state.virtualDrumEnabled)
			})
			var cloudKey = String(ghostSong.hash)
			var missingGhostDifficulties = ghostDifficulties.filter(diff => !PlayerLab.ghostAvailable({hash: ghostSong.hash, id: song.id, difficulty: diff}))
			if (missingGhostDifficulties.length && typeof account !== "undefined" && account.loggedIn && this.ghostSyncKey !== cloudKey) {
				this.ghostSyncKey = cloudKey
				body.querySelector(".difficulty-training-status").textContent = text.syncingGhosts
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
					else if (this.controls && !this.controls.hidden && this.trainingMode === "ghost") body.querySelector(".difficulty-training-status").textContent = text.noCloudGhost
				})
			}
		} else if (mode === "daily") {
			var daily = PlayerLab.dailyChallenge(this.songSelect.songs), completed = daily && state.dailyRuns && state.dailyRuns[daily.dateKey]
			body.innerHTML = daily ? '<p>' + PlayerLab.format(text.dailySummary, daily.dateKey, daily.song.title || daily.song.originalTitle, daily.difficulty.toUpperCase(), state.dailyStreak || 0, completed ? text.completed : "") + '</p><button type="button" data-daily-start ' + (trainingConflict ? "disabled" : "") + '>' + (trainingConflict ? text.modeUnavailable : text.startDaily) + '</button>' : "<p>" + text.noSongs + "</p>"
			if (daily && !trainingConflict) body.querySelector("[data-daily-start]").addEventListener("click", () => { this.hideDifficultyControls(); this.songSelect.startDailyChallenge(daily) })
		} else {
			var recommendation = PlayerLab.recommendation(this.songSelect.songs, typeof scoreStorage !== "undefined" ? scoreStorage.scores : {})
			body.innerHTML = '<p>' + (trainingConflict ? text.recommendationConflict : PlayerLab.format(text.recommendationSkill, recommendation.skill)) + '</p><ol class="difficulty-training-path"></ol>'
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
		var text = strings.playerLab
		var state = PlayerLab.loadState()
		var practice = PlayerLab.practiceFor(song) || {start: 0, end: 30, loop: true}
		this.root = document.createElement("div")
		this.root.id = "player-lab-overlay"
		this.root.innerHTML = '<section id="player-lab" role="dialog" aria-modal="true" aria-labelledby="player-lab-title">' +
			'<button class="player-lab-close" type="button" aria-label="' + text.close + '">×</button>' +
			'<h2 id="player-lab-title">' + text.trainingCenter + '</h2>' +
			'<p class="player-lab-song"></p>' +
			'<div class="player-lab-section"><h3>' + text.practiceTab + '</h3>' +
			'<label>' + text.start + '（' + text.seconds + '）<input name="practice-start" type="number" min="0" step="1"></label>' +
			'<label>' + text.end + '（' + text.seconds + '）<input name="practice-end" type="number" min="1" step="1"></label>' +
			'<label class="player-lab-check"><input name="practice-loop" type="checkbox"> ' + text.autoLoop + '</label>' +
			'<div class="player-lab-actions"><button class="player-lab-practice" type="button">' + text.enableNextPlay + '</button><button class="player-lab-practice-clear" type="button">' + text.clearPractice + '</button></div><span class="player-lab-practice-status"></span></div>' +
			'<div class="player-lab-section"><h3>' + text.ghostTab + '</h3>' +
			'<label class="player-lab-check"><input name="ghost-enabled" type="checkbox"> ' + text.recordBestGhost + '</label>' +
			'<p class="player-lab-ghost-status"></p></div>' +
			'<div class="player-lab-section"><h3>' + text.dailyTab + '</h3><p class="player-lab-daily"></p>' +
			'<button class="player-lab-daily-start" type="button">' + text.startDaily + '</button></div>' +
			'<div class="player-lab-section"><h3>' + text.recommendTab + '</h3><p class="player-lab-recommendation"></p><ol class="player-lab-path"></ol></div>' +
			'</section>'
		this.root.querySelector(".player-lab-song").textContent = song.title || song.originalTitle || String(song.id)
		this.root.querySelector('[name="practice-start"]').value = practice.start
		this.root.querySelector('[name="practice-end"]').value = practice.end
		this.root.querySelector('[name="practice-loop"]').checked = practice.loop !== false
		if (PlayerLab.practiceFor(song)) this.root.querySelector(".player-lab-practice-status").textContent = text.practiceDraftSaved
		this.root.querySelector('[name="ghost-enabled"]').checked = state.ghostEnabled !== false
		var ghostDifficulties = Object.keys(song.courses || {})
		var ghostCount = ghostDifficulties.filter(diff => localStorage.getItem(PlayerLab.ghostKey({hash: song.hash || song.id, difficulty: diff}))).length
		this.root.querySelector(".player-lab-ghost-status").textContent = ghostCount ? PlayerLab.format(text.localGhostCount, ghostCount) : text.firstGhostHint
		this.root.querySelector('[name="ghost-enabled"]').addEventListener("change", event => {
			state.ghostEnabled = event.target.checked
			PlayerLab.saveState(state)
		})
		var daily = PlayerLab.dailyChallenge(this.songSelect.songs)
		var dailyText = this.root.querySelector(".player-lab-daily")
		var dailyButton = this.root.querySelector(".player-lab-daily-start")
		if (daily) {
			var completed = state.dailyRuns && state.dailyRuns[daily.dateKey]
			dailyText.textContent = PlayerLab.format(text.dailySummary, daily.dateKey, daily.song.title || daily.song.originalTitle, daily.difficulty.toUpperCase(), state.dailyStreak || 0, completed ? text.completedToday : "")
			dailyButton.addEventListener("click", () => {
				this.remove()
				this.songSelect.startDailyChallenge(daily)
			})
		} else {
			dailyText.textContent = text.noSongs
			dailyButton.disabled = true
		}
		var recommendation = PlayerLab.recommendation(this.songSelect.songs, typeof scoreStorage !== "undefined" ? scoreStorage.scores : {})
		var recommendationText = this.root.querySelector(".player-lab-recommendation")
		var path = this.root.querySelector(".player-lab-path")
		if (recommendation.picks.length) {
			recommendationText.textContent = PlayerLab.format(text.recommendationAdvice, recommendation.skill)
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
			recommendationText.textContent = text.noRecommendations
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
				status.textContent = text.modeConflict
				status.className = "player-lab-practice-status error"
				return
			}
			if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
				status.textContent = text.invalidRange
				status.className = "player-lab-practice-status error"
				return
			}
			state.practice = this.savePractice(song, {start: start, end: end, loop: this.root.querySelector('[name="practice-loop"]').checked})
			status.textContent = text.practiceArmed
			status.className = "player-lab-practice-status success"
			this.songSelect.playerLabButton.classList.add("practice-active")
		})
		this.root.querySelector(".player-lab-practice-clear").addEventListener("click", () => {
			this.clearPractice()
			state.practice = null
			this.root.querySelector(".player-lab-practice-status").textContent = text.practiceCleared
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
		if (this.favoriteTrigger) this.favoriteTrigger.remove()
		this.controls = null
		this.trainingTrigger = null
		this.favoriteTrigger = null
		this.songSelect = null
	}
}

if (typeof module !== "undefined") {
	module.exports = PlayerLab
}
