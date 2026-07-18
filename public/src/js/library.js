function hubBindTap(target, callback) {
	var lastTouch = 0
	var onTouch = event => {
		lastTouch = Date.now()
		if (event.cancelable) event.preventDefault()
		callback(event)
	}
	var onClick = event => {
		if (Date.now() - lastTouch < 750) return
		callback(event)
	}
	pageEvents.add(target, "touchend", onTouch)
	pageEvents.add(target, "click", onClick)
	return () => {
		pageEvents.remove(target, "touchend")
		pageEvents.remove(target, "click")
	}
}

class LibraryHub {
	constructor(songSelect) {
		this.songSelect = songSelect
		this.opened = false
		this.tab = "favorites"
		this.localKey = "taikoLibrary.v1"
		this.state = this.loadLocal()
		this.overlay = document.getElementById("library-overlay")
		this.panel = document.getElementById("library-panel")
		this.list = document.getElementById("library-list")
		this.status = document.getElementById("library-status")
		this.filter = document.getElementById("library-filter")
		this.newPlaylist = document.getElementById("library-new-playlist")
		this.favoriteCurrent = document.getElementById("library-favorite-current")
		this.addCurrent = document.getElementById("library-add-current")
		this.categoryFilter = document.getElementById("library-category")
		this.makerFilter = document.getElementById("library-maker")
		this.difficultyFilter = document.getElementById("library-difficulty")
		this.starsFilter = document.getElementById("library-stars-min")
		this.starsMaxFilter = document.getElementById("library-stars-max")
		this.bpmFilter = document.getElementById("library-bpm-min")
		this.bpmMaxFilter = document.getElementById("library-bpm-max")
		this.progressFilter = document.getElementById("library-progress")
		this.closeButton = document.getElementById("library-close")
		this.tapCleanups = []
		this.renderVersion = 0
		this.bind()
	}

	loadLocal() {
		try {
			var state = JSON.parse(localStorage.getItem(this.localKey) || "{}")
			var favorites = Array.isArray(state.favorites) ? state.favorites : (Array.isArray(state.favoriteHashes) ? state.favoriteHashes : [])
			var playlists = Array.isArray(state.playlists) ? state.playlists : (Array.isArray(state.lists) ? state.lists : [])
			return {
				version: 1,
				favorites: [...new Set(favorites.filter(value => typeof value === "string" && value))],
				playlists: playlists.filter(p => p && p.name).map(p => ({
					localId: p.localId || this.randomId(), name: String(p.name).slice(0, 40),
					description: String(p.description || "").slice(0, 200),
					songHashes: Array.isArray(p.songHashes || p.song_hashes) ? [...new Set((p.songHashes || p.song_hashes).filter(value => typeof value === "string" && value))].slice(0, 200) : []
				})),
				updatedAt: Number(state.updatedAt) || Date.now()
			}
		} catch (_error) {
			return {version: 1, favorites: [], playlists: [], updatedAt: Date.now()}
		}
	}

	saveLocal() {
		this.state.updatedAt = Date.now()
		try { localStorage.setItem(this.localKey, JSON.stringify(this.state)) } catch (_error) {}
	}

	randomId() {
		return "local-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10)
	}

	bind() {
		if (!this.overlay) return
		this.tapCleanups.push(hubBindTap(this.closeButton, event => this.remove(true)))
		this.tapCleanups.push(hubBindTap(this.overlay, event => {
			if (event.target === this.overlay) this.remove(true)
		}))
		this.tapCleanups.push(hubBindTap(this.panel, event => {
			var tab = event.target.closest("[data-library-tab]")
			if (tab) this.selectTab(tab.dataset.libraryTab)
			var action = event.target.closest("[data-library-action]")
			if (action) this.action(action.dataset.libraryAction, action.dataset.songHash, action.dataset.playlistId)
		}))
		pageEvents.add(this.filter, "input", () => this.render())
		;[this.categoryFilter, this.makerFilter, this.difficultyFilter, this.starsFilter, this.starsMaxFilter, this.bpmFilter, this.bpmMaxFilter, this.progressFilter].forEach(input => pageEvents.add(input, ["change", "input"], () => this.render()))
		this.tapCleanups.push(hubBindTap(this.newPlaylist, event => this.createPlaylist()))
		this.tapCleanups.push(hubBindTap(this.favoriteCurrent, event => {
			var song = this.currentSong()
			if (song) this.toggleFavorite(String(song.hash || song.id))
		}))
		this.tapCleanups.push(hubBindTap(this.addCurrent, event => {
			var song = this.currentSong()
			if (song) this.addToPlaylist(String(song.hash || song.id))
		}))
		pageEvents.add(window, "keydown", event => {
			if (this.opened && event.key === "Escape") { event.preventDefault(); this.remove(true) }
		}, "library-escape")
		pageEvents.add(window, "login", () => this.mergeGuest().catch(() => {}), "library-login")
	}

	display() {
		if (!this.overlay) return
		this.applyStrings()
		if (this.songSelect && this.songSelect.closeSongExtras) this.songSelect.closeSongExtras(this)
		this.opened = true
		this.overlay.hidden = false
		this.filter.value = ""
		this.updateSelection(this.currentSong())
		this.populateFilters()
		try {
			this.sharedToken = new URLSearchParams(location.search).get("playlist") || null
		} catch (_error) { this.sharedToken = null }
		this.selectTab(this.tab)
		this.mergeGuest().catch(() => this.render())
		setTimeout(() => this.filter.focus(), 0)
		if (this.songSelect) this.songSelect.updateSearchButtonVisibility()
	}

	applyStrings() {
		var s = strings.librarySocial
		if (!s || !this.panel) return
		this.panel.querySelector("#library-title").textContent = s.libraryTitle
		this.panel.querySelector('[data-library-tab="favorites"]').textContent = s.favorites
		this.panel.querySelector('[data-library-tab="playlists"]').textContent = s.playlists
		this.panel.querySelector('[data-library-tab="recent"]').textContent = s.recent
		this.panel.querySelector('[data-library-tab="discover"]').textContent = s.discover
		this.filter.placeholder = s.filterSongs || s.filter
		this.newPlaylist.textContent = s.newPlaylist || "New playlist"
		this.favoriteCurrent.textContent = s.favorite
		this.addCurrent.textContent = s.addCurrent || s.add
		this.categoryFilter.options[0].textContent = s.allCategories || "All categories"
		this.makerFilter.options[0].textContent = s.allMakers || "All makers"
		this.difficultyFilter.options[0].textContent = s.allDifficulties || "All difficulties"
		this.progressFilter.options[0].textContent = s.allProgress || "All progress"
		this.progressFilter.querySelector('[value="played"]').textContent = s.played || "Played"
		this.progressFilter.querySelector('[value="unplayed"]').textContent = s.unplayed || "Unplayed"
		this.progressFilter.querySelector('[value="favorite"]').textContent = s.favorites
		this.progressFilter.querySelector('[value="branch"]').textContent = s.branchCharts || "Branch charts"
		this.closeButton.setAttribute("aria-label", s.close || "Close")
		this.closeButton.title = s.close || "Close"
	}

	currentSong() {
		return this.songSelect && this.songSelect.songs && this.songSelect.songs[this.songSelect.selectedSong]
	}

	updateSelection(song) {
		var hash = song && song.courses ? String(song.hash || song.id) : null
		var active = !!hash && this.state.favorites.indexOf(hash) !== -1
		if (this.favoriteCurrent) {
			this.favoriteCurrent.disabled = !hash
			this.favoriteCurrent.setAttribute("aria-pressed", String(active))
			this.favoriteCurrent.classList.toggle("active", active)
		}
		if (this.addCurrent) this.addCurrent.disabled = !hash
		var entry = document.getElementById("song-library-btn")
		if (entry) {
			entry.setAttribute("aria-pressed", String(active))
			entry.classList.toggle("favorite-active", active)
		}
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
		;[this.categoryFilter, this.makerFilter, this.difficultyFilter, this.starsFilter, this.starsMaxFilter, this.bpmFilter, this.bpmMaxFilter, this.progressFilter].forEach(input => pageEvents.remove(input, ["change", "input"]))
		pageEvents.remove(window, "keydown", "library-escape")
		pageEvents.remove(window, "login", "library-login")
	}

	selectTab(tab) {
		if (["favorites", "playlists", "recent", "discover"].indexOf(tab) === -1) tab = "favorites"
		this.tab = tab
		this.panel.querySelectorAll("[data-library-tab]").forEach(button => button.classList.toggle("active", button.dataset.libraryTab === tab))
		this.newPlaylist.hidden = tab !== "playlists"
		this.render()
	}

	async request(path, method, body) {
		var options = {method: method || "GET", credentials: "same-origin", headers: {"Accept": "application/json"}}
		if (body !== undefined) {
			options.headers["Content-Type"] = "application/json"
			options.body = JSON.stringify(body)
		}
		if (method && method !== "GET") {
			options.headers["X-CSRFToken"] = await loader.getCsrfToken()
		}
		var response = await fetch(path, options)
		var data = await response.json().catch(() => ({}))
		if (!response.ok || data.status === "error") throw data
		return data
	}

	async mergeGuest() {
		if (!account.loggedIn || (!this.state.favorites.length && !this.state.playlists.length)) {
			this.render()
			return
		}
		if (this.mergeDeclined) { this.render(); return }
		if (!this.mergePrompted) {
			this.mergePrompted = true
			var message = "Import " + this.state.favorites.length + " local favorites and " + this.state.playlists.length + " local playlists into this account?"
			if (!confirm(message)) { this.mergeDeclined = true; this.render(); return }
		}
		if (this.merging) return
		this.merging = true
		this.setStatus("Local library found. Importing…")
		try {
			var data = await this.request("api/library/import", "POST", {
				favorites: this.state.favorites,
				playlists: this.state.playlists.map(p => ({local_id: p.localId, name: p.name, description: p.description, song_hashes: p.songHashes}))
			})
			this.state = {version: 1, favorites: [], playlists: [], updatedAt: Date.now()}
			this.saveLocal()
		} catch (error) {
			this.setStatus(error && error.message === "not_logged_in" ? "Sign in to sync your local library." : "Library sync failed; local data is kept.", true)
		} finally {
			this.merging = false
			this.render()
		}
	}

	async loadCloud() {
		if (!account.loggedIn) return null
		var result = await Promise.all([this.request("api/library/favorites"), this.request("api/library/playlists"), this.request("api/library/discover")])
		this.state.favorites = Array.isArray(result[0].song_hashes) ? result[0].song_hashes.slice() : []
		return {favorites: result[0], playlists: result[1], discover: result[2]}
	}

	async render() {
		if (!this.opened || !this.list) return
		var renderVersion = ++this.renderVersion
		this.list.innerHTML = ""
		this.setStatus(strings.librarySocial ? strings.librarySocial.loading : "Loading…")
		try {
			if (this.sharedToken) {
				var shared = await this.request("api/library/shared/" + encodeURIComponent(this.sharedToken))
				if (renderVersion !== this.renderVersion || !this.opened) return
				this.newPlaylist.hidden = true
				this.renderSongs(shared.playlist && shared.playlist.songs || [])
				this.setStatus((shared.playlist.owner && shared.playlist.owner.display_name || "") + " · " + (shared.playlist.name || "Shared playlist"))
				return
			}
			var cloud = await this.loadCloud()
			if (renderVersion !== this.renderVersion || !this.opened) return
			this.updateSelection(this.currentSong())
			var cards
			if (this.tab === "playlists") cards = this.renderPlaylists(cloud ? cloud.playlists.playlists : this.state.playlists)
			else {
				var songs = this.tab === "favorites" ? (cloud ? cloud.favorites.songs : this.localSongs(this.state.favorites)) :
					this.tab === "recent" ? (cloud ? cloud.discover.recent : this.localSongs(this.recentHashes())) :
					(cloud ? cloud.discover.recommended : this.localSongs(this.state.favorites))
				cards = this.renderSongs(songs)
			}
			if (!cards) cards = 0
			if (!cards) this.list.innerHTML = '<div class="hub-empty">' + (strings.librarySocial ? strings.librarySocial.empty : "Nothing here yet.") + "</div>"
			this.setStatus("")
		} catch (_error) {
			this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to load library.", true)
			this.list.innerHTML = '<div class="hub-empty">' + (strings.librarySocial ? strings.librarySocial.offline : "Try again when you are online.") + "</div>"
		}
	}

	recentHashes() {
		var scoreData = typeof scoreStorage !== "undefined" && scoreStorage.scores ? scoreStorage.scores : {}
		return Object.keys(scoreData).slice(0, 100)
	}

	localSongs(hashes) {
		return (hashes || []).map(hash => this.songSelect.songs.find(song => String(song.hash || song.id) === String(hash))).filter(song => song && song.courses)
	}

	filtered(songs) {
		var query = (this.filter.value || "").trim().toLowerCase()
		var category = this.categoryFilter.value
		var maker = this.makerFilter.value
		var difficulty = this.difficultyFilter.value
		var stars = Number(this.starsFilter.value) || 0
		var starsMax = Number(this.starsMaxFilter.value) || Infinity
		var bpm = Number(this.bpmFilter.value) || 0
		var bpmMax = Number(this.bpmMaxFilter.value) || Infinity
		var progress = this.progressFilter.value
		var scores = typeof scoreStorage !== "undefined" && scoreStorage.scores || {}
		return (songs || []).filter(song => {
			var hash = String(song.hash || song.id)
			var course = difficulty && song.courses && song.courses[difficulty]
			var hasBranch = Object.keys(song.courses || {}).some(diff => song.courses[diff] && song.courses[diff].branch)
			var starValues = Object.values(song.courses || {}).filter(Boolean).map(item => Number(item.stars)).filter(Number.isFinite)
			var starPass = (!stars && !isFinite(starsMax)) || starValues.some(value => value >= stars && value <= starsMax)
			var bpmMin = Number(song.bpm_min)
			var bpmMaxValue = Number(song.bpm_max || song.bpm_min)
			return (!query || String(song.title || "").toLowerCase().includes(query) || String(song.originalTitle || "").toLowerCase().includes(query)) &&
				(!category || String(song.category_id || song.category || "") === category) &&
				(!maker || String(song.maker && (song.maker.id || song.maker.name) || "") === maker) &&
				(!difficulty || !!course) && starPass &&
				(!bpm || (Number.isFinite(bpmMin) && bpmMaxValue >= bpm)) && (!isFinite(bpmMax) || (Number.isFinite(bpmMin) && bpmMin <= bpmMax)) &&
				(progress !== "played" || !!scores[hash]) && (progress !== "unplayed" || !scores[hash]) &&
				(progress !== "favorite" || this.state.favorites.indexOf(hash) !== -1) && (progress !== "branch" || hasBranch)
		})
	}

	populateFilters() {
		if (this.filtersReady) return
		this.filtersReady = true
		var categories = new Map(), makers = new Map(), hasBpm = false
		this.songSelect.songs.forEach(song => {
			if (!song || !song.courses) return
			var categoryValue = String(song.category_id || song.category || "")
			if (categoryValue) categories.set(categoryValue, song.category || categoryValue)
			var makerValue = String(song.maker && (song.maker.id || song.maker.name) || "")
			if (makerValue) makers.set(makerValue, song.maker.name || makerValue)
			if (song.bpm_min || song.bpm_max) hasBpm = true
		})
		categories.forEach((label, value) => this.categoryFilter.add(new Option(label, value)))
		makers.forEach((label, value) => this.makerFilter.add(new Option(label, value)))
		this.bpmFilter.disabled = !hasBpm
		this.bpmMaxFilter.disabled = !hasBpm
	}

	renderSongs(rawSongs) {
		var songs = this.filtered(rawSongs)
		songs.slice(0, 100).forEach(song => {
			var hash = String(song.hash || song.id)
			var card = document.createElement("article")
			card.className = "hub-card"
			var title = document.createElement("div")
			title.className = "hub-card-title"
			title.textContent = song.title || song.originalTitle || hash
			var meta = document.createElement("div")
			meta.className = "hub-card-meta"
			meta.textContent = [song.category, song.maker && song.maker.name, song.bpm_min ? (song.bpm_min + "–" + (song.bpm_max || song.bpm_min) + " BPM") : ""].filter(Boolean).join(" · ")
			var actions = document.createElement("div")
			var score = typeof scoreStorage !== "undefined" && scoreStorage.scores ? scoreStorage.scores[hash] : null
			var scoreSummary = Object.keys(song.courses || {}).filter(diff => song.courses[diff]).map(diff => {
				var item = score && score[diff]
				return diff.toUpperCase() + " " + Number(song.courses[diff].stars || 0) + "★" + (item && item.points != null ? " · " + Number(item.points).toLocaleString() : "") + (item && item.crown ? " · " + item.crown : "")
			}).join(" / ")
			if (scoreSummary) meta.textContent += " · " + scoreSummary
			actions.className = "hub-card-actions"
			actions.innerHTML = '<button type="button" data-library-action="play" data-song-hash="' + this.escape(hash) + '">' + (strings.librarySocial ? strings.librarySocial.play : "Play") + '</button>' +
				'<button type="button" data-library-action="favorite" data-song-hash="' + this.escape(hash) + '">' + (this.state.favorites.indexOf(hash) !== -1 ? "★" : "☆") + '</button>' +
				'<button type="button" data-library-action="add" data-song-hash="' + this.escape(hash) + '">' + (strings.librarySocial ? strings.librarySocial.add : "Add") + '</button>'
			actions.insertAdjacentHTML("afterbegin", '<button type="button" data-library-action="preview" data-song-hash="' + this.escape(hash) + '">' + (strings.librarySocial ? strings.librarySocial.preview : "Preview") + '</button>')
			card.append(title, meta, actions)
			this.list.appendChild(card)
		})
		return songs.length
	}

	renderPlaylists(playlists) {
		var query = (this.filter.value || "").trim().toLowerCase()
		var filtered = (playlists || []).filter(playlist => !query || String(playlist.name).toLowerCase().includes(query))
		filtered.forEach(playlist => {
			var card = document.createElement("article")
			card.className = "hub-card"
			card.innerHTML = '<div class="hub-card-title">' + this.escape(playlist.name) + '</div><div class="hub-card-meta">' + ((playlist.song_hashes || playlist.songHashes || []).length) + ' songs</div><div class="hub-card-actions">' +
				'<button type="button" data-library-action="open-playlist" data-playlist-id="' + this.escape(playlist.playlist_id || playlist.localId) + '">Open</button>' +
				'<button type="button" data-library-action="delete-playlist" data-playlist-id="' + this.escape(playlist.playlist_id || playlist.localId) + '">Delete</button>' +
				(playlist.playlist_id ? '<button type="button" data-library-action="share-playlist" data-playlist-id="' + this.escape(playlist.playlist_id) + '">Copy link</button>' : '') +
				(playlist.playlist_id && playlist.shared ? '<button type="button" data-library-action="unshare-playlist" data-playlist-id="' + this.escape(playlist.playlist_id) + '">Stop sharing</button>' : '') + '</div>'
			this.list.appendChild(card)
		})
		return filtered.length
	}

	async action(action, songHash, playlistId) {
		if (action === "play") {
			var index = this.songSelect.songs.findIndex(song => String(song.hash || song.id) === String(songHash))
			if (index !== -1) { this.remove(true); this.songSelect.setSelectedSong(index); this.songSelect.toSelectDifficulty() }
			return
		}
		if (action === "preview") {
			var previewIndex = this.songSelect.songs.findIndex(song => String(song.hash || song.id) === String(songHash))
			if (previewIndex !== -1) {
				this.songSelect.setSelectedSong(previewIndex)
				if (this.songSelect.startPreview) this.songSelect.startPreview()
				this.setStatus(strings.librarySocial ? strings.librarySocial.previewing : "Previewing")
			}
			return
		}
		if (action === "favorite") { await this.toggleFavorite(songHash); return }
		if (action === "add") { await this.addToPlaylist(songHash); return }
		if (action === "open-playlist") { await this.openPlaylist(playlistId); return }
		if (action === "delete-playlist") { await this.deletePlaylist(playlistId); return }
		if (action === "share-playlist") { await this.copyShare(playlistId); }
		if (action === "unshare-playlist") { await this.unshare(playlistId); }
	}

	async toggleFavorite(hash) {
		var wasFavorite = this.state.favorites.indexOf(hash) !== -1
		if (wasFavorite) this.state.favorites = this.state.favorites.filter(value => value !== hash)
		else this.state.favorites.push(hash)
		this.saveLocal()
		this.updateSelection(this.currentSong())
		try {
			if (account.loggedIn) await this.request("api/library/favorites" + (wasFavorite ? "/" + encodeURIComponent(hash) : ""), wasFavorite ? "DELETE" : "POST", wasFavorite ? undefined : {song_hash: hash})
			this.render()
		} catch (_error) {
			if (wasFavorite) this.state.favorites.push(hash)
			else this.state.favorites = this.state.favorites.filter(value => value !== hash)
			this.saveLocal(); this.updateSelection(this.currentSong()); this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to save.", true)
		}
	}

	async createPlaylist() {
		var name = prompt(strings.librarySocial ? strings.librarySocial.playlistName : "Playlist name")
		if (!name || !name.trim()) return
		var description = prompt(strings.librarySocial ? strings.librarySocial.playlistDescription : "Description") || ""
		try {
			if (account.loggedIn) await this.request("api/library/playlists", "POST", {name: name.trim(), description: description.trim(), song_hashes: []})
			else { this.state.playlists.push({localId: this.randomId(), name: name.trim().slice(0, 40), description: description.trim().slice(0, 200), songHashes: []}); this.saveLocal() }
			this.render()
		} catch (_error) { this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to create playlist.", true) }
	}

	async addToPlaylist(hash) {
		if (account.loggedIn) {
			try {
				var data = await this.request("api/library/playlists")
				if (!data.playlists.length) { await this.createPlaylist(); return }
				var name = prompt(data.playlists.map((p, i) => (i + 1) + ": " + p.name).join("\n") + "\n\nEnter playlist number")
				var playlist = data.playlists[Number(name) - 1]
				if (playlist) { await this.request("api/library/playlists/" + encodeURIComponent(playlist.playlist_id) + "/songs", "POST", {song_hash: hash}); this.setStatus("Added") }
			} catch (_error) { this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to add.", true) }
		} else {
			if (!this.state.playlists.length) { await this.createPlaylist(); return }
			var choice = prompt(this.state.playlists.map((p, i) => (i + 1) + ": " + p.name).join("\n") + "\n\nEnter playlist number")
			var local = this.state.playlists[Number(choice) - 1]
			if (local && local.songHashes.indexOf(hash) === -1 && local.songHashes.length < 200) { local.songHashes.push(hash); this.saveLocal(); this.setStatus("Added") }
		}
	}

	async openPlaylist(id) {
		var playlist
		if (account.loggedIn) {
			var data = await this.request("api/library/playlists")
			playlist = data.playlists.find(p => p.playlist_id === id)
		} else playlist = this.state.playlists.find(p => p.localId === id)
		if (!playlist) return
		this.tab = "favorites"
		this.filter.value = ""
		this.list.innerHTML = ""
		this.renderSongs(this.localSongs(playlist.song_hashes || playlist.songHashes))
	}

	async deletePlaylist(id) {
		if (!confirm(strings.librarySocial ? strings.librarySocial.confirmDelete : "Delete this playlist?")) return
		try {
			if (account.loggedIn) await this.request("api/library/playlists/" + encodeURIComponent(id), "DELETE")
			else { this.state.playlists = this.state.playlists.filter(p => p.localId !== id); this.saveLocal() }
			this.render()
		} catch (_error) { this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to delete.", true) }
	}

	async copyShare(id) {
		try {
			var data = await this.request("api/library/playlists/" + encodeURIComponent(id) + "/share", "POST", {})
			var link = location.origin + location.pathname + "?playlist=" + encodeURIComponent(data.share_token)
			if (navigator.clipboard) await navigator.clipboard.writeText(link)
			this.setStatus(strings.librarySocial ? strings.librarySocial.copied : "Share link copied")
		} catch (_error) { this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to share.", true) }
	}

	async unshare(id) {
		try {
			await this.request("api/library/playlists/" + encodeURIComponent(id) + "/share", "DELETE")
			this.setStatus("Sharing stopped")
			this.render()
		} catch (_error) { this.setStatus(strings.librarySocial ? strings.librarySocial.failed : "Unable to update sharing.", true) }
	}

	setStatus(text, error) { if (this.status) { this.status.textContent = text || ""; this.status.classList.toggle("error", !!error) } }
	escape(value) { return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])) }
}
