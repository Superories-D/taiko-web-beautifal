const test = require("node:test")
const assert = require("node:assert/strict")
const {createFakeDocument, findElements} = require("./helpers/fake_dom.js")
const Leaderboard = require("../public/src/js/leaderboard.js")

const xssTitles = [
	"<script>alert(1)</script>",
	"<img src=x onerror=alert(1)>",
	"\"><svg onload=alert(1)>",
	"<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>",
	"javascript:alert(1)",
	"&lt;script&gt;alert(1)&lt;/script&gt;"
]

function installDom() {
	const previousDocument = global.document
	const previousStrings = global.strings
	global.document = createFakeDocument()
	global.strings = {
		leaderboardTitle: "Leaderboard: %s",
		back: "Back",
		noScores: "No scores",
		errorOccured: "Error",
		points: " pts"
	}
	return () => {
		if (typeof previousDocument === "undefined") delete global.document
		else global.document = previousDocument
		if (typeof previousStrings === "undefined") delete global.strings
		else global.strings = previousStrings
	}
}

test("song titles are rendered as text in the leaderboard header", async () => {
	const restore = installDom()
	try {
		for (const payload of xssTitles) {
			const board = new Leaderboard()
			board.addStyles = () => {}
			board.fetchData = async () => {}
			await board.show("song-hash", payload, "oni")

			const title = board.overlay.querySelector(".leaderboard-title")
			assert.equal(title.textContent, "Leaderboard: " + payload)
			assert.equal(title.children.length, 0)
			assert.deepEqual(findElements(board.overlay, ["script", "img", "svg", "iframe"]), [])
			board.hide()
		}
	} finally {
		restore()
	}
})

test("leaderboard entries, empty state, and error state use text nodes", () => {
	const restore = installDom()
	try {
		const board = new Leaderboard()
		board.overlay = document.createElement("div")
		const content = document.createElement("div")
		content.className = "leaderboard-content"
		board.overlay.appendChild(content)
		document.body.appendChild(board.overlay)

		board.data = [{rank: 1, display_name: xssTitles[1], score_value: 1234567}]
		board.render()
		assert.equal(content.querySelector(".leaderboard-name").textContent, xssTitles[1])
		const scoreText = content.querySelector(".leaderboard-score").textContent
		assert.equal(scoreText.replace(/\D/g, ""), "1234567")
		assert.ok(scoreText.endsWith(" pts"))
		assert.deepEqual(findElements(content, ["script", "img", "svg", "iframe"]), [])

		board.data = []
		board.render()
		assert.equal(content.querySelector(".leaderboard-empty").textContent, "No scores")

		board.renderError()
		assert.equal(content.querySelector(".leaderboard-error").textContent, "Error")
	} finally {
		restore()
	}
})

test("multilingual and special-character titles remain unchanged", async () => {
	const restore = installDom()
	const titles = [
		"正常中文标题",
		"正常な日本語タイトル",
		"정상적인 한국어 제목",
		"Quotes \" ' <angle> [brackets] & emoji 🎵"
	]
	try {
		for (const titleText of titles) {
			const board = new Leaderboard()
			board.addStyles = () => {}
			board.fetchData = async () => {}
			await board.show("song-hash", titleText, "")
			assert.equal(board.overlay.querySelector(".leaderboard-title").textContent, "Leaderboard: " + titleText)
			board.hide()
		}
	} finally {
		restore()
	}
})
