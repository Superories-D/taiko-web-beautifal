class UploadModal {
	constructor(...args) {
		this.init(...args)
	}

	init(songSelect) {
		this.songSelect = songSelect
		this.opened = false
	}

	display() {
		if (this.opened) {
			return this.remove(true)
		}

		this.opened = true
		this.div = document.createElement("div")
		this.div.innerHTML = assets.pages["upload"]
		this.container = this.div.querySelector(":scope #song-upload-container")
		this.form = this.div.querySelector(":scope #song-upload-form")
		this.submitButton = this.div.querySelector(":scope #song-upload-submit")
		this.status = this.div.querySelector(":scope #song-upload-status")
		this.error = this.div.querySelector(":scope #song-upload-error")
		this.typeSelect = this.div.querySelector(":scope #song-upload-type")

		if (this.songSelect.touchEnabled) {
			this.container.classList.add("touch-enabled")
		}
		this.populateTypes()

		pageEvents.add(this.container, ["mousedown", "touchstart"], this.onClick.bind(this))
		pageEvents.add(this.form, ["submit"], this.onSubmit.bind(this))

		this.songSelect.playSound("se_pause")
		loader.screen.appendChild(this.div)
		cancelTouch = false
		noResizeRoot = true
		if (this.songSelect.songs[this.songSelect.selectedSong].courses) {
			snd.previewGain.setVolumeMul(0.5)
		} else if (this.songSelect.bgmEnabled) {
			snd.musicGain.setVolumeMul(0.5)
		}
	}

	populateTypes() {
		this.typeSelect.innerHTML = ""
		this.songSelect.songTypes.forEach((type, index) => {
			var option = document.createElement("option")
			option.value = type
			option.innerText = type
			option.selected = index === this.songSelect.songTypeIndex
			this.typeSelect.appendChild(option)
		})
	}

	remove(byUser = false) {
		if (!this.opened) {
			return
		}
		this.opened = false
		if (byUser) {
			this.songSelect.playSound("se_cancel")
		}

		pageEvents.remove(this.container, ["mousedown", "touchstart"])
		pageEvents.remove(this.form, ["submit"])
		this.div.remove()
		delete this.div
		delete this.container
		delete this.form
		delete this.submitButton
		delete this.status
		delete this.error
		delete this.typeSelect
		cancelTouch = true
		noResizeRoot = false
		if (this.songSelect.songs[this.songSelect.selectedSong].courses) {
			snd.previewGain.setVolumeMul(1)
		} else if (this.songSelect.bgmEnabled) {
			snd.musicGain.setVolumeMul(1)
		}
	}

	async onSubmit(event) {
		event.preventDefault()
		this.error.textContent = ""
		this.status.textContent = "Uploading..."
		this.submitButton.disabled = true

		try {
			var response = await fetch("/api/upload", {
				method: "POST",
				body: new FormData(this.form)
			})
			var rawText = await response.text()
			var data = {}
			try {
				data = rawText ? JSON.parse(rawText) : {}
			} catch (_error) {
				data = {error: rawText}
			}
			if (!response.ok || data.success === false || data.error) {
				throw new Error(data.error || ("HTTP " + response.status))
			}
			this.status.textContent = "Upload complete. The song will appear after the list refreshes."
			this.form.reset()
			this.populateTypes()
			this.songSelect.playSound("se_don")
		} catch (error) {
			this.status.textContent = "Upload failed."
			this.error.textContent = String(error.message || error)
			this.songSelect.playSound("se_cancel")
		} finally {
			this.submitButton.disabled = false
		}
	}

	onClick(e) {
		if ((e.target.id === "song-upload-container" || e.target.id === "song-upload-close") && (e.which === 1 || e.type === "touchstart")) {
			e.preventDefault()
			this.remove(true)
		}
	}

	keyPress(pressed, name, event) {
		if (name === "back") {
			this.remove(true)
			if (event) {
				event.preventDefault()
			}
		} else if (name === "confirm" && event && event.target === this.submitButton) {
			this.form.requestSubmit()
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

	clean() {
		this.remove()
		delete this.songSelect
	}
}
