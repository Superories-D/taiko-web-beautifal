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
		this.tjaInput = this.div.querySelector(":scope #song-upload-tja")
		this.musicInput = this.div.querySelector(":scope #song-upload-music")
		this.quality = null
		this.qualityStatus = document.createElement("p")
		this.qualityStatus.id = "song-upload-quality"
		this.qualityStatus.setAttribute("aria-live", "polite")
		this.form.insertBefore(this.qualityStatus, this.submitButton)

		if (this.songSelect.touchEnabled) {
			this.container.classList.add("touch-enabled")
		}
		this.populateTypes()

		pageEvents.add(this.container, ["mousedown", "touchstart"], this.onClick.bind(this))
		pageEvents.add(this.form, ["submit"], this.onSubmit.bind(this))
		pageEvents.add(this.tjaInput, ["change"], this.runQualityCheck.bind(this))
		pageEvents.add(this.musicInput, ["change"], this.runQualityCheck.bind(this))

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
		var option = document.createElement("option")
		option.value = "12 Custom"
		option.innerText = "12 Custom"
		option.selected = true
		this.typeSelect.appendChild(option)
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
		pageEvents.remove(this.tjaInput, ["change"])
		pageEvents.remove(this.musicInput, ["change"])
		this.div.remove()
		delete this.div
		delete this.container
		delete this.form
		delete this.submitButton
		delete this.status
		delete this.error
		delete this.typeSelect
		delete this.tjaInput
		delete this.musicInput
		delete this.qualityStatus
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
			await this.runQualityCheck()
			if (this.quality && !this.quality.ok) {
				throw new Error("上传前质检未通过：" + this.quality.errors.join("、"))
			}
			var response = await fetch("/api/user-upload", {
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

	async runQualityCheck() {
		var tja = this.tjaInput && this.tjaInput.files[0]
		var music = this.musicInput && this.musicInput.files[0]
		this.quality = null
		if (!tja) {
			this.qualityStatus.textContent = "选择 TJA 和音频后自动检查。"
			this.qualityStatus.className = "song-upload-quality"
			return
		}
		try {
			var report = PlayerLab.analyzeTja(await tja.text(), music)
			this.quality = report
			var text = report.ok ? "质检通过：" + report.courses + " 个难度，" + report.notes + " 个音符。" : "质检失败：" + report.errors.join("；")
			if (report.warnings.length) text += " 警告：" + report.warnings.join("；")
			this.qualityStatus.textContent = text
			this.qualityStatus.className = "song-upload-quality " + (report.ok ? "ok" : "bad")
		} catch (error) {
			this.quality = {ok: false, errors: ["无法读取 TJA：" + error.message], warnings: []}
			this.qualityStatus.textContent = this.quality.errors[0]
			this.qualityStatus.className = "song-upload-quality bad"
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
