const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

class EventTargetStub {
	constructor() {
		this.listeners = new Map()
	}

	addEventListener(type, callback) {
		if (!this.listeners.has(type)) this.listeners.set(type, new Set())
		this.listeners.get(type).add(callback)
	}

	removeEventListener(type, callback) {
		if (this.listeners.has(type)) this.listeners.get(type).delete(callback)
	}

	dispatch(type, event) {
		for (const callback of Array.from(this.listeners.get(type) || [])) callback(event)
	}

	listenerCount(type) {
		return this.listeners.has(type) ? this.listeners.get(type).size : 0
	}
}

const root = path.resolve(__dirname, "..")
const source = fs.readFileSync(path.join(root, "public/src/js/pageevents.js"), "utf8")
const window = new EventTargetStub()
const context = vm.createContext({window, Map, Date})
vm.runInContext(source + "; this.PageEvents = PageEvents", context)

const pageEvents = new context.PageEvents()
let keyboardCalls = 0
let firstOverlayCalls = 0
let secondOverlayCalls = 0

pageEvents.keyAdd({}, "all", "both", () => keyboardCalls++)
assert.equal(window.listenerCount("keydown"), 1)

pageEvents.add(window, "keydown", () => firstOverlayCalls++, "library-escape")
assert.equal(window.listenerCount("keydown"), 2, "a named overlay listener must not replace the global keyboard dispatcher")

const keydown = {
	key: "d",
	keyCode: 68,
	type: "keydown",
	target: {tagName: "DIV"},
	ctrlKey: false,
	preventDefault() {}
}
window.dispatch("keydown", keydown)
assert.equal(keyboardCalls, 1)
assert.equal(firstOverlayCalls, 1)

pageEvents.add(window, "keydown", () => secondOverlayCalls++, "library-escape")
assert.equal(window.listenerCount("keydown"), 2, "replacing a named listener must not create duplicates")
window.dispatch("keydown", keydown)
assert.equal(keyboardCalls, 2)
assert.equal(firstOverlayCalls, 1)
assert.equal(secondOverlayCalls, 1)

pageEvents.remove(window, "keydown", "library-escape")
assert.equal(window.listenerCount("keydown"), 1)
window.dispatch("keydown", keydown)
assert.equal(keyboardCalls, 3, "removing an overlay listener must leave keyboard input active")

let keyupCalls = 0
pageEvents.keyAdd({}, "all", "up", () => keyupCalls++)
window.dispatch("keyup", {...keydown, type: "keyup"})
assert.equal(keyupCalls, 1)

console.log("page event listener isolation ok")
