class WeeklyChallenge {
	constructor(...args) {
		this.init(...args)
	}
	init(songSelect) {
		this.songSelect = songSelect
		this.opened = false
		this.data = null
		this.container = null
		this.challengePreview = null
		this.challengePreviewId = 0
		this.restoreAudio = null
		this.fetchId = 0
		this.countdownTimer = null
		this.serverClockOffset = 0
	}
	display() {
		if (this.opened) {
			return
		}
		this.opened = true
		this.div = document.createElement("div")
		this.div.innerHTML = assets.pages["weekly_challenge"]
		this.container = this.div.querySelector(":scope #weekly-challenge-container")
		if (this.songSelect.touchEnabled) {
			this.container.classList.add("touch-enabled")
		}
		loader.screen.appendChild(this.div)
		pageEvents.add(this.container, ["mousedown", "touchstart"], this.onClick.bind(this))
		this.startButton = this.div.querySelector(":scope #weekly-challenge-start")
		pageEvents.add(this.startButton, ["click", "touchstart"], this.onStart.bind(this))
		this.setStaticText()
		this.setStatus(strings.loading)
		this.songSelect.playSound("se_pause")
		cancelTouch = false
		noResizeRoot = true
		this.pauseSongSelectAudio()
		this.fetchData()
	}
	setStaticText() {
		var text = strings.weeklyChallenge
		this.div.querySelector(":scope .weekly-challenge-title").innerText = text.title
		this.div.querySelector(":scope .weekly-challenge-song-heading").innerText = text.thisWeekSong
		this.div.querySelector(":scope .weekly-challenge-current-heading").innerText = text.currentLeaderboard
		this.div.querySelector(":scope .weekly-challenge-previous-heading").innerText = text.previousLeaderboard
		this.startButton.innerText = text.start
		this.startButton.setAttribute("alt", text.start)
	}
	fetchData() {
		var fetchId = ++this.fetchId
		if (this.fetchController) this.fetchController.abort()
		var controller = new AbortController()
		this.fetchController = controller
		var timeout = setTimeout(() => controller.abort(), 12000)
		fetch("api/weekly-challenge/leaderboards", {
			cache: "no-store",
			signal: controller.signal
		}).then(response => {
			if (!response.ok) throw new Error("HTTP " + response.status)
			return response.json()
		}).then(data => {
			if (!this.opened || fetchId !== this.fetchId) return
			if (data.status !== "ok") {
				this.setStatus(this.errorText(data.message), true)
				return
			}
			var serverNow = Date.parse(data.server_now)
			this.serverClockOffset = Number.isFinite(serverNow) ? serverNow - Date.now() : 0
			this.data = data
			this.render()
			this.startChallengePreview(data.current)
		}).catch(error => {
			if (!this.opened || fetchId !== this.fetchId) return
			console.error("Weekly challenge load failed:", error)
			this.setStatus(strings.errorOccured, true)
		}).finally(() => {
			clearTimeout(timeout)
			if (this.fetchController === controller) this.fetchController = null
		})
	}
	errorText(message) {
		var text = strings.weeklyChallenge
		if (message && strings.serverError && strings.serverError[message]) {
			return strings.serverError[message]
		}
		return text.noChallenge
	}
	render() {
		var current = this.data.current
		if (!current || !current.song) {
			this.setStatus(strings.weeklyChallenge.noChallenge, true)
			return
		}
		this.renderSong(current)
		this.startCountdown(current.week_ends_at)
		this.renderBoard(".weekly-challenge-current-list", current.leaderboard)
		this.renderPrevious(this.data.previous)
		if (account.loggedIn) {
			this.setStatus("")
			this.startButton.disabled = false
		} else {
			this.setStatus(strings.weeklyChallenge.loginRequired)
			this.startButton.disabled = true
		}
	}
	startCountdown(endsAt) {
		this.stopCountdown()
		var end = Date.parse(endsAt)
		var element = this.div.querySelector(":scope .weekly-challenge-reset")
		if (!Number.isFinite(end) || !element) return
		var update = () => {
			var remaining = Math.max(0, end - (Date.now() + this.serverClockOffset))
			var seconds = Math.floor(remaining / 1000)
			var days = Math.floor(seconds / 86400)
			var hours = Math.floor(seconds % 86400 / 3600)
			var minutes = Math.floor(seconds % 3600 / 60)
			var secs = seconds % 60
			element.textContent = "UTC " + days + "d " + [hours, minutes, secs].map(value => String(value).padStart(2, "0")).join(":")
			if (remaining === 0) {
				this.stopCountdown()
				this.fetchData()
			}
		}
		this.countdownTimer = setInterval(update, 1000)
		update()
	}
	stopCountdown() {
		if (this.countdownTimer) clearInterval(this.countdownTimer)
		this.countdownTimer = null
	}
	renderSong(challenge) {
		var song = challenge.song
		var title = this.songSelect.getLocalTitle(song.title, song.title_lang)
		var subtitle = this.songSelect.getLocalTitle(title === song.title ? song.subtitle : "", song.subtitle_lang)
		var stars = song.courses && song.courses.oni ? song.courses.oni.stars : "?"
		this.div.querySelector(":scope .weekly-challenge-song-title").innerText = title
		this.div.querySelector(":scope .weekly-challenge-song-subtitle").innerText = subtitle || song.category || ""
		this.div.querySelector(":scope .weekly-challenge-song-meta").innerText = strings.oni + " " + stars + "\u2605"
	}
	renderPrevious(previous) {
		var label = this.div.querySelector(":scope .weekly-challenge-previous-song")
		if (previous && previous.song) {
			label.innerText = this.songSelect.getLocalTitle(previous.song.title, previous.song.title_lang)
			this.renderBoard(".weekly-challenge-previous-list", previous.leaderboard)
		} else {
			label.innerText = ""
			this.renderBoard(".weekly-challenge-previous-list", [], strings.weeklyChallenge.noPrevious)
		}
	}
	renderBoard(selector, entries, emptyText) {
		var list = this.div.querySelector(":scope " + selector)
		list.innerHTML = ""
		if (!entries || !entries.length) {
			var empty = document.createElement("li")
			empty.className = "weekly-challenge-empty"
			empty.innerText = emptyText || strings.noScores
			list.appendChild(empty)
			return
		}
		entries.forEach(entry => {
			var item = document.createElement("li")
			item.className = "weekly-challenge-rank weekly-challenge-rank-" + Math.min(entry.rank, 3)
			var rank = document.createElement("span")
			rank.className = "weekly-challenge-rank-number"
			rank.innerText = "#" + entry.rank
			var name = document.createElement("span")
			name.className = "weekly-challenge-rank-name"
			name.innerText = entry.display_name || ""
			var score = document.createElement("span")
			score.className = "weekly-challenge-rank-score"
			score.innerText = (entry.score_value || 0).toLocaleString() + strings.points
			item.appendChild(rank)
			item.appendChild(name)
			item.appendChild(score)
			list.appendChild(item)
		})
	}
	setStatus(message, error) {
		var status = this.div.querySelector(":scope .weekly-challenge-status")
		status.innerText = message || ""
		status.classList.toggle("weekly-challenge-status-error", !!error)
		status.hidden = !message
	}
	pauseSongSelectAudio() {
		var previewing = this.songSelect.previewing
		this.restoreAudio = {
			bgmEnabled: !!this.songSelect.bgmEnabled,
			previewing: previewing,
			selectedSong: this.songSelect.selectedSong,
			shouldRestorePreview: previewing !== null && previewing !== "muted"
		}
		if (this.restoreAudio.shouldRestorePreview) {
			this.songSelect.endPreview(true)
		}
		if (this.restoreAudio.bgmEnabled) {
			this.songSelect.playBgm(false)
		}
	}
	restoreSongSelectAudio() {
		if (!this.restoreAudio || !this.songSelect || this.songSelect.closed) {
			return
		}
		var restoreAudio = this.restoreAudio
		this.restoreAudio = null
		if (restoreAudio.bgmEnabled) {
			this.songSelect.playBgm(true)
		}
		if (restoreAudio.shouldRestorePreview && this.songSelect.state && this.songSelect.state.screen === "song") {
			this.songSelect.previewing = null
			this.songSelect.startPreview()
		} else {
			this.songSelect.previewing = restoreAudio.previewing
		}
	}
	startChallengePreview(challenge) {
		if (!challenge || !challenge.song) {
			return
		}
		var song = WeeklyChallenge.prepareSongAsset(challenge.song)
		if (!song || !song.music) {
			return
		}
		this.stopChallengePreview()
		var previewId = ++this.challengePreviewId
		snd.previewGain.setVolumeMul(song.volume || 1)
		snd.previewGain.load(song.music).then(sound => {
			if (!this.opened || previewId !== this.challengePreviewId) {
				sound.clean()
				return
			}
			this.challengePreview = sound
			this.challengePreview.playLoop(0, false, 0)
		}).catch(() => {})
	}
	stopChallengePreview() {
		this.challengePreviewId++
		if (this.challengePreview) {
			this.challengePreview.stop()
			this.challengePreview.clean()
			this.challengePreview = null
		}
	}
	onStart(event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		if (!this.data || !this.data.current || !this.data.current.song) {
			return
		}
		if (!account.loggedIn) {
			this.setStatus(strings.weeklyChallenge.loginRequired)
			return
		}
		this.startButton.disabled = true
		var challenge = this.data.current
		var song = WeeklyChallenge.prepareSongAsset(challenge.song)
		if (!song || !song.courses || !song.courses.oni) {
			this.setStatus(strings.weeklyChallenge.noChallenge, true)
			this.startButton.disabled = false
			return
		}
		this.skipRestoreAudio = true
		this.remove()
		this.songSelect.startWeeklyChallenge(challenge, song)
	}
	onClick(event) {
		if ((event.target.id === "weekly-challenge-container" || event.target.id === "weekly-challenge-close") && (event.which === 1 || event.type === "touchstart")) {
			event.preventDefault()
			this.remove(true)
		}
	}
	keyPress(pressed, name) {
		if (!pressed) {
			return
		}
		if (name === "back") {
			this.remove(true)
		} else if (name === "confirm" && this.data && this.data.current) {
			this.onStart()
		}
	}
	redraw() {
		if (this.opened && this.container) {
			var vmin = Math.min(innerWidth, lastHeight) / 100
			if (this.vmin !== vmin) {
				this.container.style.setProperty("--vmin", vmin + "px")
				this.vmin = vmin
			}
		} else {
			this.vmin = null
		}
	}
	remove(byUser) {
		if (!this.opened) {
			return
		}
		this.opened = false
		this.fetchId++
		if (this.fetchController) this.fetchController.abort()
		this.fetchController = null
		this.stopCountdown()
		if (byUser) {
			this.songSelect.playSound("se_cancel")
		}
		this.stopChallengePreview()
		pageEvents.remove(this.container, ["mousedown", "touchstart"])
		pageEvents.remove(this.startButton, ["click", "touchstart"])
		this.div.remove()
		delete this.div
		delete this.container
		delete this.startButton
		this.data = null
		cancelTouch = true
		noResizeRoot = false
		if (this.skipRestoreAudio) {
			this.restoreAudio = null
			this.skipRestoreAudio = false
		} else {
			this.restoreSongSelectAudio()
		}
	}
	clean() {
		this.skipRestoreAudio = true
		this.remove()
		delete this.songSelect
	}
	static prepareSongAsset(song) {
		var existing = assets.songs.find(item => item.id === song.id)
		if (existing) {
			return existing
		}
		var directory = gameConfig.songs_baseurl + song.id + "/"
		var songExt = song.music_type ? song.music_type : "mp3"
		song.music = new RemoteFile(directory + "main." + songExt)
		if (song.type === "tja") {
			song.chart = new RemoteFile(directory + "main.tja")
		} else {
			song.chart = { separateDiff: true }
			for (var diff in song.courses) {
				if (song.courses[diff]) {
					song.chart[diff] = new RemoteFile(directory + diff + ".osu")
				}
			}
		}
		if (song.lyrics) {
			song.lyricsFile = new RemoteFile(directory + "main.vtt")
		}
		if (song.preview > 0) {
			song.previewMusic = new RemoteFile(directory + "preview." + gameConfig.preview_type)
		}
		assets.songs.push(song)
		return song
	}
	static fixedOptions() {
		return {
			baisoku: "1",
			doron: "false",
			abekobe: "false",
			detarame: "0"
		}
	}
	static fixedEasySettings() {
		return {
			playbackRate: 1,
			baisoku: 1,
			doron: false,
			abekobe: false,
			detarame: false
		}
	}
	static lockEasySettings() {
		var easySettings = typeof window !== "undefined" && window.EasySettings
		if (!easySettings || typeof easySettings.getSettings !== "function" || typeof easySettings.saveSettings !== "function") {
			return
		}
		try {
			if (!sessionStorage.getItem("weeklyChallengeEasySettings")) {
				sessionStorage.setItem("weeklyChallengeEasySettings", JSON.stringify(easySettings.getSettings()))
			}
		} catch (e) { }
		easySettings.saveSettings(Object.assign(
			{},
			easySettings.getSettings(),
			WeeklyChallenge.fixedEasySettings()
		), true)
	}
	static restoreEasySettings() {
		var easySettings = typeof window !== "undefined" && window.EasySettings
		if (!easySettings || typeof easySettings.saveSettings !== "function") {
			return
		}
		var raw = null
		try {
			raw = sessionStorage.getItem("weeklyChallengeEasySettings")
		} catch (e) { }
		if (!raw) {
			return
		}
		try {
			easySettings.saveSettings(JSON.parse(raw), true)
			sessionStorage.removeItem("weeklyChallengeEasySettings")
		} catch (e) { }
	}
	static lockOptions() {
		var backup = null
		try {
			backup = sessionStorage.getItem("weeklyChallengeOptions")
		} catch (e) { }
		if (!backup) {
			backup = {}
			Object.keys(WeeklyChallenge.fixedOptions()).forEach(key => {
				backup[key] = {
					hasValue: localStorage.getItem(key) !== null,
					value: localStorage.getItem(key)
				}
			})
			try {
				sessionStorage.setItem("weeklyChallengeOptions", JSON.stringify(backup))
			} catch (e) { }
		}
		Object.keys(WeeklyChallenge.fixedOptions()).forEach(key => {
			localStorage.setItem(key, WeeklyChallenge.fixedOptions()[key])
		})
		WeeklyChallenge.lockEasySettings()
	}
	static restoreOptions() {
		var raw = null
		try {
			raw = sessionStorage.getItem("weeklyChallengeOptions")
		} catch (e) { }
		if (!raw) {
			WeeklyChallenge.restoreEasySettings()
			return
		}
		try {
			var backup = JSON.parse(raw)
			Object.keys(backup).forEach(key => {
				if (backup[key].hasValue) {
					localStorage.setItem(key, backup[key].value)
				} else {
					localStorage.removeItem(key)
				}
			})
			sessionStorage.removeItem("weeklyChallengeOptions")
		} catch (e) { }
		WeeklyChallenge.restoreEasySettings()
	}
	static markRun(challenge, song) {
		var run = {
			challenge_id: challenge.challenge_id,
			song_id: song.id,
			song_hash: challenge.song_hash || song.hash,
			difficulty: challenge.difficulty || "oni"
		}
		window.weeklyChallengeRun = run
		try {
			sessionStorage.setItem("weeklyChallengeRun", JSON.stringify(run))
		} catch (e) { }
		WeeklyChallenge.lockOptions()
	}
	static getRun() {
		if (window.weeklyChallengeRun) {
			return window.weeklyChallengeRun
		}
		try {
			var raw = sessionStorage.getItem("weeklyChallengeRun")
			if (raw) {
				window.weeklyChallengeRun = JSON.parse(raw)
				return window.weeklyChallengeRun
			}
		} catch (e) { }
		return null
	}
	static clearRun() {
		delete window.weeklyChallengeRun
		try {
			sessionStorage.removeItem("weeklyChallengeRun")
		} catch (e) { }
		WeeklyChallenge.restoreOptions()
	}
	static isActiveController(controller) {
		var run = WeeklyChallenge.getRun()
		return !!(
			run &&
			controller &&
			controller.selectedSong &&
			controller.selectedSong.weeklyChallenge &&
			controller.selectedSong.folder === run.song_id &&
			controller.selectedSong.hash === run.song_hash &&
			controller.selectedSong.difficulty === run.difficulty
		)
	}
	static submitResult(controller, result) {
		if (!WeeklyChallenge.isActiveController(controller) || controller.autoPlayEnabled || !account.loggedIn) {
			return Promise.resolve(null)
		}
		var run = WeeklyChallenge.getRun()
		var clearRun = false
		var controller = new AbortController()
		var timeout = setTimeout(() => controller.abort(), 12000)
		return loader.getCsrfToken().then(token => {
			return fetch("api/weekly-challenge/submit", {
				method: "POST",
				signal: controller.signal,
				headers: {
					"Content-Type": "application/json",
					"X-CSRFToken": token
				},
				body: JSON.stringify({
					challenge_id: run.challenge_id,
					hash: run.song_hash,
					difficulty: run.difficulty,
					score: result.points,
					good: result.good,
					ok: result.ok,
					bad: result.bad,
					max_combo: result.maxCombo,
					drumroll: result.drumroll
				})
			})
		}).then(response => {
			if (!response.ok) throw new Error("HTTP " + response.status)
			return response.json()
		}).then(data => {
			if (data.status !== "ok") {
				if (data.message === "challenge_not_active") clearRun = true
				throw new Error(data.message || "submit_failed")
			}
			clearRun = true
			return data
		}).catch(error => {
			console.error("Weekly challenge submit failed:", error)
		}).finally(() => {
			clearTimeout(timeout)
			if (clearRun) WeeklyChallenge.clearRun()
		})
	}
}
