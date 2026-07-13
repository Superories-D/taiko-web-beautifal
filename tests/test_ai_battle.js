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

test("difficulty thresholds, round outcomes and match outcomes are exact", () => {
	assert.equal(core.thresholdForDifficulty("easy"), 10)
	assert.equal(core.thresholdForDifficulty("normal"), 10)
	assert.equal(core.thresholdForDifficulty("hard"), 30)
	assert.equal(core.thresholdForDifficulty("oni"), 50)
	assert.equal(core.thresholdForDifficulty("ura"), 50)
	assert.equal(core.resolveRound(20, 11, 10), "draw")
	assert.equal(core.resolveRound(21, 11, 10), "player")
	assert.equal(core.resolveRound(11, 21, 10), "ai")
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
	for (let i = 1; i < rates.length; i++) assert.ok(rates[i - 1] > rates[i] + 0.04, rates.join(","))
})

test("Easy Settings resets and locks other options while AI is enabled", () => {
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
	context.EasySettings.setSetting("aiState", "excellent")
	assert.equal(context.EasySettings.getSettings().aiState, "excellent")
	assert.equal(context.EasySettings.isLeaderboardEligible(), false)
})
