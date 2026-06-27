function prepareRemoteSongFiles(songs) {
	songs.forEach(song => {
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
	})
	return songs
}

class TopSongs {
	constructor(...args) {
		this.init(...args)
	}

	init(songSelect) {
		this.songSelect = songSelect
		this.opened = false
		this.rows = []
		this.results = []
	}

	getText(name, fallback) {
		return strings.topSongs && strings.topSongs[name] || fallback
	}

	display(fromButton = false) {
		if (this.opened) {
			return this.remove(true)
		}

		this.opened = true
		this.rows = []
		this.results = []
		this.div = document.createElement("div")
		this.div.innerHTML = assets.pages["search"]

		this.container = this.div.querySelector(":scope #song-search-container")
		this.container.classList.add("song-top10-container")
		if (this.songSelect.touchEnabled) {
			this.container.classList.add("touch-enabled")
		}
		pageEvents.add(this.container, ["mousedown", "touchstart"], this.onClick.bind(this))

		this.panel = this.div.querySelector(":scope #song-search")
		this.panel.classList.add("song-top10-panel")
		this.closeButton = this.div.querySelector(":scope #song-search-close")
		this.closeButton.setAttribute("aria-label", this.getText("close", "Close"))
		this.closeButton.setAttribute("title", this.getText("close", "Close"))

		var bar = this.div.querySelector(":scope #song-search-bar")
		bar.classList.add("song-top10-bar")
		bar.innerHTML = ""

		var heading = document.createElement("h2")
		heading.id = "song-top10-heading"
		heading.innerText = this.getText("title", "Top 10 Songs")
		bar.appendChild(heading)

		var subheading = document.createElement("div")
		subheading.id = "song-top10-subheading"
		subheading.innerText = this.getText("subtitle", "Most played songs")
		bar.appendChild(subheading)

		this.songSelect.playSound("se_pause")
		loader.screen.appendChild(this.div)
		cancelTouch = false
		noResizeRoot = true
		if (this.songSelect.songs[this.songSelect.selectedSong].courses) {
			snd.previewGain.setVolumeMul(0.5)
		} else if (this.songSelect.bgmEnabled) {
			snd.musicGain.setVolumeMul(0.5)
		}

		this.setState(this.getText("loading", "Loading..."))
		this.fetchTopSongs()
	}

	fetchTopSongs() {
		loader.ajax("api/songs/top10?limit=10").then(response => {
			var data = JSON.parse(response)
			if (!data || data.status !== "ok" || !Array.isArray(data.songs)) {
				throw new Error("Invalid top songs response")
			}
			this.renderRows(data.songs)
		}).catch(() => {
			this.setState(this.getText("loadError", "Could not load top songs."), true)
		})
	}

	findLocalSong(row) {
		var rowId = this.normalizeSongId(row.song_id)
		return this.songSelect.songs.find(song => {
			return !song.action && (
				song.id === rowId ||
				row.song_hash && song.hash === row.song_hash
			)
		})
	}

	normalizeSongId(songId) {
		if (typeof songId === "number") {
			return songId
		}
		if (/^-?\d+$/.test(songId)) {
			return parseInt(songId)
		}
		return songId
	}

	getDisplayTitle(row, localSong) {
		if (localSong) {
			return localSong.title || localSong.originalTitle || row.title || ""
		}
		return this.songSelect.getLocalTitle(row.title || "", row.title_lang || {})
	}

	getDisplaySubtitle(row, localSong, title) {
		if (localSong) {
			return localSong.subtitle || ""
		}
		if (title === row.title) {
			return this.songSelect.getLocalTitle(row.subtitle || "", row.subtitle_lang || {})
		}
		return ""
	}

	getCategoryClass(row, localSong) {
		var categoryId = localSong && localSong.category_id
		if (categoryId === null || categoryId === undefined) {
			categoryId = row.category_id
		}
		return categoryId === null || categoryId === undefined ? "default" : "cat" + categoryId
	}

	createResult(row, index) {
		var localSong = this.findLocalSong(row)
		var title = this.getDisplayTitle(row, localSong)
		var subtitle = this.getDisplaySubtitle(row, localSong, title)
		var categoryClass = this.getCategoryClass(row, localSong)

		var resultDiv = document.createElement("div")
		resultDiv.classList.add("song-search-result", "song-top10-result", "song-search-" + categoryClass)
		resultDiv.dataset.index = index
		resultDiv.dataset.songId = row.song_id

		var rank = document.createElement("div")
		rank.classList.add("song-top10-rank")
		rank.innerText = "#" + (row.rank || index + 1)
		resultDiv.appendChild(rank)

		var resultInfoDiv = document.createElement("div")
		resultInfoDiv.classList.add("song-search-result-info", "song-top10-info")

		var resultInfoTitle = document.createElement("span")
		resultInfoTitle.classList.add("song-search-result-title")
		resultInfoTitle.style.fontFamily = strings.songFont || songTitleFont
		resultInfoTitle.innerText = title
		resultInfoTitle.setAttribute("alt", title)
		resultInfoDiv.appendChild(resultInfoTitle)

		if (subtitle) {
			resultInfoDiv.appendChild(document.createElement("br"))
			var resultInfoSubtitle = document.createElement("span")
			resultInfoSubtitle.classList.add("song-search-result-subtitle")
			resultInfoSubtitle.style.fontFamily = strings.font
			resultInfoSubtitle.innerText = subtitle
			resultInfoSubtitle.setAttribute("alt", subtitle)
			resultInfoDiv.appendChild(resultInfoSubtitle)
		}

		resultDiv.appendChild(resultInfoDiv)

		var count = document.createElement("div")
		count.classList.add("song-top10-count")
		var countValue = document.createElement("strong")
		countValue.innerText = (row.play_count || 0).toLocaleString()
		var countLabel = document.createElement("span")
		countLabel.innerText = this.getText("plays", "plays")
		count.appendChild(countValue)
		count.appendChild(countLabel)
		resultDiv.appendChild(count)

		return resultDiv
	}

	renderRows(rows) {
		this.rows = rows
		this.results = []
		var resultsDiv = this.div.querySelector(":scope #song-search-results")
		resultsDiv.innerHTML = ""

		if (!rows.length) {
			this.setState(this.getText("empty", "No play data yet."))
			return
		}

		var header = document.createElement("div")
		header.classList.add("song-top10-list-header")
		header.innerHTML =
			"<span>" + this.getText("rank", "Rank") + "</span>" +
			"<span>" + this.getText("songName", "Song") + "</span>" +
			"<span>" + this.getText("plays", "plays") + "</span>"
		resultsDiv.appendChild(header)

		var fragment = document.createDocumentFragment()
		rows.forEach((row, index) => {
			var result = this.createResult(row, index)
			fragment.appendChild(result)
			this.results.push(result)
		})
		resultsDiv.appendChild(fragment)
	}

	setState(message, error = false) {
		var resultsDiv = this.div.querySelector(":scope #song-search-results")
		resultsDiv.innerHTML = ""
		this.rows = []
		this.results = []

		var tip = document.createElement("div")
		tip.id = "song-search-tip"
		tip.innerText = message
		if (error) {
			tip.classList.add("song-search-tip-error")
		}
		resultsDiv.appendChild(tip)
	}

	setActive(idx) {
		this.songSelect.playSound("se_ka")
		var active = this.div.querySelector(":scope .song-search-result-active")
		if (active) {
			active.classList.remove("song-search-result-active")
		}
		if (idx === null) {
			this.active = null
			return
		}
		var el = this.results[idx]
		el.classList.add("song-search-result-active")
		this.scrollTo(el)
		this.active = idx
	}

	scrollTo(element) {
		var parentNode = element.parentNode
		var selected = element.getBoundingClientRect()
		var parent = parentNode.getBoundingClientRect()
		var selectedPosTop = selected.top - selected.height / 2
		if (Math.floor(selectedPosTop) < Math.floor(parent.top)) {
			parentNode.scrollTop += selectedPosTop - parent.top
		} else {
			var selectedPosBottom = selected.top + selected.height * 1.5 - parent.top
			if (Math.floor(selectedPosBottom) > Math.floor(parent.height)) {
				parentNode.scrollTop += selectedPosBottom - parent.height
			}
		}
	}

	loadSongType(row) {
		var url = "api/songs"
		if (row.song_type) {
			url += "?type=" + encodeURIComponent(row.song_type)
		}
		return loader.ajax(url).then(response => {
			var songs = prepareRemoteSongFiles(JSON.parse(response))
			assets.songsDefault = songs
			assets.songs = assets.songsDefault
			var typeIndex = this.songSelect.songTypes.indexOf(row.song_type)
			if (typeIndex !== -1) {
				localStorage.setItem("songTypeIndex", typeIndex)
			}
		})
	}

	proceed(row) {
		if (!row) {
			return
		}

		var songId = this.normalizeSongId(row.song_id)
		var songIndex = this.songSelect.songs.findIndex(song => {
			return !song.action && (
				song.id === songId ||
				row.song_hash && song.hash === row.song_hash
			)
		})

		if (songIndex !== -1) {
			this.remove()
			this.songSelect.playBgm(false)
			if (this.songSelect.previewing === "muted") {
				this.songSelect.previewing = null
			}
			this.songSelect.setSelectedSong(songIndex)
			this.songSelect.toSelectDifficulty()
			return
		}

		var touchEnabled = this.songSelect.touchEnabled
		this.setState(this.getText("loadingSong", "Loading song..."))
		this.loadSongType(row).then(() => {
			this.remove()
			this.songSelect.playSound("se_don")
			this.songSelect.clean()
			setTimeout(() => {
				new SongSelect(false, false, touchEnabled, songId)
			}, 100)
		}).catch(() => {
			this.setState(this.getText("loadSongError", "Could not open this song."), true)
		})
	}

	onClick(e) {
		var primary = e.type === "touchstart" || e.which === 1
		if (!primary) {
			return
		}
		if (e.target.id === "song-search-container" || e.target.id === "song-search-close") {
			this.remove(true)
			return
		}
		var songEl = e.target.closest(".song-top10-result")
		if (songEl) {
			this.proceed(this.rows[songEl.dataset.index | 0])
		}
	}

	keyPress(pressed, name, event, repeat, ctrl) {
		if (name === "back" || (event && event.keyCode && event.keyCode === 70 && ctrl)) {
			this.remove(true)
			if (event) {
				event.preventDefault()
			}
		} else if (name === "down" && this.results.length) {
			if (this.active === this.results.length - 1) {
				this.setActive(null)
			} else if (Number.isInteger(this.active)) {
				this.setActive(this.active + 1)
			} else {
				this.setActive(0)
			}
		} else if (name === "up" && this.results.length) {
			if (this.active === 0) {
				this.setActive(null)
			} else if (Number.isInteger(this.active)) {
				this.setActive(this.active - 1)
			} else {
				this.setActive(this.results.length - 1)
			}
		} else if (name === "confirm" && Number.isInteger(this.active)) {
			this.proceed(this.rows[this.active])
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

	remove(byUser = false) {
		if (!this.opened) {
			return
		}

		this.opened = false
		if (byUser) {
			this.songSelect.playSound("se_cancel")
		}
		if (this.container) {
			pageEvents.remove(this.container, ["mousedown", "touchstart"])
		}
		this.div.remove()
		delete this.div
		delete this.container
		delete this.panel
		delete this.closeButton
		delete this.active
		cancelTouch = true
		noResizeRoot = false
		if (this.songSelect.songs[this.songSelect.selectedSong].courses) {
			snd.previewGain.setVolumeMul(1)
		} else if (this.songSelect.bgmEnabled) {
			snd.musicGain.setVolumeMul(1)
		}
	}

	clean() {
		if (this.opened) {
			this.remove()
		}
		delete this.rows
		delete this.results
		delete this.songSelect
	}
}
