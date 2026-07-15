"use strict"

const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

const core = require(path.join(__dirname, "..", "public", "src", "js", "aibattle.js"))

test("seeded RNG and random state selection are deterministic", () => {
	const first = core.createRng("song:oni:run")
	const second = core.createRng("song:oni:run")
	assert.deepEqual(Array.from({length: 20}, first), Array.from({length: 20}, second))
	assert.equal(core.resolveState("normal", first), "normal")
})

test("weighted random states follow the configured distribution", () => {
	const rng = core.createRng("weighted-distribution")
	const counts = Object.fromEntries(core.STATES.map(state => [state, 0]))
	const total = 100000
	for (let i = 0; i < total; i++) counts[core.chooseState(rng)]++
	core.STATES.forEach((state, index) => {
		assert.ok(Math.abs(counts[state] / total - core.WEIGHTS[index]) < 0.008, state)
	})
})

test("five-way note splitting is balanced including very short charts", () => {
	assert.deepEqual(core.splitCounts(103, 5), [21, 21, 21, 20, 20])
	assert.deepEqual(core.splitCounts(3, 5), [1, 1, 1, 0, 0])
	assert.deepEqual(core.splitCounts(0, 5), [0, 0, 0, 0, 0])
})

test("difficulty thresholds use a central 50 percent draw zone", () => {
	assert.equal(core.thresholdForDifficulty("easy"), 10)
	assert.equal(core.thresholdForDifficulty("normal"), 10)
	assert.equal(core.thresholdForDifficulty("hard"), 30)
	assert.equal(core.thresholdForDifficulty("oni"), 50)
	assert.equal(core.thresholdForDifficulty("ura"), 50)
	assert.equal(core.roundWinThreshold(10), 5)
	assert.equal(core.roundWinThreshold(30), 15)
	assert.equal(core.roundWinThreshold(50), 25)
	assert.equal(core.resolveRound(20, 16, 10), "draw")
	assert.equal(core.resolveRound(20, 15, 10), "player")
	assert.equal(core.resolveRound(15, 20, 10), "ai")
	assert.equal(core.resolveRound(114, 100, 30), "draw")
	assert.equal(core.resolveRound(115, 100, 30), "player")
	assert.equal(core.resolveRound(100, 124, 50), "draw")
	assert.equal(core.resolveRound(100, 125, 50), "ai")
	assert.equal(core.resolveRound(100, 100, 10), "draw")
	assert.equal(core.resolveMatch(["player", "draw", "ai", "player", "draw"]), "player")
	assert.equal(core.resolveMatch(["player", "ai", "draw", "draw", "draw"]), "draw")
})

test("AI mode conflicts with both auto play and multiplayer", () => {
	assert.equal(core.hasModeConflict(true, true, false), true)
	assert.equal(core.hasModeConflict(true, false, true), true)
	assert.equal(core.hasModeConflict(true, true, true), true)
	assert.equal(core.hasModeConflict(true, false, false), false)
	assert.equal(core.hasModeConflict(false, true, true), false)
})

test("AI form tiers retain the intended ordering over seeded decisions", () => {
	function goodRate(state) {
		const controller = {game: {rules: {good: 25, ok: 75, bad: 108}}}
		const player = new core.AIBattlePlayer(controller, state, "tier:" + state)
		let good = 0
		const total = 12000
		for (let i = 0; i < total; i++) {
			if (player.decide({type: "don", ms: i * 240}).score === 450) good++
		}
		return good / total
	}
	const rates = core.STATES.map(goodRate)
	assert.ok(rates[0] > 0.94 && rates[0] < 0.96, rates.join(","))
	assert.ok(rates[1] > 0.885 && rates[1] < 0.915, rates.join(","))
	for (let i = 1; i < rates.length; i++) assert.ok(rates[i - 1] > rates[i] + 0.015, rates.join(","))
})

test("player branch changes never force the AI branch", () => {
	let aiBranchChanges = 0
	const coordinator = Object.create(core.AIBattleCoordinator.prototype)
	Object.assign(coordinator, {
		closed: false,
		currentSegment: 0,
		boundaries: [100, 200, 300, 400, 500],
		secondary: {game: {setBranch() { aiBranchChanges++ }}},
		activeNotes() { return [{ms: 210}, {ms: 310}, {ms: 410}, {ms: 510}] }
	})
	coordinator.onBranchChange(150, "normal")
	assert.equal(aiBranchChanges, 0)
})

test("round result overlay is a game-level sibling of the HUD", () => {
	function classList() {
		const values = new Set()
		return {
			add(...names) { names.forEach(name => values.add(name)) },
			remove(...names) { names.forEach(name => values.delete(name)) },
			toggle(name, enabled) { enabled ? values.add(name) : values.delete(name) }
		}
	}
	function element() {
		const parts = {
			".ai-battle-form": {classList: classList()},
			".ai-battle-player": {style: {}},
			".ai-battle-ai": {style: {}}
		}
		return {
			children: [],
			classList: classList(),
			style: {},
			appendChild(child) { child.parentNode = this; this.children.push(child) },
			removeChild(child) { this.children = this.children.filter(item => item !== child); child.parentNode = null },
			querySelector(selector) { return parts[selector] },
			setAttribute(name, value) { this[name] = value }
		}
	}
	const game = element()
	const oldDocument = global.document
	const oldTimeout = global.setTimeout
	global.document = {
		getElementById(id) { return id === "game" ? game : null },
		createElement() { return element() }
	}
	global.setTimeout = callback => { callback(); return 0 }
	try {
		const coordinator = Object.create(core.AIBattleCoordinator.prototype)
		Object.assign(coordinator, {
			secondary: {aiPlayer: {state: "normal"}},
			scores: Array.from({length: 5}, () => [0, 0]),
			threshold: 10,
			currentSegment: 0,
			closed: false
		})
		coordinator.createHud()
		assert.equal(game.children.length, 2)
		assert.equal(coordinator.hud.parentNode, game)
		assert.equal(coordinator.resultBox.parentNode, game)
		assert.notEqual(coordinator.resultBox.parentNode, coordinator.hud)
		coordinator.clean()
		assert.equal(game.children.length, 0)
	} finally {
		global.document = oldDocument
		global.setTimeout = oldTimeout
	}
})

test("AI battle HUD uses a compact responsive status ribbon", () => {
	const css = fs.readFileSync(path.join(__dirname, "..", "public", "src", "css", "game.css"), "utf8")
	assert.match(css, /#ai-battle-hud\s*\{[\s\S]*?grid-template-areas:\s*"form bar rounds"/)
	assert.match(css, /\.touchp2 #ai-battle-hud\s*\{[\s\S]*?width:\s*clamp\(280px,\s*50vw,\s*620px\)/)
	assert.match(css, /\.touchp2 #ai-battle-hud \.ai-battle-form\.quiet\s*\{[\s\S]*?opacity:\s*0/)
	assert.match(css, /\.portrait #ai-battle-hud\s*\{[\s\S]*?safe-area-inset-top/)
	assert.match(css, /@media \(max-width:\s*600px\) and \(orientation:\s*portrait\)/)
	assert.match(css, /grid-template-areas:\s*"bar rounds"/)
	assert.match(css, /\.ai-battle-form\.quiet\s*\{[\s\S]*?opacity:\s*0/)
	assert.doesNotMatch(css, /\.portrait #ai-battle-hud\s*\{[\s\S]{0,100}?top:\s*max\(42px,\s*5vh\)/)
})

test("ghost battle results keep the opponent score and label it as 幽灵", () => {
	const source = fs.readFileSync(path.join(__dirname, "..", "public", "src", "js", "scoresheet.js"), "utf8")
	assert.match(source, /this\.ghostBattle = !!controller\.ghostBattle/)
	assert.match(source, /this\.battleMode = this\.aiBattle \|\| this\.ghostBattle/)
	assert.match(source, /this\.ghostBattle \? "幽灵"/)
})

test("AI consumes dense triplets and alternating notes in one frame", () => {
	const circles = [
		{type: "don", ms: 90},
		{type: "ka", ms: 94},
		{type: "don", ms: 98}
	]
	const played = []
	const game = {
		currentCircle: 0,
		elapsedTime: 100,
		rules: {good: 25, ok: 75, bad: 108},
		songData: {circles},
		updateCurrentCircle() { this.currentCircle++ },
		skipNote(circle) { circle.isPlayed = true; this.currentCircle++ }
	}
	const controller = {
		game,
		audioLatency: 0,
		mekadon: {
			playNow(circle) {
				played.push(circle.type)
				circle.isPlayed = true
				game.currentCircle++
			},
			playDrumrollAt() {}
		}
	}
	const player = new core.AIBattlePlayer(controller, "excellent", "dense-triplet")
	player.decide = () => ({score: 450, offset: 0, miss: false, reverse: false, dai: 0})
	player.update()
	assert.deepEqual(played, ["don", "ka", "don"])
})

test("Easy Settings keeps title sorting available while AI is enabled", () => {
	const storage = new Map()
	const context = {
		console,
		setTimeout,
		clearTimeout,
		CustomEvent: function () {},
		localStorage: {
			getItem: key => storage.has(key) ? storage.get(key) : null,
			setItem: (key, value) => storage.set(key, String(value))
		},
		dispatchEvent() {},
		p2: null
	}
	context.window = context
	vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "public", "src", "js", "easysettings.js"), "utf8"), context)
	context.EasySettings.setSetting("baisoku", 4)
	context.EasySettings.setSetting("doron", true)
	context.EasySettings.setSetting("aiBattleEnabled", true)
	let settings = context.EasySettings.getSettings()
	assert.equal(settings.aiBattleEnabled, true)
	assert.equal(settings.baisoku, 1)
	assert.equal(settings.doron, false)
	context.EasySettings.setSetting("baisoku", 3)
	settings = context.EasySettings.getSettings()
	assert.equal(settings.baisoku, 1)
	context.EasySettings.setSetting("sortByTitle", true)
	settings = context.EasySettings.getSettings()
	assert.equal(settings.sortByTitle, true)
	assert.equal(context.EasySettings.sanitizeSettings(settings).sortByTitle, true)
	context.EasySettings.setSetting("aiState", "excellent")
	assert.equal(context.EasySettings.getSettings().aiState, "excellent")
	assert.equal(context.EasySettings.isLeaderboardEligible(), false)
})

test("Easy Settings refuses to enable AI during multiplayer", () => {
	const storage = new Map()
	const context = {
		console,
		setTimeout,
		clearTimeout,
		CustomEvent: function () {},
		localStorage: {
			getItem: key => storage.has(key) ? storage.get(key) : null,
			setItem: (key, value) => storage.set(key, String(value))
		},
		dispatchEvent() {},
		p2: {session: true, otherConnected: true, hashLock: true, aiBattleBlocked: false}
	}
	context.window = context
	vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "public", "src", "js", "easysettings.js"), "utf8"), context)
	assert.equal(context.EasySettings.isMultiplayerActive(), true)
	let settings = context.EasySettings.getSettings()
	assert.equal(settings.sortByTitle, true)
	assert.equal(settings.aiBattleEnabled, false)
	assert.equal(settings.baisoku, 1)
	context.EasySettings.setSetting("aiBattleEnabled", true)
	assert.equal(context.EasySettings.getSettings().aiBattleEnabled, false)
	context.EasySettings.setSetting("sortByTitle", false)
	assert.equal(context.EasySettings.getSettings().sortByTitle, true)
	context.EasySettings.saveSettings({baisoku: 4, doron: true, sortByTitle: false})
	settings = context.EasySettings.getSettings()
	assert.equal(settings.baisoku, 1)
	assert.equal(settings.doron, false)
	assert.equal(settings.sortByTitle, true)
	context.p2.session = false
	context.p2.otherConnected = false
	assert.equal(context.EasySettings.isMultiplayerActive(), true)
	context.EasySettings.setSetting("aiBattleEnabled", true)
	assert.equal(context.EasySettings.getSettings().aiBattleEnabled, false)
	context.p2.hashLock = false
	assert.equal(context.EasySettings.isMultiplayerActive(), false)
	context.EasySettings.setSetting("sortByTitle", false)
	assert.equal(context.EasySettings.getSettings().sortByTitle, false)
})
