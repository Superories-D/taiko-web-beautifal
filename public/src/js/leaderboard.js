class Leaderboard {
	constructor() {
		this.visible = false
		this.period = "monthly"
		this.difficulty = ""
		this.difficulties = ["", "oni", "ura", "hard", "normal", "easy"]
	}

	anonymousId() {
		var key = "leaderboardAnonymousId"
		var id = localStorage.getItem(key)
		if(!id) {
			id = "anon_" + Math.random().toString(36).slice(2) + Date.now().toString(36)
			localStorage.setItem(key, id)
		}
		return id
	}

	async show(songHash, songTitle, difficulty) {
		this.songHash = songHash
		this.songTitle = songTitle
		this.difficulty = difficulty || ""
		this.mode = "normal"
		this.visible = true

		this.overlay = document.createElement("div")
		this.overlay.id = "leaderboard-overlay"
		this.overlay.innerHTML = this.shell()
		document.body.appendChild(this.overlay)
		this.bind()
		await this.fetchData()
	}

	async showDaily(date) {
		this.mode = "daily"
		this.dailyDate = date || ""
		this.visible = true

		this.overlay = document.createElement("div")
		this.overlay.id = "leaderboard-overlay"
		this.overlay.innerHTML = this.dailyShell()
		document.body.appendChild(this.overlay)
		this.bindDaily()
		await this.fetchDailyData()
	}

	shell() {
		return `
			<div class="leaderboard-container" role="dialog" aria-modal="true">
				<div class="leaderboard-header">
					<button class="leaderboard-back" type="button">${strings.back}</button>
					<h2 class="leaderboard-title">${this.escapeHtml(strings.leaderboardTitle.replace("%s", this.songTitle))}</h2>
				</div>
				<div class="leaderboard-tabs">
					${["monthly", "weekly", "all"].map(period => `<button class="leaderboard-tab ${period === this.period ? "active" : ""}" data-period="${period}" type="button">${this.periodLabel(period)}</button>`).join("")}
				</div>
				<div class="leaderboard-diffs">
					${this.difficulties.map(diff => `<button class="leaderboard-diff ${diff === this.difficulty ? "active" : ""}" data-difficulty="${diff}" type="button">${this.diffLabel(diff)}</button>`).join("")}
				</div>
				<div class="leaderboard-content"><div class="leaderboard-loading">${strings.loading}</div></div>
				<div class="leaderboard-footer">
					<span class="leaderboard-total"></span>
					<span class="leaderboard-user-rank"></span>
				</div>
			</div>
		`
	}

	dailyShell() {
		return `
			<div class="leaderboard-container leaderboard-daily" role="dialog" aria-modal="true">
				<div class="leaderboard-header">
					<button class="leaderboard-back" type="button">${strings.back}</button>
					<h2 class="leaderboard-title">${strings.dailyChallengeHistory}</h2>
				</div>
				<div class="leaderboard-date-tabs"></div>
				<div class="leaderboard-content"><div class="leaderboard-loading">${strings.loading}</div></div>
				<div class="leaderboard-footer">
					<span class="leaderboard-total"></span>
					<span class="leaderboard-user-rank"></span>
				</div>
			</div>
		`
	}

	bind() {
		this.overlay.querySelector(".leaderboard-back").addEventListener("click", () => this.hide())
		this.overlay.addEventListener("click", event => {
			if(event.target === this.overlay) {
				this.hide()
			}
			if(event.target.dataset.period) {
				this.period = event.target.dataset.period
				this.refreshControls()
				this.fetchData()
			}
			if("difficulty" in event.target.dataset) {
				this.difficulty = event.target.dataset.difficulty
				this.refreshControls()
				this.fetchData()
			}
		})
		this.keyHandler = event => {
			if(event.key === "Escape") {
				this.hide()
			}
		}
		document.addEventListener("keydown", this.keyHandler)
	}

	bindDaily() {
		this.overlay.querySelector(".leaderboard-back").addEventListener("click", () => this.hide())
		this.overlay.addEventListener("click", event => {
			if(event.target === this.overlay) {
				this.hide()
			}
			var tab = event.target.closest(".leaderboard-date-tab")
			if(tab) {
				this.dailyDate = tab.dataset.date
				this.fetchDailyData()
			}
		})
		this.keyHandler = event => {
			if(event.key === "Escape") {
				this.hide()
			}
		}
		document.addEventListener("keydown", this.keyHandler)
	}

	refreshControls() {
		this.overlay.querySelectorAll(".leaderboard-tab").forEach(btn => {
			btn.classList.toggle("active", btn.dataset.period === this.period)
		})
		this.overlay.querySelectorAll(".leaderboard-diff").forEach(btn => {
			btn.classList.toggle("active", btn.dataset.difficulty === this.difficulty)
		})
	}

	async fetchData() {
		var content = this.overlay.querySelector(".leaderboard-content")
		content.innerHTML = `<div class="leaderboard-loading">${strings.loading}</div>`
		try {
			var url = `api/leaderboard/get?hash=${encodeURIComponent(this.songHash)}&difficulty=${encodeURIComponent(this.difficulty)}&period=${encodeURIComponent(this.period)}&anonymous_id=${encodeURIComponent(this.anonymousId())}`
			var response = await fetch(url)
			var data = await response.json()
			if(data.status !== "ok") {
				throw new Error("bad_status")
			}
			this.render(data)
		} catch(e) {
			this.renderError()
		}
	}

	async fetchDailyData() {
		var content = this.overlay.querySelector(".leaderboard-content")
		content.innerHTML = `<div class="leaderboard-loading">${strings.loading}</div>`
		try {
			var suffix = this.dailyDate ? `?date=${encodeURIComponent(this.dailyDate)}` : ""
			var response = await fetch(`api/daily-challenge/leaderboard${suffix}`)
			var data = await response.json()
			if(data.status !== "ok") {
				throw new Error("bad_status")
			}
			this.renderDaily(data)
		} catch(e) {
			this.renderError()
		}
	}

	render(data) {
		var content = this.overlay.querySelector(".leaderboard-content")
		this.overlay.querySelector(".leaderboard-total").textContent = (data.total_scores || 0) + " scores"
		this.overlay.querySelector(".leaderboard-user-rank").textContent = data.my_rank ? strings.yourRank + ": #" + data.my_rank : ""
		if(!data.leaderboard || data.leaderboard.length === 0) {
			content.innerHTML = `<div class="leaderboard-empty"><div class="leaderboard-empty-art"></div><div>${strings.noScores}</div></div>`
			return
		}
		content.innerHTML = `<ul class="leaderboard-list">${data.leaderboard.map(entry => this.item(entry)).join("")}</ul>`
	}

	item(entry) {
		var rankClass = entry.rank <= 3 ? `rank-${entry.rank}` : ""
		return `
			<li class="leaderboard-item ${rankClass}">
				<span class="leaderboard-rank">#${entry.rank}</span>
				<span class="leaderboard-name">${this.escapeHtml(entry.display_name)}</span>
				<span class="leaderboard-score">${Number(entry.score_value || 0).toLocaleString()} ${strings.points}</span>
			</li>
		`
	}

	renderDaily(data) {
		var tabs = this.overlay.querySelector(".leaderboard-date-tabs")
		var content = this.overlay.querySelector(".leaderboard-content")
		this.dailyDate = data.date
		tabs.innerHTML = (data.dates || []).map(day => `
			<button class="leaderboard-date-tab ${day.date === data.date ? "active" : ""}" data-date="${day.date}" type="button">${day.date}</button>
		`).join("")
		this.overlay.querySelector(".leaderboard-total").textContent = (data.leaderboard || []).length + " scores"
		this.overlay.querySelector(".leaderboard-user-rank").textContent = data.date || ""

		var title = data.challenge && data.challenge.song ? data.challenge.song.title : strings.dailyChallenge
		var html = `
			<div class="daily-challenge-song">
				<div class="daily-challenge-label">${strings.dailyChallenge}</div>
				<div class="daily-challenge-title">${this.escapeHtml(title || "")}</div>
				<div class="daily-challenge-meta">${this.escapeHtml(data.date || "")} · ${strings.oni}</div>
			</div>
		`
		if(!data.leaderboard || data.leaderboard.length === 0) {
			content.innerHTML = html + `<div class="leaderboard-empty"><div class="leaderboard-empty-art"></div><div>${strings.noScores}</div></div>`
			return
		}
		html += `<ul class="leaderboard-list">${data.leaderboard.map(entry => this.dailyItem(entry)).join("")}</ul>`
		content.innerHTML = html
	}

	dailyItem(entry) {
		var rankClass = entry.rank <= 3 ? `rank-${entry.rank}` : (entry.rank <= 10 ? "rank-top-10" : "")
		var badge = entry.rank <= 3 ? "&#9819; " : (entry.rank <= 10 ? "&#9733; " : "")
		return `
			<li class="leaderboard-item ${rankClass}">
				<span class="leaderboard-rank">${badge}#${entry.rank}</span>
				<span class="leaderboard-name">${this.escapeHtml(entry.display_name)}</span>
				<span class="leaderboard-score">${Number(entry.score_value || 0).toLocaleString()} ${strings.points}</span>
			</li>
		`
	}

	renderError() {
		var content = this.overlay.querySelector(".leaderboard-content")
		content.innerHTML = `<div class="leaderboard-error"><div>${strings.errorOccured}</div><button class="leaderboard-retry" type="button">Retry</button></div>`
		content.querySelector(".leaderboard-retry").addEventListener("click", () => {
			if(this.mode === "daily") {
				this.fetchDailyData()
			} else {
				this.fetchData()
			}
		})
	}

	async submitWithName(hash, difficulty, score, defaultName) {
		var displayName = await this.askName(defaultName)
		if(displayName === null) {
			return null
		}
		localStorage.setItem("leaderboardName", displayName)
		var response = await fetch("api/leaderboard/submit", {
			method: "POST",
			headers: {"Content-Type": "application/json"},
			body: JSON.stringify({
				hash: hash,
				difficulty: difficulty,
				score: score,
				display_name: displayName,
				anonymous_id: this.anonymousId()
			})
		})
		var data = await response.json()
		if(data.status !== "ok") {
			throw new Error("leaderboard_submit_failed")
		}
		return data
	}

	askName(defaultName) {
		return new Promise(resolve => {
			var overlay = document.createElement("div")
			overlay.id = "leaderboard-submit-overlay"
			overlay.innerHTML = `
				<form class="leaderboard-submit">
					<h3>${strings.leaderboard}</h3>
					<p>${strings.enterName}</p>
					<input name="displayName" maxlength="20" autocomplete="nickname">
					<div class="leaderboard-submit-actions">
						<button type="button" data-cancel>${strings.cancel}</button>
						<button type="submit">${strings.yourRank}</button>
					</div>
				</form>
			`
			document.body.appendChild(overlay)
			var input = overlay.querySelector("input")
			input.value = localStorage.getItem("leaderboardName") || defaultName || ""
			input.focus()
			overlay.querySelector("[data-cancel]").addEventListener("click", () => {
				overlay.remove()
				resolve(null)
			})
			overlay.querySelector("form").addEventListener("submit", event => {
				event.preventDefault()
				var name = input.value.trim().slice(0, 20) || "Anonymous"
				overlay.remove()
				resolve(name)
			})
		})
	}

	resultCard(message, action) {
		var old = document.querySelector(".leaderboard-result-card")
		if(old) old.remove()
		var card = document.createElement("div")
		card.className = "leaderboard-result-card"
		card.innerHTML = `<strong>${strings.leaderboard}</strong><div>${this.escapeHtml(message)}</div>`
		if(action) {
			var actions = document.createElement("div")
			actions.className = "leaderboard-result-actions"
			var button = document.createElement("button")
			button.type = "button"
			button.textContent = strings.leaderboard
			button.addEventListener("click", action)
			actions.appendChild(button)
			card.appendChild(actions)
		}
		document.body.appendChild(card)
		setTimeout(() => {
			if(card.parentNode) card.remove()
		}, 9000)
	}

	periodLabel(period) {
		return ({monthly: "Monthly", weekly: "Weekly", all: "All-Time"})[period]
	}

	diffLabel(diff) {
		return diff ? strings[diff === "ura" ? "oni" : diff] + (diff === "ura" ? " Ura" : "") : "All"
	}

	escapeHtml(str) {
		return String(str || "").replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
	}

	hide() {
		if(this.overlay) {
			this.overlay.remove()
			this.overlay = null
		}
		if(this.keyHandler) {
			document.removeEventListener("keydown", this.keyHandler)
			this.keyHandler = null
		}
		this.visible = false
	}
}

var leaderboard = new Leaderboard()
