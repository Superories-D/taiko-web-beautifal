/* Chart feedback, compact hit analysis and the result-page practice bridge. */
class PerformanceAnalytics {
	static createTracker(circles, count) {
		var notes = (Array.isArray(circles) ? circles : []).filter(circle => circle && ["don", "ka", "daiDon", "daiKa"].indexOf(circle.type) !== -1)
		var end = notes.reduce((max, circle) => Math.max(max, Number(circle.ms) || 0), 0)
		var bucketCount = count || 20
		var size = Math.max(1, Math.ceil((end + 1) / bucketCount))
		var buckets = Array.from({length: bucketCount}, (_, index) => ({
			start_ms: index * size,
			end_ms: Math.min((index + 1) * size, end + 1),
			good: 0, ok: 0, bad: 0, offset_sum_ms: 0, offset_count: 0
		}))
		return {buckets: buckets, end: end, notes: notes.length, record: function (score, circle, offset) {
			var ms = Math.max(0, Number(circle && circle.ms) || 0)
			var index = Math.min(bucketCount - 1, Math.floor(ms / size))
			var bucket = buckets[index]
			if (score === 450) bucket.good++
			else if (score === 230) bucket.ok++
			else bucket.bad++
			if (typeof offset === "number" && isFinite(offset)) {
				bucket.offset_sum_ms += Math.max(-1000, Math.min(1000, Math.round(offset)))
				bucket.offset_count++
			}
		}}
	}

	static finish(controller, score) {
		var tracker = controller && controller.game && controller.game.performanceTracker
		if (!tracker || !score || !Number.isFinite(Number(score.points))) return null
		var result = {
			run_id: this.randomId(),
			song_hash: String(controller.selectedSong.hash || controller.selectedSong.id),
			difficulty: String(score.difficulty || controller.selectedSong.difficulty || "oni"),
			score: Math.max(0, Math.round(Number(score.points) || 0)),
			good: Math.max(0, Math.round(Number(score.good) || 0)),
			ok: Math.max(0, Math.round(Number(score.ok) || 0)),
			bad: Math.max(0, Math.round(Number(score.bad) || 0)),
			max_combo: Math.max(0, Math.round(Number(score.maxCombo) || 0)),
			drumroll: Math.max(0, Math.round(Number(score.drumroll) || 0)),
			gauge: Math.max(0, Math.min(10000, Math.round(Number(score.gauge) || 0))),
			buckets: tracker.buckets,
			rule_version: "standard-v1"
		}
		var total = result.good + result.ok + result.bad
		result.accuracy = total ? (result.good + result.ok * 0.55) / total : 0
		result.worst = this.worstBucket(result)
		return result
	}

	static worstBucket(result) {
		var weakest = null
		;(result.buckets || []).forEach(bucket => {
			var total = bucket.good + bucket.ok + bucket.bad
			if (!total) return
			var accuracy = (bucket.good + bucket.ok * 0.55) / total
			if (!weakest || accuracy < weakest.accuracy) weakest = {start_ms: bucket.start_ms, end_ms: bucket.end_ms, accuracy: accuracy}
		})
		return weakest
	}

	static randomId() {
		if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "")
		return (Date.now().toString(16) + Math.random().toString(16).slice(2)).padEnd(32, "0").slice(0, 32)
	}
}

class FeedbackAnalytics {
	constructor(songSelect) {
		this.songSelect = songSelect || null
		this.overlay = null
		this.resultController = null
	}

	labels() {
		return (typeof strings !== "undefined" && strings.feedbackAnalytics) || {
			title: "Chart feedback", analysis: "Performance analysis", rating: "Rate this chart",
			report: "Report a problem", login: "Sign in to rate or report.", playRequired: "Complete a standard play first.",
			noRating: "No ratings yet", submit: "Submit", close: "Close", stars: "stars", accuracy: "Accuracy",
			weakest: "Weakest section", practice: "Practice this section", sync: "Audio sync", readability: "Readability",
			fun: "Fun", difficulty: "Difficulty", reason: "Reason", details: "Details", position: "Position (seconds)",
			thanks: "Thanks for the feedback.", reportSent: "Report submitted.", history: "Recent runs", unavailable: "Feedback is temporarily unavailable."
		}
	}

	static isEligible(controller) {
		return !!(controller && !controller.multiplayer && !controller.autoPlayEnabled &&
			!controller.aiBattle && !controller.ghostBattle && !controller.practiceMode &&
			(!controller.isLeaderboardEligible || controller.isLeaderboardEligible()))
	}

	static saveLocal(result) {
		try {
			var key = "taikoPerformanceRuns.v1"
			var state = JSON.parse(localStorage.getItem(key) || "{}") || {}
			var songKey = result.song_hash + ":" + result.difficulty
			state[songKey] = [result].concat(Array.isArray(state[songKey]) ? state[songKey] : []).slice(0, 30)
			localStorage.setItem(key, JSON.stringify(state))
		} catch (_error) {}
	}

	static loadLocalRuns(songHash, difficulty) {
		try {
			if (typeof localStorage === "undefined") return []
			var state = JSON.parse(localStorage.getItem("taikoPerformanceRuns.v1") || "{}") || {}
			var rows = state[String(songHash) + ":" + String(difficulty)]
			return Array.isArray(rows) ? rows.filter(row => row && row.song_hash && row.difficulty) : []
		} catch (_error) {
			return []
		}
	}

	static async syncRun(result, controller) {
		if (typeof account === "undefined" || !account.loggedIn || !this.isEligible(controller)) return false
		try {
			var token = typeof loader !== "undefined" && loader.getCsrfToken ? await loader.getCsrfToken() : null
			var headers = {"Content-Type": "application/json"}
			if (token) headers["X-CSRFToken"] = token
			var payload = {
				run_id: result.run_id, song_hash: result.song_hash, difficulty: result.difficulty,
				score: result.score, good: result.good, ok: result.ok, bad: result.bad,
				max_combo: result.max_combo, drumroll: result.drumroll, gauge: result.gauge,
				buckets: result.buckets, rule_version: result.rule_version
			}
			var response = await fetch("api/performance/runs", {method: "POST", credentials: "same-origin", headers: headers, body: JSON.stringify(payload)})
			return response.ok
		} catch (_error) { return false }
	}

	static complete(controller, score) {
		var result = PerformanceAnalytics.finish(controller, score)
		if (!result) return null
		result.eligible = this.isEligible(controller)
		if (result.eligible) {
			this.saveLocal(result)
			this.syncRun(result, controller).catch(() => {})
		}
		return result
	}

	static api(path, options) {
		options = options || {}
		options.credentials = "same-origin"
		options.headers = Object.assign({}, options.headers || {})
		if (options.body && typeof options.body !== "string") {
			options.headers["Content-Type"] = "application/json"
			options.body = JSON.stringify(options.body)
		}
		var tokenPromise = options.method && options.method !== "GET" && typeof loader !== "undefined" && loader.getCsrfToken ? loader.getCsrfToken() : Promise.resolve(null)
		return tokenPromise.then(token => {
			if (token) options.headers["X-CSRFToken"] = token
			return fetch(path, options).then(response => response.json().catch(() => ({})).then(data => {
				if (!response.ok) throw new Error(data.message || data.error || "request_failed")
				return data
			}))
		})
	}

	static finishResult(controller, score) {
		var result = this.complete(controller, score)
		if (result && result.eligible) {
			var ui = new FeedbackAnalytics()
			ui.showResult(controller, result)
		}
		return result
	}

	ensureOverlay() {
		if (!this.overlay) this.overlay = document.getElementById("feedback-analytics-overlay")
		if (this.overlay && this.overlay.parentNode) return this.overlay
		this.overlay = document.createElement("div")
		this.overlay.id = "feedback-analytics-overlay"
		this.overlay.hidden = true
		this.overlay.addEventListener("click", event => { if (event.target === this.overlay) this.close() })
		document.body.appendChild(this.overlay)
		return this.overlay
	}

	close() {
		if (this.overlay) this.overlay.hidden = true
	}

	showResult(controller, result) {
		this.resultController = controller
		var host = document.getElementById("game") || document.body
		var old = document.getElementById("feedback-result-button")
		if (old && old.parentNode) old.parentNode.removeChild(old)
		var button = document.createElement("button")
		button.id = "feedback-result-button"
		button.type = "button"
		button.textContent = this.labels().analysis
		button.addEventListener("click", event => { event.stopPropagation(); this.showRun(result) })
		host.appendChild(button)
	}

	showRun(result) {
		var labels = this.labels(), overlay = this.ensureOverlay()
		overlay.innerHTML = ""
		var panel = document.createElement("section")
		panel.id = "feedback-analytics-panel"
		panel.setAttribute("role", "dialog")
		panel.setAttribute("aria-modal", "true")
		var heading = document.createElement("h2"); heading.textContent = labels.analysis; panel.appendChild(heading)
		var close = document.createElement("button"); close.type = "button"; close.className = "feedback-close"; close.textContent = "×"; close.title = labels.close; close.addEventListener("click", () => this.close()); panel.appendChild(close)
		var summary = document.createElement("div"); summary.className = "feedback-summary"
		summary.innerHTML = "<strong>" + Math.round(result.accuracy * 1000) / 10 + "%</strong><span>" + labels.accuracy + "</span><strong>" + result.max_combo + "</strong><span>Max combo</span><strong>" + result.score.toLocaleString() + "</strong><span>Score</span>"
		panel.appendChild(summary)
		var heat = document.createElement("div"); heat.className = "feedback-heatmap"; heat.setAttribute("aria-label", labels.accuracy)
		;(result.buckets || []).forEach(bucket => {
			var total = bucket.good + bucket.ok + bucket.bad, accuracy = total ? (bucket.good + bucket.ok * 0.55) / total : 1
			var cell = document.createElement("span"); cell.className = accuracy >= .9 ? "good" : accuracy >= .7 ? "ok" : "bad"; cell.style.height = Math.max(8, Math.round(accuracy * 100)) + "%"; cell.title = Math.round(accuracy * 100) + "%"
			heat.appendChild(cell)
		})
		panel.appendChild(heat)
		var weakest = document.createElement("p"); weakest.className = "feedback-weakest"
		if (result.worst) {
			weakest.textContent = labels.weakest + ": " + (result.worst.start_ms / 1000).toFixed(1) + "s – " + (result.worst.end_ms / 1000).toFixed(1) + "s"
			var practice = document.createElement("button"); practice.type = "button"; practice.textContent = labels.practice; practice.addEventListener("click", () => this.setPractice(result, result.worst)); weakest.appendChild(practice)
		} else weakest.textContent = labels.weakest + ": —"
		panel.appendChild(weakest)
		var chart = document.createElement("div"); chart.className = "feedback-chart-slot"; panel.appendChild(chart)
		var actions = document.createElement("div"); actions.className = "feedback-actions"
		var feedbackButton = document.createElement("button"); feedbackButton.type = "button"; feedbackButton.textContent = labels.rating + " / " + labels.report; feedbackButton.addEventListener("click", async () => {
			feedbackButton.disabled = true
			feedbackButton.textContent = labels.rating + " / " + labels.report + "…"
			try { await this.loadChartFeedback(result, panel) } finally {
				feedbackButton.disabled = false
				feedbackButton.textContent = labels.rating + " / " + labels.report
			}
		}); actions.appendChild(feedbackButton); panel.appendChild(actions)
		overlay.appendChild(panel); overlay.hidden = false
		this.loadChartFeedback(result, panel).catch(() => {})
		if (!result.score) this.loadHistory(result, panel).catch(() => {})
	}

	setPractice(result, weakest) {
		try {
			var state = PlayerLab.loadState()
			state.practice = {songId: this.resultController && (this.resultController.selectedSong.id || this.resultController.selectedSong.folder), start: weakest.start_ms / 1000, end: weakest.end_ms / 1000, loop: true}
			PlayerLab.saveState(state)
			var node = document.querySelector(".feedback-weakest")
			if (node) node.appendChild(document.createTextNode(" ✓"))
		} catch (_error) {}
	}

	async loadChartFeedback(result, panel) {
		var labels = this.labels(), data
		try { data = await FeedbackAnalytics.api("api/chart-feedback?hash=" + encodeURIComponent(result.song_hash) + "&difficulty=" + encodeURIComponent(result.difficulty)) } catch (_error) {
			var failed = panel.querySelector(".feedback-chart-feedback") || document.createElement("div")
			failed.className = "feedback-chart-feedback"
			failed.textContent = labels.unavailable
			if (!failed.parentNode) panel.appendChild(failed)
			return
		}
		var section = panel.querySelector(".feedback-chart-feedback")
		if (!section) { section = document.createElement("div"); section.className = "feedback-chart-feedback"; panel.appendChild(section) }
		section.innerHTML = ""
		var summary = data.summary || {}, title = document.createElement("h3"); title.textContent = labels.title; section.appendChild(title)
		var text = document.createElement("p"); text.textContent = summary.rating_avg ? summary.rating_avg + " / 5 (" + summary.rating_count + " " + labels.stars + ")" : labels.noRating; section.appendChild(text)
		if (typeof account === "undefined" || !account.loggedIn) { var login = document.createElement("p"); login.textContent = labels.login; section.appendChild(login); return }
		if (!data.eligible) { var required = document.createElement("p"); required.textContent = labels.playRequired; section.appendChild(required); return }
		var rating = document.createElement("div"); rating.className = "feedback-rating-input"; [1, 2, 3, 4, 5].forEach(star => { var button = document.createElement("button"); button.type = "button"; button.textContent = star + " ★"; button.dataset.stars = star; if (data.own_rating && Number(data.own_rating.stars) === star) button.classList.add("active"); button.addEventListener("click", () => this.submitRating(result, star, data.own_rating && data.own_rating.tag, section)); rating.appendChild(button) }); section.appendChild(rating)
		var tag = document.createElement("select"); tag.className = "feedback-tag"; [["", labels.title], ["sync", labels.sync], ["readability", labels.readability], ["fun", labels.fun], ["difficulty", labels.difficulty]].forEach(item => { var option = document.createElement("option"); option.value = item[0]; option.textContent = item[1]; if (data.own_rating && data.own_rating.tag === item[0]) option.selected = true; tag.appendChild(option) }); section.appendChild(tag); this.pendingTag = tag
		var report = document.createElement("form"); report.className = "feedback-report-form"; report.innerHTML = "<h3>" + labels.report + "</h3><select name=reason><option value=audio_sync>" + labels.sync + "</option><option value=invalid_notes>Invalid notes</option><option value=display>Display issue</option><option value=metadata>Metadata</option><option value=copyright>Copyright</option><option value=inappropriate>Inappropriate</option><option value=other>Other</option></select><input name=position_ms type=number min=0 step=0.1 placeholder='" + labels.position + "'><textarea name=description maxlength=300 placeholder='" + labels.details + "'></textarea><button type=submit>" + labels.submit + "</button>"; report.addEventListener("submit", event => { event.preventDefault(); this.submitReport(result, report) }); section.appendChild(report)
		this.loadOwnReports(result, section).catch(() => {})
	}

	async submitRating(result, stars, currentTag, section) {
		var tagSelect = section.querySelector(".feedback-tag")
		var tagValue = (tagSelect && tagSelect.value) || currentTag || null
		try { await FeedbackAnalytics.api("api/chart-feedback/rating", {method: "PUT", body: {song_hash: result.song_hash, difficulty: result.difficulty, stars: stars, tag: tagValue || null}}); var note = document.createElement("p"); note.textContent = this.labels().thanks; section.appendChild(note) } catch (_error) {}
	}

	async submitReport(result, form) {
		var fields = new FormData(form), position = fields.get("position_ms")
		try { await FeedbackAnalytics.api("api/chart-feedback/reports", {method: "POST", body: {song_hash: result.song_hash, difficulty: result.difficulty, reason: fields.get("reason"), position_ms: position === "" ? null : Math.round(Number(position) * 1000), description: fields.get("description") || ""}}); form.reset(); var note = document.createElement("p"); note.textContent = this.labels().reportSent; form.parentNode.appendChild(note) } catch (_error) {}
	}

	async loadOwnReports(result, section) {
		if (typeof account === "undefined" || !account.loggedIn) return
		var data = await FeedbackAnalytics.api("api/chart-feedback/reports/me")
		var rows = (data.reports || []).filter(row => row.song_hash === result.song_hash && row.difficulty === result.difficulty)
		if (!rows.length) return
		var title = document.createElement("h3"); title.textContent = "Your reports"; section.appendChild(title)
		var list = document.createElement("ul"); rows.slice(0, 5).forEach(row => { var item = document.createElement("li"); item.textContent = (row.reason || "other") + " · " + (row.status || "open") + (row.resolution ? " · " + row.resolution : ""); list.appendChild(item) }); section.appendChild(list)
	}

	async loadHistory(result, panel) {
		var section = document.createElement("div"); section.className = "feedback-history"; panel.appendChild(section)
		if (typeof account === "undefined" || !account.loggedIn) { section.textContent = this.labels().history + ": sign in to sync history."; return }
		try {
			var data = await FeedbackAnalytics.api("api/performance/history?hash=" + encodeURIComponent(result.song_hash) + "&difficulty=" + encodeURIComponent(result.difficulty) + "&limit=12")
			var rows = data.runs || [], title = document.createElement("h3"); title.textContent = this.labels().history; section.appendChild(title)
			if (!rows.length) { section.appendChild(document.createTextNode("No completed runs yet.")); return }
			var list = document.createElement("ul"); rows.forEach(row => { var item = document.createElement("li"); item.textContent = Math.round(Number(row.accuracy || 0) * 1000) / 10 + "% · " + Number(row.score || 0).toLocaleString() + " · " + (row.finished_at || ""); list.appendChild(item) }); section.appendChild(list)
		} catch (_error) { section.textContent = this.labels().history + ": unavailable." }
	}

	async displaySelected() {
		if (!this.songSelect || this.songSelect.state.screen !== "song") return
		var song = this.songSelect.songs[this.songSelect.selectedSong]
		if (!song || song.action) return
		var index = this.songSelect.selectedDiff - this.songSelect.diffOptions.length
		var difficulty = this.songSelect.difficultyId[index >= 0 && index < 5 ? index : 3]
		if (!song.courses || !song.courses[difficulty]) difficulty = Object.keys(song.courses || {})[0]
		if (!difficulty) return
		var songHash = String(song.hash || song.id)
		var preview = {song_hash: songHash, difficulty: difficulty, score: 0, accuracy: 0, max_combo: 0, buckets: []}
		var localRuns = FeedbackAnalytics.loadLocalRuns(songHash, difficulty)
		if (localRuns.length) {
			var localResult = localRuns[0]
			localResult.worst = localResult.worst || PerformanceAnalytics.worstBucket(localResult)
			this.showRun(localResult)
			return
		}
		this.showRun(preview)
		if (typeof account === "undefined" || !account.loggedIn) return
		try {
			var data = await FeedbackAnalytics.api("api/performance/history?hash=" + encodeURIComponent(songHash) + "&difficulty=" + encodeURIComponent(difficulty) + "&limit=1")
			var latest = data.runs && data.runs[0]
			if (!latest || !this.songSelect || this.songSelect.songs[this.songSelect.selectedSong] !== song) return
			latest.worst = PerformanceAnalytics.worstBucket(latest)
			this.showRun(latest)
		} catch (_error) {}
	}
}

if (typeof module !== "undefined") module.exports = {PerformanceAnalytics, FeedbackAnalytics}
