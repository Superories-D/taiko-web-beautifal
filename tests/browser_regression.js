const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const { chromium } = require("playwright")

const baseUrl = (process.env.TAIKO_BROWSER_BASE_URL || "http://127.0.0.1:34940").replace(/\/$/, "")
const outputDir = path.resolve(process.env.TAIKO_BROWSER_OUTPUT_DIR || "browser-artifacts")
const adminPassword = process.env.TAIKO_BROWSER_ADMIN_PASSWORD

if (!adminPassword) {
	throw new Error("TAIKO_BROWSER_ADMIN_PASSWORD is required for the admin browser regression")
}

fs.mkdirSync(outputDir, { recursive: true })

function installErrorCapture(page, errors) {
	const ignored = /WebSocket|\/p2(?:\?|$)|ERR_CONNECTION_REFUSED.*p2/i
	page.on("console", message => {
		if (message.type() === "error" && !ignored.test(message.text())) {
			errors.push("console: " + message.text())
		}
	})
	page.on("pageerror", error => errors.push("page: " + error.message))
	page.on("requestfailed", request => {
		const detail = request.failure() && request.failure().errorText || ""
		if (!ignored.test(request.url() + " " + detail)) {
			errors.push("request: " + request.url() + " " + detail)
		}
	})
}

async function preparePage(context, viewport, errors) {
	const page = await context.newPage()
	installErrorCapture(page, errors)
	await page.setViewportSize(viewport)
	await page.addInitScript(() => {
		localStorage.setItem("tutorial", "true")
		localStorage.setItem("lang", "en")
		localStorage.setItem("settings", "{}")
	})
	await page.goto(baseUrl + "/en", { waitUntil: "domcontentloaded", timeout: 60000 })
	await page.waitForSelector("#title-screen", { state: "visible", timeout: 90000 })
	await page.keyboard.press("Enter")
	await page.waitForSelector("#song-select", { state: "visible", timeout: 30000 })
	await page.waitForFunction(() => {
		return ["#song-search-btn", "#weekly-challenge-btn", "#song-easy-settings-btn"]
			.every(selector => {
				const element = document.querySelector(selector)
				return element && !element.hidden
			})
	})
	return page
}

async function testLeaderboardXss(page) {
	const song = await page.evaluate(() => {
		const candidate = assets.songs.find(item => item.courses && item.courses.oni)
		return {
			hash: candidate.hash,
			title: candidate.title,
			difficulty: "oni"
		}
	})
	const malicious = "<img src=x onerror=window.__xss=1>"
	const submitted = await page.evaluate(async ({ song, malicious }) => {
		const tokenResponse = await fetch("api/csrftoken", { cache: "no-store" })
		const token = await tokenResponse.json()
		const response = await fetch("api/leaderboard/submit", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"X-CSRFToken": token.token
			},
			body: JSON.stringify({
				hash: song.hash,
				difficulty: song.difficulty,
				display_name: malicious,
				score: 654321
			})
		})
		return { status: response.status, data: await response.json() }
	}, { song, malicious })
	assert.equal(submitted.status, 200)
	assert.equal(submitted.data.status, "ok")

	await page.evaluate(({ song, malicious }) => {
		window.__xss = 0
		return leaderboard.show(song.hash, malicious, song.difficulty)
	}, { song, malicious })
	await page.waitForSelector("#leaderboard-overlay .leaderboard-item")
	const dom = await page.evaluate(malicious => ({
		xss: window.__xss,
		images: document.querySelectorAll("#leaderboard-overlay img").length,
		title: document.querySelector(".leaderboard-title").textContent,
		names: Array.from(document.querySelectorAll(".leaderboard-name"), item => item.textContent)
	}), malicious)
	assert.equal(dom.xss, 0)
	assert.equal(dom.images, 0)
	assert.ok(dom.title.includes(malicious))
	assert.ok(dom.names.some(name => name.startsWith("<img")))
	await page.locator(".leaderboard-close").click()
}

async function testSongSelectModals(page, prefix) {
	await page.locator("#weekly-challenge-btn").click()
	await page.waitForSelector("#weekly-challenge-container", { state: "visible" })
	await page.waitForFunction(() => {
		const countdown = document.querySelector(".weekly-challenge-reset")
		return countdown && /^UTC \d+d \d{2}:\d{2}:\d{2}$/.test(countdown.textContent)
	})
	assert.equal(await page.locator("#site-message-button").getAttribute("hidden"), "")
	await page.screenshot({ path: path.join(outputDir, prefix + "-weekly.png") })
	await page.locator("#weekly-challenge-close").click({ force: true })

	await page.locator("#song-search-btn").click()
	await page.waitForSelector("#song-search-container", { state: "visible" })
	assert.equal(await page.locator("#site-message-button").getAttribute("hidden"), "")
	await page.locator("#song-search-input").fill("a")
	await page.waitForSelector(".song-search-result")
	await page.screenshot({ path: path.join(outputDir, prefix + "-search.png") })
	await page.locator("#song-search-close").click({ force: true })

	await page.locator("#song-easy-settings-btn").click()
	await page.waitForSelector("#easy-settings-overlay", { state: "visible" })
	assert.equal(await page.locator("#site-message-button").getAttribute("hidden"), "")
	await page.locator("#easy-settings-close").click({ force: true })
}

async function testAdmin(browser) {
	// Keep the admin session isolated from outstanding game requests that can set an
	// anonymous session cookie after navigation.
	const context = await browser.newContext()
	const page = await context.newPage()
	try {
		await page.goto(baseUrl + "/1128admin1128", { waitUntil: "domcontentloaded" })
		await page.locator("#username").fill("roll4_browser_admin")
		await page.locator("#password").fill(adminPassword)
		await Promise.all([
			page.waitForURL(/\/admin\/overview$/),
			page.locator("button[type=submit]").click()
		])
		const text = await page.locator("main").innerText()
		assert.match(text, /Playable songs\s+230/)
		assert.match(text, /Missing files\s+7/)
		await page.screenshot({ path: path.join(outputDir, "admin-overview.png"), fullPage: true })
	} finally {
		await context.close()
	}
}

async function main() {
	const browser = await chromium.launch({
		headless: true,
		executablePath: process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe"
	})
	const context = await browser.newContext()
	const errors = []
	try {
		const desktop = await preparePage(context, { width: 1440, height: 900 }, errors)
		assert.equal((await desktop.evaluate(() => assets.songs.length)), 230)
		await testLeaderboardXss(desktop)
		await testSongSelectModals(desktop, "desktop")
		await desktop.screenshot({ path: path.join(outputDir, "desktop-songselect.png") })
		await testAdmin(browser)

		const mobile = await preparePage(context, { width: 390, height: 844 }, errors)
		await testSongSelectModals(mobile, "mobile")
		const layout = await mobile.evaluate(() => ({
			viewport: innerWidth,
			documentWidth: document.documentElement.scrollWidth,
			weeklyWidth: document.querySelector("#weekly-challenge")?.getBoundingClientRect().width || 0
		}))
		assert.ok(layout.documentWidth <= layout.viewport + 1)
		assert.ok(layout.weeklyWidth <= layout.viewport)
		await mobile.close()

		assert.deepEqual(errors, [])
		console.log(JSON.stringify({
			status: "ok",
			desktop: "1440x900",
			mobile: "390x844",
			publicSongs: 230,
			errors
		}))
	} finally {
		await context.close()
		await browser.close()
	}
}

main().catch(error => {
	console.error(error)
	process.exit(1)
})
