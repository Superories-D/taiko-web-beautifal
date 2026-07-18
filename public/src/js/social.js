class SocialHub {
	constructor(songSelect) {
		this.songSelect = songSelect
		this.opened = false
		this.tab = "challenges"
		this.overlay = document.getElementById("social-overlay")
		this.panel = document.getElementById("social-panel")
		this.list = document.getElementById("social-list")
		this.status = document.getElementById("social-status")
		this.filter = document.getElementById("social-filter")
		this.closeButton = document.getElementById("social-close")
		this.tapCleanups = []
		this.challengeCache = []
		this.countdownTimer = null
		this.renderVersion = 0
		this.bind()
	}

	bind() {
		if (!this.overlay) return
		this.tapCleanups.push(hubBindTap(this.closeButton, event => this.remove(true)))
		this.tapCleanups.push(hubBindTap(this.overlay, event => { if (event.target === this.overlay) this.remove(true) }))
		this.tapCleanups.push(hubBindTap(this.panel, event => {
			var tab = event.target.closest("[data-social-tab]")
			if (tab) this.selectTab(tab.dataset.socialTab)
			var action = event.target.closest("[data-social-action]")
			if (action) this.action(action.dataset.socialAction, action.dataset.publicId, action.dataset.challengeId, action.dataset.following)
		}))
		pageEvents.add(this.filter, "input", () => this.render())
		this.countdownTimer = setInterval(() => this.updateCountdowns(), 1000)
		pageEvents.add(window, "keydown", event => {
			if (this.opened && event.key === "Escape") { event.preventDefault(); this.remove(true) }
		}, "social-escape")
		pageEvents.add(window, "login", () => { if (this.opened) this.render() }, "social-login")
	}

	display() {
		if (!this.overlay) return
		if (!account.loggedIn) {
			try {
				var song = this.songSelect && this.songSelect.songs[this.songSelect.selectedSong]
				localStorage.setItem("taikoPendingHub", "social")
				localStorage.setItem("taikoPendingHubState", JSON.stringify({songHash: song && String(song.hash || song.id)}))
			} catch (_error) {}
			if (this.songSelect && this.songSelect.toAccount) this.songSelect.toAccount()
			return
		}
		this.applyStrings()
		if (this.songSelect && this.songSelect.closeSongExtras) this.songSelect.closeSongExtras(this)
		this.opened = true
		this.overlay.hidden = false
		this.selectTab(this.tab)
		setTimeout(() => this.filter.focus(), 0)
		if (this.songSelect) this.songSelect.updateSearchButtonVisibility()
	}

	applyStrings() {
		var s = strings.librarySocial
		if (!s || !this.panel) return
		this.panel.querySelector("#social-title").textContent = s.socialTitle
		this.panel.querySelector('[data-social-tab="challenges"]').textContent = s.challenges
		this.panel.querySelector('[data-social-tab="following"]').textContent = s.following
		this.panel.querySelector('[data-social-tab="search"]').textContent = s.findPlayers
		this.panel.querySelector('[data-social-tab="blocked"]').textContent = s.blocked
		this.panel.querySelector("#social-tabs").setAttribute("aria-label", s.socialSections || s.socialTitle)
		this.filter.setAttribute("aria-label", s.searchPlayers || s.filter)
		this.closeButton.setAttribute("aria-label", s.close || "Close")
		this.closeButton.title = s.close || "Close"
	}

	remove() {
		if (!this.opened) return
		this.opened = false
		this.overlay.hidden = true
		if (this.songSelect) this.songSelect.updateSearchButtonVisibility()
	}

	clean() {
		this.remove()
		if (!this.overlay) return
		this.tapCleanups.splice(0).forEach(cleanup => cleanup())
		pageEvents.remove(this.filter, "input")
		pageEvents.remove(window, "keydown", "social-escape")
		pageEvents.remove(window, "login", "social-login")
		if (this.countdownTimer) clearInterval(this.countdownTimer)
		this.countdownTimer = null
	}

	selectTab(tab) {
		if (["challenges", "following", "search", "blocked"].indexOf(tab) === -1) tab = "challenges"
		this.tab = tab
		this.panel.querySelectorAll("[data-social-tab]").forEach(button => button.classList.toggle("active", button.dataset.socialTab === tab))
		this.filter.placeholder = tab === "search" ? (strings.librarySocial ? strings.librarySocial.searchPlayers : "Search players") : (strings.librarySocial ? strings.librarySocial.filter : "Filter")
		this.render()
	}

	async request(path, method, body) {
		var options = {method: method || "GET", credentials: "same-origin", headers: {"Accept": "application/json"}}
		if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body) }
		if (method && method !== "GET") options.headers["X-CSRFToken"] = await loader.getCsrfToken()
		var response = await fetch(path, options)
		var data = await response.json().catch(() => ({}))
		if (!response.ok || data.status === "error") throw data
		return data
	}

	async render() {
		if (!this.opened || !this.list) return
		var renderVersion = ++this.renderVersion
		this.list.innerHTML = ""
		this.setStatus(strings.librarySocial ? strings.librarySocial.loading : "Loading…")
		try {
			if (this.tab === "challenges") {
				var challenges = await this.request("api/challenges")
				this.renderChallenges(challenges.challenges || [])
			} else if (this.tab === "following") {
				var following = await this.request("api/social/following")
				this.renderUsers(following.users || [])
			} else if (this.tab === "blocked") {
				var blocked = await this.request("api/social/blocked")
				this.renderUsers(blocked.users || [])
			} else {
				var query = (this.filter.value || "").trim()
				var users = query.length >= 2 ? await this.request("api/social/users?q=" + encodeURIComponent(query)) : {users: []}
				if (renderVersion !== this.renderVersion || !this.opened) return
				this.renderUsers(users.users || [])
			}
			if (renderVersion !== this.renderVersion || !this.opened) return
			if (!this.list.children.length) this.list.innerHTML = '<div class="hub-empty">' + (strings.librarySocial ? strings.librarySocial.emptySocial : "Nothing here yet.") + "</div>"
			this.setStatus("")
		} catch (error) {
			this.setStatus(error && error.message === "not_logged_in" ? this.label("signInSocial", "Sign in to use friends and challenges.") : this.friendlyError(error), true)
		}
	}

	renderChallenges(challenges) {
		this.challengeCache = challenges
		var query = (this.filter.value || "").trim().toLowerCase()
		challenges.filter(challenge => !query || String(challenge.song_hash).toLowerCase().includes(query) || String(challenge.status).toLowerCase().includes(query)).forEach(challenge => {
			var card = document.createElement("article")
			card.className = "hub-card"
			var song = this.songSelect.songs.find(item => String(item.hash || item.id) === String(challenge.song_hash))
			var title = (song && (song.title || song.originalTitle) || challenge.song_hash) + " · " + String(challenge.difficulty || "oni").toUpperCase()
			var result = (challenge.results || []).map(item => (item.player && item.player.display_name || this.label("player", "Player")) + ": " + Number(item.score || 0).toLocaleString()).join("  ·  ")
			var canPlay = challenge.status === "pending" || challenge.status === "active"
			card.innerHTML = '<div class="hub-card-title">' + this.escape(title) + '</div><div class="hub-card-meta">' + this.escape(this.statusLabel(challenge.status)) + ' · ' + this.escape(result || this.label("noScores", "No scores yet")) + '</div><div class="hub-card-actions">' +
				(challenge.role === "recipient" && challenge.status === "pending" ? '<button type="button" data-social-action="accept" data-challenge-id="' + this.escape(challenge.challenge_id) + '">' + this.label("accept", "Accept") + '</button>' : '') +
				(canPlay ? '<button type="button" data-social-action="play" data-challenge-id="' + this.escape(challenge.challenge_id) + '">' + this.label("play", "Play") + '</button>' : '<button type="button" data-social-action="replay" data-challenge-id="' + this.escape(challenge.challenge_id) + '">' + this.label("replay", "Replay") + '</button>') +
				(challenge.role === "recipient" && challenge.status === "pending" ? '<button type="button" data-social-action="decline" data-challenge-id="' + this.escape(challenge.challenge_id) + '">' + this.label("decline", "Decline") + '</button>' : '') +
				(challenge.role === "sender" && challenge.status === "pending" ? '<button type="button" data-social-action="cancel" data-challenge-id="' + this.escape(challenge.challenge_id) + '">' + this.label("cancel", "Cancel") + '</button>' : '') + '</div>'
			var meta = card.querySelector(".hub-card-meta")
			var countdown = document.createElement("span")
			countdown.dataset.countdown = challenge.expires_at || ""
			meta.appendChild(countdown)
			this.list.appendChild(card)
		})
	}

	renderUsers(users) {
		users.forEach(user => {
			var card = document.createElement("article")
			card.className = "hub-card"
			if (user.blocked) {
				card.innerHTML = '<div class="hub-card-title">' + this.escape(user.display_name || this.label("player", "Player")) + '</div><div class="hub-card-meta">' + this.escape(user.public_id || "") + '</div><div class="hub-card-actions"><button type="button" data-social-action="unblock" data-public-id="' + this.escape(user.public_id) + '">' + this.label("unblock", "Unblock") + '</button></div>'
			} else card.innerHTML = '<div class="hub-card-title">' + this.escape(user.display_name || this.label("player", "Player")) + '</div><div class="hub-card-meta">' + this.escape(user.public_id || "") + '</div><div class="hub-card-actions">' +
				'<button type="button" data-social-action="follow" data-following="' + String(!!user.following) + '" data-public-id="' + this.escape(user.public_id) + '">' + (user.following ? this.label("unfollow", "Unfollow") : this.label("follow", "Follow")) + '</button>' +
				'<button type="button" data-social-action="challenge" data-public-id="' + this.escape(user.public_id) + '"' + (user.following ? '' : ' disabled') + '>' + this.label("challenge", "Challenge") + '</button>' +
				'<button type="button" data-social-action="profile" data-public-id="' + this.escape(user.public_id) + '">' + this.label("profile", "Profile") + '</button>' +
				'<button type="button" data-social-action="block" data-public-id="' + this.escape(user.public_id) + '">' + this.label("block", "Block") + '</button></div>'
			this.list.appendChild(card)
		})
	}

	async action(action, publicId, challengeId, following) {
		try {
			if (action === "follow") {
				await this.request("api/social/follow/" + encodeURIComponent(publicId), following === "true" ? "DELETE" : "POST", following === "true" ? undefined : {})
				this.render(); return
			}
			if (action === "accept") { await this.playChallenge(challengeId); return }
			if (action === "block") { await this.request("api/social/block/" + encodeURIComponent(publicId), "POST", {}); this.render(); return }
			if (action === "unblock") { await this.request("api/social/block/" + encodeURIComponent(publicId), "DELETE"); this.render(); return }
			if (action === "profile") { await this.showProfile(publicId); return }
			if (action === "decline") { await this.request("api/challenges/" + encodeURIComponent(challengeId) + "/decline", "POST", {}); this.render(); return }
			if (action === "cancel") { await this.request("api/challenges/" + encodeURIComponent(challengeId) + "/cancel", "POST", {}); this.render(); return }
			if (action === "challenge") { await this.createChallenge(publicId); return }
			if (action === "replay") {
				var replay = this.challengeCache.find(item => item.challenge_id === challengeId)
				if (replay) await this.replayChallenge(replay)
				return
			}
			if (action === "play") { await this.playChallenge(challengeId); }
		} catch (error) { this.setStatus(this.friendlyError(error), true) }
	}

	async showProfile(publicId) {
		var data = await this.request("api/social/profile/" + encodeURIComponent(publicId))
		var profile = data.profile || {}
		var stats = profile.challenge_stats || {}
		var scores = (profile.top_scores || []).map(item => this.escape(item.song_hash) + " " + this.escape(item.difficulty || "") + ": " + Number(item.score || 0).toLocaleString()).join("<br>")
		this.list.innerHTML = '<article class="hub-card hub-profile"><div class="hub-card-title">' + this.escape(profile.display_name || this.label("player", "Player")) + '</div><div class="hub-card-meta">' + this.escape(profile.public_id || "") + '</div><div>' + this.escape(profile.rank_summary || "") + '</div><div>' + this.escape(this.label("wins", "Wins")) + ' ' + Number(stats.wins || 0) + ' / ' + this.escape(this.label("losses", "Losses")) + ' ' + Number(stats.losses || 0) + '</div><div class="hub-profile-scores">' + (scores || this.escape(this.label("noPublicScores", "No public scores"))) + '</div></article>'
	}

	async replayChallenge(challenge) {
		var target = challenge.role === "sender" ? challenge.recipient : challenge.sender
		if (!target || !target.public_id) throw new Error("player_unavailable")
		await this.request("api/challenges", "POST", {
			recipient_public_id: target.public_id,
			song_hash: challenge.song_hash,
			difficulty: challenge.difficulty,
			rule_version: "standard-v1"
		})
		this.setStatus(this.label("sent", "Challenge sent"))
		this.selectTab("challenges")
	}

	async createChallenge(publicId) {
		var song = this.songSelect.songs[this.songSelect.selectedSong]
		if (!song || !song.courses) { this.setStatus(this.label("selectSongFirst", "Select a song first."), true); return }
		var difficulty = prompt(this.label("difficultyPrompt", "Difficulty (easy, normal, hard, oni, ura)"), "oni")
		if (["easy", "normal", "hard", "oni", "ura"].indexOf(difficulty) === -1 || !song.courses[difficulty]) return
		await this.request("api/challenges", "POST", {recipient_public_id: publicId, song_hash: String(song.hash || song.id), difficulty: difficulty, rule_version: "standard-v1"})
		this.setStatus(this.label("sent", "Challenge sent"))
		this.selectTab("challenges")
	}

	async playChallenge(id) {
		var data = await this.request("api/challenges/" + encodeURIComponent(id))
		var challenge = data.challenge
		if (["pending", "active"].indexOf(challenge.status) === -1) { this.setStatus(this.label("challengeClosed", "This challenge is closed."), true); return }
		if (challenge.opponent_result && challenge.opponent_result.ghost_payload) {
			challenge.opponentGhost = await PlayerLab.decompressGhost(challenge.opponent_result.ghost_payload)
		}
		var index = this.songSelect.songs.findIndex(song => String(song.hash || song.id) === String(challenge.song_hash))
		if (index === -1) { this.setStatus(this.label("songUnavailable", "This song is no longer available."), true); return }
		challenge.challenge = true
		if (typeof EasySettings !== "undefined") EasySettings.enforceMultiplayerSettings(true)
		SocialHub.activeChallenge = challenge
		this.remove(true)
		this.songSelect.setSelectedSong(index)
		this.songSelect.challengeRun = challenge
		this.songSelect.toSelectDifficulty()
	}

	static async submitChallengeResult(controller, results) {
		if (!controller || !controller.asyncChallenge || !controller.challengeGhostResult || !account.loggedIn) return false
		var payload = await PlayerLab.compressGhost(controller.challengeGhostResult)
		if (!payload) return false
		var token = await loader.getCsrfToken()
		var body = {
			score: Math.max(0, Math.round(Number(results.points) || 0)),
			good: Math.max(0, Math.round(Number(results.good) || 0)),
			ok: Math.max(0, Math.round(Number(results.ok) || 0)),
			bad: Math.max(0, Math.round(Number(results.bad) || 0)),
			max_combo: Math.max(0, Math.round(Number(results.maxCombo) || 0)),
			drumroll: Math.max(0, Math.round(Number(results.drumroll) || 0)),
			clear: !!controller.game.rules.clearReached(results.gauge),
			ghost_payload: payload,
			ghost_encoding: "gzip"
		}
		var response = await fetch("api/challenges/" + encodeURIComponent(controller.asyncChallenge.challenge_id) + "/result", {
			method: "POST", credentials: "same-origin",
			headers: {"Content-Type": "application/json", "X-CSRFToken": token}, body: JSON.stringify(body)
		})
		return response.ok
	}

	updateCountdowns() {
		if (!this.opened) return
		this.list.querySelectorAll("[data-countdown]").forEach(node => {
			var until = Date.parse(node.dataset.countdown)
			if (!Number.isFinite(until)) { node.textContent = ""; return }
			var seconds = Math.max(0, Math.floor((until - Date.now()) / 1000))
			var days = Math.floor(seconds / 86400); seconds %= 86400
			var hours = Math.floor(seconds / 3600); seconds %= 3600
			var minutes = Math.floor(seconds / 60)
			node.textContent = days ? " · " + days + this.label("dayShort", "d") + " " + hours + this.label("hourShort", "h") : " · " + hours + this.label("hourShort", "h") + " " + minutes + this.label("minuteShort", "m")
		})
	}

	setStatus(text, error) { if (this.status) { this.status.textContent = text || ""; this.status.classList.toggle("error", !!error) } }
	statusLabel(status) {
		var keys = {pending: "statusPending", active: "statusActive", declined: "statusDeclined", cancelled: "statusCancelled", expired: "statusExpired"}
		return this.label(keys[status] || "statusActive", status || "Active")
	}
	friendlyError(error) {
		var message = error && error.message
		if (message === "not_logged_in") return this.label("signInSocial", "Sign in to use friends and challenges.")
		if (message === "not_following" || message === "follow_required") return this.label("mustFollow", "Follow this player before challenging them.")
		if (message === "blocked" || message === "relationship_blocked") return this.label("relationshipBlocked", "This action is unavailable because one player is blocked.")
		if (message === "player_unavailable" || message === "user_not_found") return this.label("playerUnavailable", "This player is no longer available.")
		if (message === "song_not_found") return this.label("songUnavailable", "This song is no longer available.")
		return this.label("actionFailed", "Action failed.")
	}
	label(key, fallback) { var value = strings.librarySocial && strings.librarySocial[key]; return value || fallback }
	escape(value) { return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])) }
}
SocialHub.activeChallenge = null
