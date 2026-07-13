(function (root, factory) {
	var api = factory()
	if (typeof module !== "undefined" && module.exports) {
		module.exports = api
	}
	root.AIBattleCore = api
})(typeof window !== "undefined" ? window : globalThis, function () {
	"use strict"

	var STATES = ["excellent", "great", "normal", "poor", "awful"]
	var WEIGHTS = [0.08, 0.27, 0.45, 0.15, 0.05]
	var PROFILES = {
		excellent: {good: 0.982, ok: 0.016, bad: 0.002, roll: 36, big: 0.995, instability: 0.24},
		great: {good: 0.94, ok: 0.05, bad: 0.01, roll: 46, big: 0.975, instability: 0.48},
		normal: {good: 0.84, ok: 0.12, bad: 0.04, roll: 60, big: 0.90, instability: 0.76},
		poor: {good: 0.67, ok: 0.23, bad: 0.10, roll: 78, big: 0.76, instability: 1},
		awful: {good: 0.47, ok: 0.32, bad: 0.21, roll: 100, big: 0.58, instability: 1.12}
	}

	function hashSeed(value) {
		var text = String(value == null ? "" : value)
		var hash = 2166136261
		for (var i = 0; i < text.length; i++) {
			hash ^= text.charCodeAt(i)
			hash = Math.imul(hash, 16777619)
		}
		return hash >>> 0
	}

	function createRng(seed) {
		var state = typeof seed === "number" ? seed >>> 0 : hashSeed(seed)
		return function () {
			state += 0x6D2B79F5
			var value = state
			value = Math.imul(value ^ value >>> 15, value | 1)
			value ^= value + Math.imul(value ^ value >>> 7, value | 61)
			return ((value ^ value >>> 14) >>> 0) / 4294967296
		}
	}

	function normalRandom(rng) {
		var u = Math.max(1e-9, rng())
		var v = Math.max(1e-9, rng())
		return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
	}

	function chooseState(rng) {
		var value = rng()
		var total = 0
		for (var i = 0; i < STATES.length; i++) {
			total += WEIGHTS[i]
			if (value < total) {
				return STATES[i]
			}
		}
		return "normal"
	}

	function resolveState(requested, rng) {
		return STATES.indexOf(requested) === -1 ? chooseState(rng) : requested
	}

	function splitCounts(total, parts) {
		total = Math.max(0, Math.floor(Number(total) || 0))
		parts = Math.max(1, Math.floor(Number(parts) || 1))
		var base = Math.floor(total / parts)
		var remainder = total % parts
		var output = []
		for (var i = 0; i < parts; i++) {
			output.push(base + (i < remainder ? 1 : 0))
		}
		return output
	}

	function thresholdForDifficulty(difficulty) {
		if (difficulty === "oni" || difficulty === "ura") {
			return 50
		}
		if (difficulty === "hard") {
			return 30
		}
		return 10
	}

	function resolveRound(playerScore, aiScore, threshold) {
		var difference = playerScore - aiScore
		if (Math.abs(difference) < threshold) {
			return "draw"
		}
		return difference > 0 ? "player" : "ai"
	}

	function resolveMatch(results) {
		var player = 0
		var ai = 0
		;(results || []).forEach(function (result) {
			if (result === "player") player++
			if (result === "ai") ai++
		})
		return player === ai ? "draw" : (player > ai ? "player" : "ai")
	}

	function hasModeConflict(aiEnabled, autoPlayEnabled, multiplayer) {
		return !!aiEnabled && (!!autoPlayEnabled || !!multiplayer)
	}

	function isBattleNote(circle) {
		return !!circle && ["don", "ka", "daiDon", "daiKa"].indexOf(circle.type) !== -1 && (!circle.branch || circle.branch.active)
	}

	function stateLabel(state) {
		var labels = {
			excellent: "极佳",
			great: "佳",
			normal: "普通",
			poor: "差",
			awful: "极差"
		}
		if (typeof strings !== "undefined" && strings.aiBattle && strings.aiBattle[state]) {
			return strings.aiBattle[state]
		}
		return labels[state] || state
	}

	function text(key, fallback) {
		return typeof strings !== "undefined" && strings.aiBattle && strings.aiBattle[key] || fallback
	}

	function AIBattlePlayer(controller, requestedState, seed) {
		this.controller = controller
		this.rng = createRng(seed == null ? Date.now() + ":" + Math.random() : seed)
		this.state = resolveState(requestedState, this.rng)
		this.profile = PROFILES[this.state]
		this.form = normalRandom(this.rng) * 0.25
		this.timingDrift = normalRandom(this.rng) * 4
		this.lastCircle = null
		this.lastNoteMs = -Infinity
		this.decision = null
		this.errorStreak = 0
	}

	AIBattlePlayer.prototype.decide = function (circle) {
		var rng = this.rng
		var gap = isFinite(this.lastNoteMs) ? circle.ms - this.lastNoteMs : 1000
		var densityPenalty = gap < 100 ? 0.075 : (gap < 160 ? 0.035 : 0)
		this.form = this.form * 0.94 + normalRandom(rng) * 0.06
		var streakPenalty = this.errorStreak >= 2 ? Math.min(0.07, this.errorStreak * 0.012) : 0
		var instability = this.profile.instability
		var appliedDensity = densityPenalty * instability
		var appliedStreak = streakPenalty * instability
		var good = Math.max(0.08, Math.min(0.9995, this.profile.good + this.form * 0.08 * instability - appliedDensity - appliedStreak))
		var ok = Math.max(0.0004, Math.min(0.65, this.profile.ok + appliedDensity * 0.65 + appliedStreak * 0.45))
		if (good + ok > 0.9995) ok = Math.max(0.0001, 0.9995 - good)
		var value = rng()
		var score = value < good ? 450 : (value < good + ok ? 230 : 0)
		if (score === 0) this.errorStreak++
		else this.errorStreak = Math.max(0, this.errorStreak - 1)
		this.timingDrift = this.timingDrift * 0.88 + normalRandom(rng) * 7
		var rules = this.controller.game.rules
		var offset
		if (score === 450) {
			offset = this.timingDrift + normalRandom(rng) * rules.good * 0.24
			offset = Math.max(-rules.good * 0.82, Math.min(rules.good * 0.82, offset))
		} else if (score === 230) {
			var sign = rng() < 0.5 ? -1 : 1
			offset = sign * (rules.good * 1.08 + rng() * Math.max(1, rules.ok - rules.good * 1.15))
		} else {
			offset = (rng() < 0.28 ? -1 : 1) * (rules.ok * 1.03 + rng() * Math.max(1, rules.bad - rules.ok * 1.08))
		}
		var miss = score === 0 && rng() < 0.34
		var reverse = score === 0 && !miss && rng() < 0.42
		var big = circle.type === "daiDon" || circle.type === "daiKa"
		var dai = big && rng() < this.profile.big ? 2 : (big ? 1 : 0)
		this.lastNoteMs = circle.ms
		return {score: score, offset: offset, miss: miss, reverse: reverse, dai: dai}
	}

	AIBattlePlayer.prototype.update = function () {
		var game = this.controller.game
		var circles = game.songData.circles
		var circle = circles[game.currentCircle]
		if (!circle || circle.isPlayed || circle.branch && !circle.branch.active) return
		if (circle !== this.lastCircle) {
			this.lastCircle = circle
			this.decision = isBattleNote(circle) ? this.decide(circle) : null
		}
		var type = circle.type
		if (type === "balloon" || type === "drumroll" || type === "daiDrumroll") {
			var pace = this.profile.roll * (0.82 + this.rng() * 0.4)
			this.controller.mekadon.playDrumrollAt(circle, 0, pace, type === "balloon" ? 0 : 0.35)
			return
		}
		if (!this.decision || this.decision.miss) return
		if (game.elapsedTime >= circle.ms + this.controller.audioLatency + this.decision.offset) {
			this.controller.mekadon.playNow(circle, this.decision.score, this.decision.dai, this.decision.reverse)
		}
	}

	AIBattlePlayer.prototype.clean = function () {
		this.controller = null
		this.lastCircle = null
		this.decision = null
	}

	function AIBattleCoordinator(primary, secondary, options) {
		this.primary = primary
		this.secondary = secondary
		this.options = options || {}
		this.threshold = thresholdForDifficulty(primary.selectedSong.difficulty)
		this.scores = Array.from({length: 5}, function () { return [0, 0] })
		this.results = []
		this.currentSegment = 0
		this.closed = false
		this.buildBoundaries()
		this.createHud()
	}

	AIBattleCoordinator.prototype.activeNotes = function (afterMs) {
		return this.primary.game.songData.circles.filter(function (circle) {
			return isBattleNote(circle) && (afterMs == null || circle.ms > afterMs)
		})
	}

	AIBattleCoordinator.prototype.buildBoundaries = function () {
		var notes = this.activeNotes()
		var counts = splitCounts(notes.length, 5)
		this.boundaries = []
		var cursor = 0
		var last = null
		for (var i = 0; i < counts.length; i++) {
			cursor += counts[i]
			if (cursor > 0 && notes[cursor - 1]) last = notes[cursor - 1].ms
			this.boundaries.push(last)
		}
	}

	AIBattleCoordinator.prototype.segmentFor = function (circle) {
		var ms = circle && Number(circle.ms)
		if (!isFinite(ms)) return Math.min(4, this.currentSegment)
		for (var i = 0; i < this.boundaries.length; i++) {
			if (this.boundaries[i] != null && ms <= this.boundaries[i]) return i
		}
		return 4
	}

	AIBattleCoordinator.prototype.record = function (player, score, circle) {
		if (this.closed || !isBattleNote(circle)) return
		var segment = this.segmentFor(circle)
		var points = score === 450 ? 3 : (score === 230 ? 2 : 0)
		this.scores[segment][player === 2 ? 1 : 0] += points
		if (segment === this.currentSegment) this.renderAdvantage()
	}

	AIBattleCoordinator.prototype.update = function (ms) {
		if (this.closed) return
		while (this.currentSegment < 5) {
			var boundary = this.boundaries[this.currentSegment]
			if (boundary == null || ms < boundary + this.primary.game.rules.bad + 35) break
			this.settleCurrent()
		}
	}

	AIBattleCoordinator.prototype.settleCurrent = function () {
		if (this.currentSegment >= 5) return
		var score = this.scores[this.currentSegment]
		var result = resolveRound(score[0], score[1], this.threshold)
		this.results.push(result)
		this.showRoundResult(this.currentSegment, result)
		this.currentSegment++
		this.renderAdvantage()
		if (this.currentSegment === 5) this.showMatchResult()
	}

	AIBattleCoordinator.prototype.finish = function () {
		while (this.currentSegment < 5) this.settleCurrent()
	}

	AIBattleCoordinator.prototype.onBranchChange = function (branchMs, activeName) {
		if (this.closed) return
		var keepThrough = this.currentSegment
		var anchor = this.boundaries[keepThrough]
		if (anchor == null || keepThrough >= 4) return
		var notes = this.activeNotes(anchor)
		var counts = splitCounts(notes.length, 4 - keepThrough)
		var cursor = 0
		var last = anchor
		for (var i = keepThrough + 1; i < 5; i++) {
			cursor += counts[i - keepThrough - 1]
			if (cursor > 0 && notes[cursor - 1]) last = notes[cursor - 1].ms
			this.boundaries[i] = last
		}
	}

	AIBattleCoordinator.prototype.createHud = function () {
		var game = document.getElementById("game")
		if (!game) return
		var hud = document.createElement("div")
		hud.id = "ai-battle-hud"
		hud.innerHTML =
			'<div class="ai-battle-form"></div>' +
			'<div class="ai-battle-bar" aria-label="AI battle advantage"><div class="ai-battle-player"></div><div class="ai-battle-ai"></div><i></i></div>' +
			'<div class="ai-battle-rounds">' + Array.from({length: 5}, function (_, i) { return '<span data-round="' + i + '">' + (i + 1) + '</span>' }).join("") + '</div>' +
			'<div class="ai-battle-result" aria-live="polite"></div>'
		game.appendChild(hud)
		game.classList.add("ai-battle-active")
		this.hud = hud
		var form = hud.querySelector(".ai-battle-form")
		form.textContent = text("form", "AI 状态") + " · " + stateLabel(this.secondary.aiPlayer.state)
		setTimeout(function () { form.classList.add("quiet") }, 3200)
		this.renderAdvantage()
	}

	AIBattleCoordinator.prototype.renderAdvantage = function () {
		if (!this.hud) return
		var score = this.scores[Math.min(4, this.currentSegment)] || [0, 0]
		var ratio = Math.max(-1, Math.min(1, (score[0] - score[1]) / this.threshold))
		var player = Math.max(0, ratio) * 50
		var ai = Math.max(0, -ratio) * 50
		this.hud.querySelector(".ai-battle-player").style.width = player + "%"
		this.hud.querySelector(".ai-battle-ai").style.width = ai + "%"
		var game = document.getElementById("game")
		game.classList.toggle("ai-battle-player-leading", ratio > 0.03)
		game.classList.toggle("ai-battle-ai-leading", ratio < -0.03)
	}

	AIBattleCoordinator.prototype.showRoundResult = function (round, result) {
		if (!this.hud) return
		var marker = this.hud.querySelector('[data-round="' + round + '"]')
		marker.classList.add(result)
		marker.textContent = result === "player" ? "胜" : (result === "ai" ? "负" : "平")
		var resultBox = this.hud.querySelector(".ai-battle-result")
		resultBox.className = "ai-battle-result show " + result
		resultBox.textContent = text("round", "第 {round} 段").replace("{round}", round + 1) + " · " +
			(result === "player" ? text("playerWins", "玩家胜") : (result === "ai" ? text("aiWins", "AI 胜") : text("draw", "平局")))
		clearTimeout(this.resultTimer)
		this.resultTimer = setTimeout(function () { resultBox.classList.remove("show") }, 1200)
	}

	AIBattleCoordinator.prototype.showMatchResult = function () {
		if (!this.hud) return
		var result = resolveMatch(this.results)
		var resultBox = this.hud.querySelector(".ai-battle-result")
		resultBox.className = "ai-battle-result show match " + result
		resultBox.textContent = result === "player" ? text("matchPlayer", "五局战罢 · 玩家胜") :
			(result === "ai" ? text("matchAi", "五局战罢 · AI 胜") : text("matchDraw", "五局战罢 · 平局"))
		clearTimeout(this.resultTimer)
		this.resultTimer = setTimeout(function () { resultBox.classList.remove("show") }, 2400)
	}

	AIBattleCoordinator.prototype.clean = function () {
		this.closed = true
		clearTimeout(this.resultTimer)
		var game = document.getElementById("game")
		if (game) game.classList.remove("ai-battle-active", "ai-battle-player-leading", "ai-battle-ai-leading")
		if (this.hud && this.hud.parentNode) this.hud.parentNode.removeChild(this.hud)
		this.hud = null
	}

	return {
		STATES: STATES.slice(),
		WEIGHTS: WEIGHTS.slice(),
		PROFILES: PROFILES,
		hashSeed: hashSeed,
		createRng: createRng,
		chooseState: chooseState,
		resolveState: resolveState,
		splitCounts: splitCounts,
		thresholdForDifficulty: thresholdForDifficulty,
		resolveRound: resolveRound,
		resolveMatch: resolveMatch,
		hasModeConflict: hasModeConflict,
		isBattleNote: isBattleNote,
		AIBattlePlayer: AIBattlePlayer,
		AIBattleCoordinator: AIBattleCoordinator
	}
})
