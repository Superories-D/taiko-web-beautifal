(function () {
	var STORAGE_KEY = "easySettings"
	var DEFAULT_SETTINGS = {
		playbackRate: 1,
		baisoku: 1,
		doron: false,
		abekobe: false,
		detarame: false,
		sortByTitle: false,
		songSelectingSpeed: 400
	}
	var BAISOKU_VALUES = [1, 1.5, 2, 3, 4]
	var cachedSettings = null
	var overlay = null
	var activeSongSelect = null
	var opened = false

	function clampNumber(value, min, max, fallback) {
		var number = typeof value === "number" ? value : parseFloat(value)
		if (!isFinite(number)) {
			return fallback
		}
		return Math.min(max, Math.max(min, number))
	}

	function sanitizeBoolean(value, fallback) {
		if (typeof value === "boolean") {
			return value
		}
		if (typeof value === "string") {
			var lower = value.toLowerCase().trim()
			if (lower === "true" || lower === "1" || lower === "yes" || lower === "on") {
				return true
			}
			if (lower === "false" || lower === "0" || lower === "no" || lower === "off" || lower === "") {
				return false
			}
		}
		if (typeof value === "number") {
			return value !== 0
		}
		return fallback
	}

	function sanitizeBaisoku(value) {
		var number = typeof value === "number" ? value : parseFloat(value)
		if (!isFinite(number)) {
			return DEFAULT_SETTINGS.baisoku
		}
		for (var i = 0; i < BAISOKU_VALUES.length; i++) {
			if (Math.abs(number - BAISOKU_VALUES[i]) < 0.0001) {
				return BAISOKU_VALUES[i]
			}
		}
		return DEFAULT_SETTINGS.baisoku
	}

	function sanitizeSongSelectingSpeed(value) {
		return Math.round(clampNumber(value, 150, 1200, DEFAULT_SETTINGS.songSelectingSpeed))
	}

	function readStorage(key) {
		try {
			return localStorage.getItem(key)
		} catch (e) {
			return null
		}
	}

	function writeStorage(key, value) {
		try {
			localStorage.setItem(key, value)
		} catch (e) { }
	}

	function readLegacySettings() {
		var legacy = {}
		var baisoku = readStorage("baisoku")
		var doron = readStorage("doron")
		var abekobe = readStorage("abekobe")
		var detarame = readStorage("detarame")
		var titlesort = readStorage("titlesort")
		var sss = readStorage("sss")
		if (baisoku !== null) {
			legacy.baisoku = baisoku
		}
		if (doron !== null) {
			legacy.doron = doron
		}
		if (abekobe !== null) {
			legacy.abekobe = abekobe
		}
		if (detarame !== null) {
			legacy.detarame = detarame === "true" || parseFloat(detarame) > 0
		}
		if (titlesort !== null) {
			legacy.sortByTitle = titlesort
		}
		if (sss !== null) {
			legacy.songSelectingSpeed = sss
		}
		return legacy
	}

	function syncLegacySettings(settings) {
		writeStorage("baisoku", String(settings.baisoku))
		writeStorage("doron", String(settings.doron))
		writeStorage("abekobe", String(settings.abekobe))
		writeStorage("detarame", String(settings.detarame))
		writeStorage("titlesort", String(settings.sortByTitle))
		writeStorage("sss", String(settings.songSelectingSpeed))
	}

	function sanitizeSettings(input) {
		var source = input && typeof input === "object" ? input : {}
		var settings = Object.assign({}, DEFAULT_SETTINGS, source)
		settings.playbackRate = clampNumber(settings.playbackRate, 0.5, 2, DEFAULT_SETTINGS.playbackRate)
		settings.baisoku = sanitizeBaisoku(settings.baisoku)
		settings.doron = sanitizeBoolean(settings.doron, DEFAULT_SETTINGS.doron)
		settings.abekobe = sanitizeBoolean(settings.abekobe, DEFAULT_SETTINGS.abekobe)
		settings.detarame = sanitizeBoolean(settings.detarame, DEFAULT_SETTINGS.detarame)
		settings.sortByTitle = sanitizeBoolean(settings.sortByTitle, DEFAULT_SETTINGS.sortByTitle)
		settings.songSelectingSpeed = sanitizeSongSelectingSpeed(settings.songSelectingSpeed)
		return settings
	}

	function loadSettings() {
		var stored = {}
		var raw = readStorage(STORAGE_KEY)
		if (raw) {
			try {
				stored = JSON.parse(raw) || {}
			} catch (e) {
				stored = {}
			}
		}
		cachedSettings = sanitizeSettings(Object.assign({}, readLegacySettings(), stored))
		saveSettings(cachedSettings, true)
		return getSettings()
	}

	function saveSettings(settings, silent) {
		cachedSettings = sanitizeSettings(settings)
		writeStorage(STORAGE_KEY, JSON.stringify(cachedSettings))
		syncLegacySettings(cachedSettings)
		if (!silent) {
			notifyChange()
		}
		return getSettings()
	}

	function getSettings() {
		if (!cachedSettings) {
			loadSettings()
		}
		return Object.assign({}, cachedSettings)
	}

	function setSetting(key, value) {
		var settings = getSettings()
		settings[key] = value
		return saveSettings(settings)
	}

	function isModifiedGameplay(settings) {
		settings = sanitizeSettings(settings || getSettings())
		return Math.abs(settings.playbackRate - 1) > 0.0001 ||
			Math.abs(settings.baisoku - 1) > 0.0001 ||
			settings.doron ||
			settings.abekobe ||
			settings.detarame
	}

	function isLeaderboardEligible(settings) {
		return !isModifiedGameplay(settings)
	}

	function getLeaderboardBlockReason(settings) {
		settings = sanitizeSettings(settings || getSettings())
		var reasons = []
		if (Math.abs(settings.playbackRate - 1) > 0.0001) {
			reasons.push("playbackRate")
		}
		if (Math.abs(settings.baisoku - 1) > 0.0001) {
			reasons.push("baisoku")
		}
		if (settings.doron) {
			reasons.push("doron")
		}
		if (settings.abekobe) {
			reasons.push("abekobe")
		}
		if (settings.detarame) {
			reasons.push("detarame")
		}
		return reasons.join(", ")
	}

	function getPlaybackRate() {
		return getSettings().playbackRate
	}

	function getBaisoku() {
		return getSettings().baisoku
	}

	function getText(key, fallback) {
		if (typeof strings !== "undefined" && strings.easySettings && strings.easySettings[key]) {
			return strings.easySettings[key]
		}
		return fallback
	}

	function setText(element, text) {
		if (element) {
			element.textContent = text
		}
	}

	function formatNumber(value) {
		return String(Math.round(value * 100) / 100).replace(/\.0$/, "")
	}

	function getPreferredLanguage() {
		if (typeof strings !== "undefined" && strings.id) {
			return strings.id
		}
		return "en"
	}

	function getLocalizedValue(value, preferredLanguage) {
		if (value === null || typeof value === "undefined") {
			return ""
		}
		if (typeof value === "string" || typeof value === "number") {
			return String(value)
		}
		if (Array.isArray(value)) {
			for (var i = 0; i < value.length; i++) {
				var arrayValue = getLocalizedValue(value[i], preferredLanguage)
				if (arrayValue) {
					return arrayValue
				}
			}
			return ""
		}
		if (typeof value === "object") {
			if (preferredLanguage && value[preferredLanguage]) {
				return getLocalizedValue(value[preferredLanguage], preferredLanguage)
			}
			if (value.en) {
				return getLocalizedValue(value.en, preferredLanguage)
			}
			for (var key in value) {
				var objectValue = getLocalizedValue(value[key], preferredLanguage)
				if (objectValue) {
					return objectValue
				}
			}
		}
		return ""
	}

	function getSongTitle(song, preferredLanguage) {
		if (!song) {
			return ""
		}
		preferredLanguage = preferredLanguage || getPreferredLanguage()
		var title = getLocalizedValue(song.title, preferredLanguage)
		if (!title && song.title_lang) {
			title = getLocalizedValue(song.title_lang, preferredLanguage)
		}
		if (!title && song.name) {
			title = getLocalizedValue(song.name, preferredLanguage)
		}
		if (!title && song.id !== null && typeof song.id !== "undefined") {
			title = String(song.id)
		}
		return String(title || "")
	}

	function ensureOverlay(songSelect) {
		activeSongSelect = songSelect || activeSongSelect
		var container = activeSongSelect && activeSongSelect.songSelect || document.getElementById("song-select")
		if (!container) {
			return null
		}
		if (overlay && overlay.parentNode !== container) {
			overlay.parentNode.removeChild(overlay)
			overlay = null
		}
		if (overlay) {
			return overlay
		}

		overlay = document.createElement("div")
		overlay.id = "easy-settings-overlay"
		overlay.hidden = true
		overlay.innerHTML =
			'<div id="easy-settings-panel" role="dialog" aria-modal="true" aria-labelledby="easy-settings-heading">' +
				'<div class="easy-settings-header">' +
					'<h2 id="easy-settings-heading"></h2>' +
					'<button id="easy-settings-close" type="button" aria-label="Close" title="Close">x</button>' +
				'</div>' +
				'<div class="easy-settings-body">' +
					'<label class="easy-settings-row">' +
						'<span id="easy-settings-playback-label"></span>' +
						'<span class="easy-settings-value" id="easy-settings-playback-value"></span>' +
						'<input id="easy-settings-playback" type="range" min="0.5" max="2" step="0.05">' +
					'</label>' +
					'<label class="easy-settings-row">' +
						'<span id="easy-settings-baisoku-label"></span>' +
						'<select id="easy-settings-baisoku">' +
							'<option value="1">1x</option>' +
							'<option value="1.5">1.5x</option>' +
							'<option value="2">2x</option>' +
							'<option value="3">3x</option>' +
							'<option value="4">4x</option>' +
						'</select>' +
					'</label>' +
					'<label class="easy-settings-row">' +
						'<span id="easy-settings-speed-label"></span>' +
						'<input id="easy-settings-speed" type="number" min="150" max="1200" step="10">' +
					'</label>' +
					'<label class="easy-settings-toggle"><input id="easy-settings-doron" type="checkbox"><span id="easy-settings-doron-label"></span></label>' +
					'<label class="easy-settings-toggle"><input id="easy-settings-abekobe" type="checkbox"><span id="easy-settings-abekobe-label"></span></label>' +
					'<label class="easy-settings-toggle"><input id="easy-settings-detarame" type="checkbox"><span id="easy-settings-detarame-label"></span></label>' +
					'<label class="easy-settings-toggle"><input id="easy-settings-sort" type="checkbox"><span id="easy-settings-sort-label"></span></label>' +
				'</div>' +
				'<div class="easy-settings-footer">' +
					'<span id="easy-settings-leaderboard"></span>' +
					'<button id="easy-settings-reset" type="button"></button>' +
				'</div>' +
			'</div>'
		container.appendChild(overlay)

		var closeButton = overlay.querySelector("#easy-settings-close")
		var resetButton = overlay.querySelector("#easy-settings-reset")
		closeButton.addEventListener("click", close)
		resetButton.addEventListener("click", function () {
			saveSettings(DEFAULT_SETTINGS)
			renderSettings()
		})
		overlay.addEventListener("click", function (event) {
			if (event.target === overlay) {
				close()
			}
		})
		overlay.querySelector("#easy-settings-playback").addEventListener("input", function (event) {
			setSetting("playbackRate", event.target.value)
			renderSettings(false)
		})
		overlay.querySelector("#easy-settings-baisoku").addEventListener("change", function (event) {
			setSetting("baisoku", event.target.value)
			renderSettings(false)
		})
		overlay.querySelector("#easy-settings-speed").addEventListener("change", function (event) {
			setSetting("songSelectingSpeed", event.target.value)
			renderSettings(false)
		})
		overlay.querySelector("#easy-settings-doron").addEventListener("change", function (event) {
			setSetting("doron", event.target.checked)
			renderSettings(false)
		})
		overlay.querySelector("#easy-settings-abekobe").addEventListener("change", function (event) {
			setSetting("abekobe", event.target.checked)
			renderSettings(false)
		})
		overlay.querySelector("#easy-settings-detarame").addEventListener("change", function (event) {
			setSetting("detarame", event.target.checked)
			renderSettings(false)
		})
		overlay.querySelector("#easy-settings-sort").addEventListener("change", function (event) {
			setSetting("sortByTitle", event.target.checked)
			renderSettings(false)
		})
		renderStaticText()
		return overlay
	}

	function renderStaticText() {
		if (!overlay) {
			return
		}
		setText(overlay.querySelector("#easy-settings-heading"), getText("title", "Easy Settings"))
		setText(overlay.querySelector("#easy-settings-playback-label"), getText("playbackRate", "Playback Rate"))
		setText(overlay.querySelector("#easy-settings-baisoku-label"), getText("baisoku", "Note Speed"))
		setText(overlay.querySelector("#easy-settings-speed-label"), getText("songSelectingSpeed", "Song Select Speed"))
		setText(overlay.querySelector("#easy-settings-doron-label"), getText("doron", "Hidden Notes"))
		setText(overlay.querySelector("#easy-settings-abekobe-label"), getText("abekobe", "Reverse"))
		setText(overlay.querySelector("#easy-settings-detarame-label"), getText("detarame", "Random Notes"))
		setText(overlay.querySelector("#easy-settings-sort-label"), getText("sortByTitle", "Sort Current Category by Title"))
		setText(overlay.querySelector("#easy-settings-reset"), getText("reset", "Reset"))
	}

	function renderSettings(includeStaticText) {
		if (!overlay) {
			return
		}
		if (includeStaticText !== false) {
			renderStaticText()
		}
		var settings = getSettings()
		overlay.querySelector("#easy-settings-playback").value = settings.playbackRate
		setText(overlay.querySelector("#easy-settings-playback-value"), formatNumber(settings.playbackRate) + "x")
		overlay.querySelector("#easy-settings-baisoku").value = String(settings.baisoku)
		overlay.querySelector("#easy-settings-speed").value = settings.songSelectingSpeed
		overlay.querySelector("#easy-settings-doron").checked = settings.doron
		overlay.querySelector("#easy-settings-abekobe").checked = settings.abekobe
		overlay.querySelector("#easy-settings-detarame").checked = settings.detarame
		overlay.querySelector("#easy-settings-sort").checked = settings.sortByTitle
		var status = overlay.querySelector("#easy-settings-leaderboard")
		if (isLeaderboardEligible(settings)) {
			status.classList.remove("modified")
			setText(status, getText("leaderboardEnabled", "Leaderboard enabled"))
		} else {
			status.classList.add("modified")
			var reason = getLeaderboardBlockReason(settings)
			var text = getText("leaderboardDisabled", "Current settings do not support leaderboard")
			setText(status, reason ? text + ": " + reason : text)
		}
	}

	function initUI(songSelect) {
		activeSongSelect = songSelect || activeSongSelect
		ensureOverlay(activeSongSelect)
		var button = document.getElementById("song-easy-settings-btn")
		if (button) {
			button.title = getText("title", "Easy Settings")
			button.setAttribute("aria-label", getText("title", "Easy Settings"))
			var label = button.querySelector("span")
			if (label) {
				label.textContent = getText("button", "Easy")
			}
		}
		renderSettings()
	}

	function open(songSelect) {
		ensureOverlay(songSelect)
		if (!overlay) {
			return
		}
		opened = true
		renderSettings()
		overlay.hidden = false
		var firstInput = overlay.querySelector("input, select, button")
		if (firstInput) {
			firstInput.focus()
		}
		notifyVisibility()
	}

	function close() {
		if (!overlay) {
			return
		}
		opened = false
		overlay.hidden = true
		notifyVisibility()
	}

	function isOpen() {
		return opened
	}

	function notifyVisibility() {
		if (activeSongSelect && typeof activeSongSelect.updateSearchButtonVisibility === "function") {
			activeSongSelect.updateSearchButtonVisibility()
		}
	}

	function notifyChange() {
		renderSettings(false)
		var settings = getSettings()
		if (activeSongSelect && typeof activeSongSelect.onEasySettingsChanged === "function") {
			activeSongSelect.onEasySettingsChanged(settings)
		}
		if (typeof window.CustomEvent === "function") {
			window.dispatchEvent(new CustomEvent("easysettingschange", {
				detail: settings
			}))
		}
	}

	loadSettings()

	window.EasySettings = {
		defaultSettings: Object.assign({}, DEFAULT_SETTINGS),
		getSettings: getSettings,
		setSetting: setSetting,
		loadSettings: loadSettings,
		saveSettings: saveSettings,
		sanitizeSettings: sanitizeSettings,
		isModifiedGameplay: isModifiedGameplay,
		isLeaderboardEligible: isLeaderboardEligible,
		getLeaderboardBlockReason: getLeaderboardBlockReason,
		getPlaybackRate: getPlaybackRate,
		getBaisoku: getBaisoku,
		getSongTitle: getSongTitle,
		initUI: initUI,
		open: open,
		close: close,
		isOpen: isOpen
	}
})()
