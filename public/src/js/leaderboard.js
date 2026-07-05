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
		this.overlay.innerHTML = `
			<div class="leaderboard-container">
				<div class="leaderboard-header">
					<h2 class="leaderboard-title">${strings.leaderboardTitle.replace("%s", songTitle)}</h2>
					<button class="leaderboard-close" type="button" aria-label="${strings.back}" title="${strings.back}">x</button>
				</div>
				<div class="leaderboard-content">
					<div class="leaderboard-loading">Loading...</div>
				</div>
				<div class="leaderboard-user-rank"></div>
			</div>
		`
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
			if (this.visible && (e.key === "Escape" || e.key === "Esc")) {
				this.hide()
			}
		}
		this.closeButton = this.overlay.querySelector(".leaderboard-close")
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

		if (!this.data || this.data.length === 0) {
			content.innerHTML = `<div class="leaderboard-empty">${strings.noScores}</div>`
			return
		}

		let html = '<ul class="leaderboard-list">'
		for (const entry of this.data) {
			const rankClass = entry.rank <= 3 ? `rank-${entry.rank}` : ""
			html += `
				<li class="leaderboard-item ${rankClass}">
					<span class="leaderboard-rank">${entry.rank}.</span>
					<span class="leaderboard-name">${this.escapeHtml(entry.display_name)}</span>
					<span class="leaderboard-score">${entry.score_value.toLocaleString()}${strings.points}</span>
				</li>
			`
		}
		html += '</ul>'
		content.innerHTML = html
	}

	renderError() {
		const content = this.overlay.querySelector(".leaderboard-content")
		content.innerHTML = `<div class="leaderboard-error">${strings.errorOccured}</div>`
	}

	escapeHtml(str) {
		if (!str) return ""
		return str.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
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
