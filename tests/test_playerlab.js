const test = require("node:test")
const assert = require("node:assert/strict")

global.localStorage = {
	data: {},
	getItem(key) { return this.data[key] ?? null },
	setItem(key, value) { this.data[key] = String(value) }
}

const PlayerLab = require("../public/src/js/playerlab.js")

test("practice mode trims and rebases chart data", () => {
	const controller = {
		selectedSong: {practiceMode: {start: 10, end: 20, loop: true}},
		parsedSongData: {
			circles: [
				{ms: 9000, endTime: 9000},
				{ms: 10000, endTime: 10000},
				{ms: 19000, endTime: 19000},
				{ms: 21000, endTime: 21000}
			],
			events: [{ms: 9500}, {ms: 12000}, {ms: 22000}],
			measures: [],
			timingPoints: []
		},
		offset: 250,
		saveScore: true
	}
	assert.equal(PlayerLab.applyPractice(controller), true)
	assert.deepEqual(controller.parsedSongData.circles.map(note => note.ms), [1500, 10500])
	assert.deepEqual(controller.parsedSongData.events.map(event => event.ms), [1000, 3500])
	assert.equal(controller.offset, 8750)
	assert.equal(controller.saveScore, false)
	assert.equal(controller.practiceMode.loop, true)
})

test("practice mode rejects an empty range without changing score eligibility", () => {
	const controller = {
		selectedSong: {practiceMode: {start: 30, end: 40}},
		parsedSongData: {circles: [{ms: 1000, endTime: 1000}]},
		offset: 0,
		saveScore: true
	}
	assert.equal(PlayerLab.applyPractice(controller), false)
	assert.equal(controller.saveScore, true)
	assert.equal(controller.selectedSong.practiceMode, null)
})

test("ghost race records compact judgements and only replaces the best run", () => {
	localStorage.data = {}
	const song = {hash: "song-hash", difficulty: "oni"}
	const first = {selectedSong: song, autoPlayEnabled: false, multiplayer: false, game: {globalScore: {points: 1200}}}
	PlayerLab.startGhost(first)
	PlayerLab.recordGhost(first, 450, {ms: 1000})
	first.game.globalScore.points = 2000
	PlayerLab.recordGhost(first, 230, {ms: 2000})
	assert.equal(PlayerLab.finishGhost(first), true)
	let saved = JSON.parse(localStorage.getItem(PlayerLab.ghostKey(song)))
	assert.deepEqual(saved.events.map(event => event.j), [2, 1])
	assert.equal(saved.points, 2000)

	const worse = {selectedSong: song, autoPlayEnabled: false, multiplayer: false, game: {globalScore: {points: 500}}}
	PlayerLab.startGhost(worse)
	PlayerLab.recordGhost(worse, 0, {ms: 1000})
	assert.equal(PlayerLab.finishGhost(worse), false)
	saved = JSON.parse(localStorage.getItem(PlayerLab.ghostKey(song)))
	assert.equal(saved.points, 2000)
})

test("ghost difficulty choices are listed independently of the outer cursor", () => {
	assert.deepEqual(PlayerLab.ghostDifficulties({courses: {oni: {stars: 8}, easy: {stars: 2}, ura: {stars: 9}}}), ["easy", "oni", "ura"])
	assert.deepEqual(PlayerLab.ghostDifficulties({courses: {normal: {stars: 4}, hard: {stars: 6}}}), ["normal", "hard"])
})

test("virtual drum defaults off on desktop and persists the player's choice", () => {
	localStorage.data = {}
	assert.equal(PlayerLab.loadState().virtualDrumEnabled, false)
	PlayerLab.saveState({virtualDrumEnabled: true})
	assert.equal(PlayerLab.loadState().virtualDrumEnabled, true)
})

test("virtual drum defaults on for mobile browsers", () => {
	localStorage.data = {}
	const originalNavigator = Object.getOwnPropertyDescriptor(global, "navigator")
	Object.defineProperty(global, "navigator", {configurable: true, value: {userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"}})
	try {
		assert.equal(PlayerLab.loadState().virtualDrumEnabled, true)
	} finally {
		if (originalNavigator) Object.defineProperty(global, "navigator", originalNavigator)
		else delete global.navigator
	}
})

test("daily challenge is deterministic and advances a UTC streak", () => {
	localStorage.data = {}
	const songs = [
		{id: 1, title: "A", courses: {normal: {stars: 3}, hard: {stars: 5}}},
		{id: 2, title: "B", courses: {easy: {stars: 2}, oni: {stars: 8}}}
	]
	const date = new Date("2026-07-15T12:00:00Z")
	const first = PlayerLab.dailyChallenge(songs, date)
	const again = PlayerLab.dailyChallenge(songs, new Date("2026-07-15T23:59:00Z"))
	assert.equal(first.song.id, again.song.id)
	assert.equal(first.difficulty, again.difficulty)
	assert.equal(first.dateKey, "2026-07-15")

	PlayerLab.saveState({dailyRuns: {"2026-07-14": {points: 10}}, ghostEnabled: true})
	const controller = {selectedSong: {dailyChallenge: {dateKey: "2026-07-15"}}, game: {globalScore: {points: 12345}}}
	assert.equal(PlayerLab.completeDaily(controller), 2)
	const state = PlayerLab.loadState()
	assert.equal(state.dailyRuns["2026-07-15"].points, 12345)
	assert.equal(state.dailyStreak, 2)
})

test("recommendation creates a three-step path above the player's level", () => {
	const songs = [
		{id: 1, hash: "a", title: "Easy", courses: {easy: {stars: 2}, normal: {stars: 4}}},
		{id: 2, hash: "b", title: "Next", courses: {hard: {stars: 6}, oni: {stars: 8}}},
		{id: 3, hash: "c", title: "High", courses: {oni: {stars: 9}}}
	]
	const recommendation = PlayerLab.recommendation(songs, {a: {easy: {good: 20, ok: 0, bad: 0}}})
	assert.equal(recommendation.picks.length, 3)
	assert.ok(recommendation.picks.some(pick => pick.song.id === 2))
	assert.ok(recommendation.picks.every(pick => pick.difficulty))
})

test("TJA quality check catches malformed charts without touching upload APIs", () => {
	const good = PlayerLab.analyzeTja(`TITLE: Test
WAVE: song.ogg
OFFSET: 0
COURSE: Oni
#START
1110,
#END`, {name: "song.ogg"})
	assert.equal(good.ok, true)
	assert.equal(good.courses, 1)
	assert.equal(good.notes, 3)
	const bad = PlayerLab.analyzeTja(`TITLE: Missing end
WAVE: song.wav
#START
0000`, {name: "song.wav"})
	assert.equal(bad.ok, false)
	assert.ok(bad.errors.some(message => message.includes("#START/#END")))
	assert.ok(bad.errors.some(message => message.includes("OGG 或 MP3")))
})

test("ghost player replays the saved opponent judgement on the shared game clock", () => {
	localStorage.data = {}
	const song = {hash: "ghost-song", difficulty: "oni"}
	localStorage.setItem(PlayerLab.ghostKey(song), JSON.stringify({events: [{t: 1000, j: 2}]}))
	const calls = []
	const circle = {ms: 1000, type: "don", isPlayed: false}
	const controller = {
		selectedSong: song,
		game: {currentCircle: 0, elapsedTime: 1000, songData: {circles: [circle]}, rules: {bad: 50}, skipNote() {}, updateCurrentCircle() {}},
		mekadon: {playNow(note, score) { calls.push([note, score]) }}
	}
	const ghost = new PlayerLab.GhostPlayer(controller)
	ghost.update()
	assert.deepEqual(calls, [[circle, 450]])
})
