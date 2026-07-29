class FakeClassList {
	constructor(element) {
		this.element = element
	}

	add(...names) {
		for (const name of names) {
			if (name) this.element.classes.add(String(name))
		}
	}

	contains(name) {
		return this.element.classes.has(String(name))
	}

	toggle(name, force) {
		const normalized = String(name)
		const enabled = typeof force === "boolean" ? force : !this.contains(normalized)
		if (enabled) this.element.classes.add(normalized)
		else this.element.classes.delete(normalized)
		return enabled
	}
}

class FakeElement {
	constructor(tagName) {
		this.tagName = String(tagName || "").toUpperCase()
		this.children = []
		this.parentNode = null
		this.attributes = new Map()
		this.classes = new Set()
		this.classList = new FakeClassList(this)
		this.listeners = new Map()
		this._textContent = ""
		this.id = ""
		this.disabled = false
		this.type = ""
	}

	get className() {
		return Array.from(this.classes).join(" ")
	}

	set className(value) {
		this.classes = new Set(String(value || "").split(/\s+/).filter(Boolean))
	}

	get firstChild() {
		return this.children[0] || null
	}

	get textContent() {
		if (this.children.length) {
			return this.children.map(child => child.textContent).join("")
		}
		return this._textContent
	}

	set textContent(value) {
		this.children = []
		this._textContent = String(value ?? "")
	}

	appendChild(child) {
		child.parentNode = this
		this.children.push(child)
		return child
	}

	removeChild(child) {
		const index = this.children.indexOf(child)
		if (index !== -1) {
			this.children.splice(index, 1)
			child.parentNode = null
		}
		return child
	}

	remove() {
		if (this.parentNode) this.parentNode.removeChild(this)
	}

	setAttribute(name, value) {
		const normalized = String(name)
		const text = String(value)
		this.attributes.set(normalized, text)
		if (normalized === "id") this.id = text
		if (normalized === "class") this.className = text
	}

	getAttribute(name) {
		return this.attributes.get(String(name)) ?? null
	}

	addEventListener(name, handler) {
		const normalized = String(name)
		const handlers = this.listeners.get(normalized) || []
		handlers.push(handler)
		this.listeners.set(normalized, handlers)
	}

	matches(selector) {
		if (selector.startsWith(".")) {
			return this.classList.contains(selector.slice(1))
		}
		const dataAttribute = selector.match(/^\[([a-zA-Z0-9_-]+)\]$/)
		if (dataAttribute) {
			return this.attributes.has(dataAttribute[1])
		}
		if (selector.startsWith("#")) {
			return this.id === selector.slice(1)
		}
		return this.tagName.toLowerCase() === selector.toLowerCase()
	}

	querySelector(selector) {
		for (const child of this.children) {
			if (child.matches(selector)) return child
			const nested = child.querySelector(selector)
			if (nested) return nested
		}
		return null
	}

	querySelectorAll(selector) {
		const results = []
		for (const child of this.children) {
			if (child.matches(selector)) results.push(child)
			results.push(...child.querySelectorAll(selector))
		}
		return results
	}
}

function createFakeDocument() {
	const document = {
		body: new FakeElement("body"),
		head: new FakeElement("head"),
		listeners: new Map(),
		createElement(tagName) {
			return new FakeElement(tagName)
		},
		getElementById(id) {
			return this.body.querySelector("#" + id) || this.head.querySelector("#" + id)
		},
		addEventListener(name, handler) {
			this.listeners.set(String(name), handler)
		},
		removeEventListener(name) {
			this.listeners.delete(String(name))
		}
	}
	return document
}

function findElements(root, tagNames) {
	const targets = new Set(tagNames.map(name => String(name).toUpperCase()))
	const results = []
	for (const child of root.children || []) {
		if (targets.has(child.tagName)) results.push(child)
		results.push(...findElements(child, tagNames))
	}
	return results
}

module.exports = {FakeElement, createFakeDocument, findElements}
