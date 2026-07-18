const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const root = path.resolve(__dirname, "..")
const read = file => fs.readFileSync(path.join(root, file), "utf8")

const songView = read("public/src/views/songselect.html")
const libraryView = read("public/src/views/library.html")
const socialView = read("public/src/views/social.html")
const css = read("public/src/css/library_social.css")
const library = read("public/src/js/library.js")
const social = read("public/src/js/social.js")
const playerLab = read("public/src/js/playerlab.js")
const loader = read("public/src/js/loader.js")

assert.match(songView, /id="song-library-btn"/)
assert.match(songView, /id="song-social-btn"/)
assert.match(songView, /id="library-overlay"/)
assert.match(songView, /id="social-overlay"/)
assert.match(libraryView, /id="library-overlay"/)
assert.match(socialView, /id="social-overlay"/)
assert.match(css, /grid-template-columns: repeat\(6, var\(--song-option-size\)\)/)
assert.match(css, /grid-template-columns: repeat\(3, var\(--song-option-size\)\)/)
assert.match(css, /safe-area-inset-bottom/)
assert.match(library, /localStorage\.setItem\(this\.localKey/)
assert.match(library, /api\/library\/import/)
assert.match(social, /api\/challenges/)
assert.match(social, /submitChallengeResult/)
assert.match(playerLab, /challengeGhostResult/)
assert.match(loader, /api\/csrftoken\?refresh=" \+ Date\.now\(\)/)
assert.match(library, /renderVersion !== this\.renderVersion/)
assert.match(social, /renderVersion !== this\.renderVersion/)
assert.match(social, /data-social-action="accept"/)

// Exercise the local schema migration and touch/click de-duplication without a browser.
const storage = new Map([["taikoLibrary.v1", JSON.stringify({
	version: 0,
	favoriteHashes: ["one", "one", "two"],
	lists: [{name: "Old list", song_hashes: ["one", "one"]}]
})]])
const context = vm.createContext({
	localStorage: {
		getItem: key => storage.get(key) || null,
		setItem: (key, value) => storage.set(key, value)
	},
	pageEvents: {
		add: (target, type, callback) => { target[type] = callback },
		remove: (target, type) => { delete target[type] }
	},
	Date, Math, Set, Array, Object, String, Number
})
vm.runInContext(library, context)
const migrated = vm.runInContext("(() => { let h = Object.create(LibraryHub.prototype); h.localKey = 'taikoLibrary.v1'; h.randomId = () => 'migrated'; return h.loadLocal() })()", context)
assert.deepEqual(Array.from(migrated.favorites), ["one", "two"])
assert.deepEqual(Array.from(migrated.playlists[0].songHashes), ["one"])
context.tapTarget = {}
context.tapCount = 0
vm.runInContext("hubBindTap(tapTarget, () => tapCount++)", context)
context.tapTarget.touchend({cancelable: true, preventDefault() {}})
context.tapTarget.click({})
assert.equal(context.tapCount, 1)
console.log("library/social UI contracts ok")
