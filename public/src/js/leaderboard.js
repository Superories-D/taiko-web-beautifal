class Leaderboard {
	constructor() {
		this.visible = false
		this.data = null
		this.songTitle = ""
		this.songHash = ""
		this.difficulty = ""
	}

	async show(songHash, songTitle, difficulty) {
		this.songHash = songHash
		this.songTitle = songTitle
		this.difficulty = difficulty
		this.visible = true
		this.data = null

		// Create overlay
		this.overlay = document.createElement("div")
		this.overlay.id = "leaderboard-overlay"
		const container = document.createElement("div")
		container.className = "leaderboard-container"
		const header = document.createElement("div")
		header.className = "leaderboard-header"
		const title = document.createElement("h2")
		title.className = "leaderboard-title"
		title.textContent = strings.leaderboardTitle.replace("%s", String(songTitle || ""))
		const closeButton = document.createElement("button")
		closeButton.className = "leaderboard-close"
		closeButton.type = "button"
		closeButton.setAttribute("aria-label", strings.back)
		closeButton.setAttribute("title", strings.back)
		closeButton.textContent = "x"
		const content = document.createElement("div")
		content.className = "leaderboard-content"
		const loading = document.createElement("div")
		loading.className = "leaderboard-loading"
		loading.textContent = "Loading..."
		const userRank = document.createElement("div")
		userRank.className = "leaderboard-user-rank"

		header.appendChild(title)
		header.appendChild(closeButton)
		content.appendChild(loading)
		container.appendChild(header)
		container.appendChild(content)
		container.appendChild(userRank)
		this.overlay.appendChild(container)
		document.body.appendChild(this.overlay)

		// Add styles
		this.addStyles()

		// Bind close only to the explicit close button so mobile scrolling does not dismiss the modal.
		this.closeHandler = event => {
			event.preventDefault()
			event.stopPropagation()
			this.hide()
		}
		this.keyHandler = (e) => {
			const key = String(e.key || "").toLowerCase()
			if (this.visible && ["escape", "esc", "d", "f", "j", "k"].indexOf(key) !== -1) {
				e.preventDefault()
				e.stopPropagation()
				this.hide()
			}
		}
		this.closeButton = closeButton
		this.closeButton.addEventListener("click", this.closeHandler)
		this.closeButton.addEventListener("touchend", this.closeHandler)
		document.addEventListener("keydown", this.keyHandler)

		// Fetch data
		await this.fetchData()
	}

	async fetchData() {
		try {
			const url = `api/leaderboard/get?hash=${encodeURIComponent(this.songHash)}&difficulty=${encodeURIComponent(this.difficulty)}`
			const response = await fetch(url)
			const data = await response.json()

			if (data.status === "ok") {
				this.data = data.leaderboard
				this.render()
			}
		} catch (e) {
			console.error("Failed to fetch leaderboard:", e)
			this.renderError()
		}
	}

	render() {
		const content = this.overlay.querySelector(".leaderboard-content")
		this.clearElement(content)

		if (!this.data || this.data.length === 0) {
			const empty = document.createElement("div")
			empty.className = "leaderboard-empty"
			empty.textContent = strings.noScores
			content.appendChild(empty)
			return
		}

		const list = document.createElement("ul")
		list.className = "leaderboard-list"
		for (const entry of this.data) {
			const rankValue = Number(entry.rank)
			const rank = Number.isInteger(rankValue) && rankValue > 0 ? rankValue : 0
			const item = document.createElement("li")
			item.className = "leaderboard-item"
			if (rank >= 1 && rank <= 3) {
				item.classList.add(`rank-${rank}`)
			}

			const rankElement = document.createElement("span")
			rankElement.className = "leaderboard-rank"
			rankElement.textContent = `${rank}.`
			const nameElement = document.createElement("span")
			nameElement.className = "leaderboard-name"
			nameElement.textContent = String(entry.display_name || "")
			const scoreElement = document.createElement("span")
			scoreElement.className = "leaderboard-score"
			const scoreValue = Number(entry.score_value)
			const score = Number.isFinite(scoreValue) ? scoreValue : 0
			scoreElement.textContent = `${score.toLocaleString()}${strings.points}`

			item.appendChild(rankElement)
			item.appendChild(nameElement)
			item.appendChild(scoreElement)
			list.appendChild(item)
		}
		content.appendChild(list)
	}

	renderError() {
		const content = this.overlay.querySelector(".leaderboard-content")
		this.clearElement(content)
		const error = document.createElement("div")
		error.className = "leaderboard-error"
		error.textContent = strings.errorOccured
		content.appendChild(error)
	}

	clearElement(element) {
		while (element.firstChild) {
			element.removeChild(element.firstChild)
		}
	}

	hide() {
		if (this.overlay) {
			this.overlay.remove()
			this.overlay = null
		}
		if (this.keyHandler) {
			document.removeEventListener("keydown", this.keyHandler)
			this.keyHandler = null
		}
		this.visible = false
	}

	addStyles() {
		if (document.getElementById("leaderboard-styles")) return

		const style = document.createElement("style")
		style.id = "leaderboard-styles"
		style.textContent = `
			#leaderboard-overlay {
				position: fixed;
				top: 0;
				left: 0;
				width: 100%;
				height: 100%;
				background: rgba(0, 0, 0, 0.7);
				display: flex;
				justify-content: center;
				align-items: center;
				z-index: 1000;
				box-sizing: border-box;
				padding: max(10px, env(safe-area-inset-top, 0px)) max(10px, env(safe-area-inset-right, 0px)) max(10px, env(safe-area-inset-bottom, 0px)) max(10px, env(safe-area-inset-left, 0px));
			}
			.leaderboard-container {
				background: linear-gradient(135deg, #fff9e6 0%, #ffffff 100%);
				border-radius: 15px;
				box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
				width: min(100%, 700px);
				max-width: 700px;
				max-height: min(80vh, 100%);
				overflow: hidden;
				display: flex;
				flex-direction: column;
			}
			.leaderboard-header {
				background: linear-gradient(90deg, #ff6b6b 0%, #ff8e53 100%);
				padding: 15px 20px;
				display: flex;
				align-items: center;
				gap: 15px;
				flex: 0 0 auto;
			}
			.leaderboard-close {
				background: #fff;
				border: none;
				display: grid;
				place-items: center;
				flex: 0 0 auto;
				width: 44px;
				height: 44px;
				padding: 0;
				border-radius: 50%;
				cursor: pointer;
				font-weight: bold;
				font-size: 24px;
				line-height: 1;
				color: #ff6b6b;
				transition: transform 0.1s;
				position: relative;
				z-index: 2;
				touch-action: manipulation;
			}
			.leaderboard-close:hover {
				transform: scale(1.05);
			}
			.leaderboard-title {
				color: #fff;
				font-size: 1.3em;
				margin: 0;
				text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
				flex: 1;
				min-width: 0;
				overflow-wrap: anywhere;
			}
			.leaderboard-content {
				padding: 20px;
				overflow-y: auto;
				flex: 1;
				min-height: 0;
				overscroll-behavior: contain;
				-webkit-overflow-scrolling: touch;
				touch-action: pan-y;
			}
			.leaderboard-list {
				list-style: none;
				padding: 0;
				margin: 0;
			}
			.leaderboard-item {
				display: flex;
				align-items: center;
				padding: 12px 15px;
				margin: 5px 0;
				background: rgba(255, 255, 255, 0.8);
				border-radius: 10px;
				border-left: 4px solid #ddd;
				transition: transform 0.1s;
			}
			.leaderboard-item:hover {
				transform: translateX(5px);
			}
			.leaderboard-item.rank-1 {
				background: linear-gradient(90deg, #ffd700 0%, #fff9e6 30%);
				border-left-color: #ffd700;
			}
			.leaderboard-item.rank-2 {
				background: linear-gradient(90deg, #c0c0c0 0%, #fff 30%);
				border-left-color: #c0c0c0;
			}
			.leaderboard-item.rank-3 {
				background: linear-gradient(90deg, #cd7f32 0%, #fff5eb 30%);
				border-left-color: #cd7f32;
			}
			.leaderboard-rank {
				font-weight: bold;
				font-size: 1.2em;
				width: 50px;
				color: #333;
			}
			.leaderboard-name {
				flex: 1;
				color: #444;
				overflow: hidden;
				text-overflow: ellipsis;
				white-space: nowrap;
			}
			.leaderboard-score {
				font-weight: bold;
				color: #ff6b6b;
				font-size: 1.1em;
			}
			.leaderboard-empty, .leaderboard-loading, .leaderboard-error {
				text-align: center;
				padding: 40px;
				color: #666;
				font-size: 1.2em;
			}
			.leaderboard-user-rank {
				background: #f0f0f0;
				padding: 15px;
				text-align: center;
				flex: 0 0 auto;
			}
			.user-rank-text {
				font-weight: bold;
				color: #ff6b6b;
				font-size: 1.2em;
			}
			@media (max-width: 520px) {
				.leaderboard-header {
					padding: 12px 14px;
					gap: 10px;
				}
				.leaderboard-title {
					font-size: 1.08em;
				}
				.leaderboard-close {
					width: 44px;
					height: 44px;
					font-size: 22px;
				}
				.leaderboard-content {
					padding: 12px;
				}
				.leaderboard-item {
					gap: 8px;
					padding: 10px 12px;
				}
				.leaderboard-rank {
					width: 42px;
				}
				.leaderboard-score {
					font-size: 1em;
				}
			}
		`
		document.head.appendChild(style)
	}
}

var leaderboard = new Leaderboard()

if (typeof module !== "undefined") {
	module.exports = Leaderboard
}
