class WeeklyChallenge {
	constructor(...args) {
		this.init(...args)
	}
	init(songSelect) {
		this.songSelect = songSelect
		this.opened = false
		this.data = null
		this.container = null
	}
	display() {
		if (!account.loggedIn || this.opened) {
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
		if (this.songSelect.songs[this.songSelect.selectedSong].courses) {
			snd.previewGain.setVolumeMul(0.5)
		} else if (this.songSelect.bgmEnabled) {
			snd.musicGain.setVolumeMul(0.5)
		}
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
		fetch("api/weekly-challenge/leaderboards").then(response => response.json()).then(data => {
			if (data.status !== "ok") {
				this.setStatus(this.errorText(data.message), true)
				return
			}
			this.data = data
			this.render()
		}).catch(() => {
			this.setStatus(strings.errorOccured, true)
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
		this.renderBoard(".weekly-challenge-current-list", current.leaderboard)
		this.renderPrevious(this.data.previous)
		this.setStatus("")
		this.startButton.disabled = false
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
			label.innerText = strings.weeklyChallenge.noPrevious
			this.renderBoard(".weekly-challenge-previous-list", [])
		}
	}
	renderBoard(selector, entries) {
		var list = this.div.querySelector(":scope " + selector)
		list.innerHTML = ""
		if (!entries || !entries.length) {
			var empty = document.createElement("li")
			empty.className = "weekly-challenge-empty"
			empty.innerText = strings.noScores
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
	onStart(event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		if (!this.data || !this.data.current || !this.data.current.song) {
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
		if (byUser) {
			this.songSelect.playSound("se_cancel")
		}
		pageEvents.remove(this.container, ["mousedown", "touchstart"])
		pageEvents.remove(this.startButton, ["click", "touchstart"])
		this.div.remove()
		delete this.div
		delete this.container
		delete this.startButton
		this.data = null
		cancelTouch = true
		noResizeRoot = false
		if (this.songSelect.songs[this.songSelect.selectedSong].courses) {
			snd.previewGain.setVolumeMul(1)
		} else if (this.songSelect.bgmEnabled) {
			snd.musicGain.setVolumeMul(1)
		}
	}
	clean() {
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
	}
	static restoreOptions() {
		var raw = null
		try {
			raw = sessionStorage.getItem("weeklyChallengeOptions")
		} catch (e) { }
		if (!raw) {
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
		return loader.getCsrfToken().then(token => {
			return fetch("api/weekly-challenge/submit", {
				method: "POST",
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
		}).then(response => response.json()).catch(error => {
			console.error("Weekly challenge submit failed:", error)
		}).finally(() => {
			WeeklyChallenge.clearRun()
		})
	}
}
