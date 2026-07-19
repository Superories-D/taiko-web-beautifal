const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const {PerformanceAnalytics, FeedbackAnalytics} = require("../public/src/js/feedbackanalytics.js")

test("performance tracker compacts judgements into ordered buckets", () => {
  const tracker = PerformanceAnalytics.createTracker([
    {type: "don", ms: 100},
    {type: "ka", ms: 1200},
    {type: "balloon", ms: 1800}
  ], 4)
  tracker.record(450, {ms: 100}, -4)
  tracker.record(230, {ms: 1200}, 8)
  tracker.record(0, {ms: 1200}, null)
  const controller = {
    selectedSong: {hash: "chart-hash", difficulty: "oni"},
    autoPlayEnabled: false,
    multiplayer: false,
    aiBattle: false,
    ghostBattle: false,
    game: {performanceTracker: tracker}
  }
  const result = PerformanceAnalytics.finish(controller, {
    points: 1000, good: 1, ok: 1, bad: 1, maxCombo: 2, drumroll: 0, gauge: 5000, difficulty: "oni"
  })
  assert.equal(result.buckets.length, 4)
  assert.equal(result.good + result.ok + result.bad, 3)
  assert.equal(result.accuracy, (1 + 0.55) / 3)
  assert.ok(result.worst)
  assert.ok(result.buckets.every((bucket, index) => index === 0 || bucket.start_ms >= result.buckets[index - 1].end_ms))
})

test("eligible runs persist locally even when the controller has circular references", () => {
  const values = new Map()
  global.localStorage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value)
  }
  const tracker = PerformanceAnalytics.createTracker([{type: "don", ms: 100}], 1)
  tracker.record(450, {ms: 100}, -2)
  const controller = {
    selectedSong: {hash: "local-chart", difficulty: "oni"},
    autoPlayEnabled: false, multiplayer: false, aiBattle: false, ghostBattle: false,
    game: {performanceTracker: tracker},
    isLeaderboardEligible: () => true
  }
  controller.game.controller = controller
  const result = FeedbackAnalytics.complete(controller, {
    points: 1234, good: 1, ok: 0, bad: 0, maxCombo: 1, drumroll: 0, gauge: 5000, difficulty: "oni"
  })
  const saved = JSON.parse(values.get("taikoPerformanceRuns.v1"))
  assert.equal(result.eligible, true)
  assert.equal(saved["local-chart:oni"].length, 1)
  assert.equal(saved["local-chart:oni"][0].score, 1234)
  assert.equal("controller" in saved["local-chart:oni"][0], false)
  delete global.localStorage
})

test("local run lookup returns the latest run for a selected chart", () => {
  const values = new Map([["taikoPerformanceRuns.v1", JSON.stringify({
    "chart:oni": [{song_hash: "chart", difficulty: "oni", score: 900}, {song_hash: "chart", difficulty: "oni", score: 800}],
    "chart:hard": [{song_hash: "chart", difficulty: "hard", score: 700}]
  })]])
  global.localStorage = {getItem: key => values.get(key) || null}
  assert.equal(FeedbackAnalytics.loadLocalRuns("chart", "oni")[0].score, 900)
  assert.equal(FeedbackAnalytics.loadLocalRuns("chart", "ura").length, 0)
  delete global.localStorage
})

test("analytics failures cannot interrupt the original score-save lifecycle", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "public", "src", "js", "scoresheet.js"), "utf8")
  let captured = ""
  const context = vm.createContext({
    FeedbackAnalytics: {finishResult() { throw new Error("analytics failed") }},
    errorMessage(value) { captured = value }
  })
  vm.runInContext(source + ";globalThis.Scoresheet = Scoresheet", context)
  const sheet = Object.create(context.Scoresheet.prototype)
  sheet.controller = {saveScore: false, asyncChallenge: null}
  sheet.resultsObj = {}
  sheet.saveScore()
  assert.equal(sheet.analysisAttempted, true)
  assert.equal(sheet.scoreSaved, true)
  assert.match(captured, /analytics failed/)
})
