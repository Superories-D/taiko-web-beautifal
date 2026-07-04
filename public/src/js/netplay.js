class NetplayBeta {
	constructor(...args) {
		this.init(...args)
	}

	static isInviteHash(hash) {
		var value = String(hash || "").toLowerCase()
		return value.startsWith("#netplay=") || value.startsWith("#np=")
	}

	static encodeBase64Url(text) {
		return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "")
	}

	static decodeBase64Url(text) {
		var input = String(text || "").replace(/-/g, "+").replace(/_/g, "/")
		while (input.length % 4) {
			input += "="
		}
		return atob(input)
	}

	static inviteHash(serverId, inviteId) {
		var payload = NetplayBeta.encodeBase64Url(JSON.stringify({
			s: serverId,
			i: inviteId
		}))
		return "#netplay=" + payload
	}

	static parseInviteHash(hash) {
		if (!NetplayBeta.isInviteHash(hash)) {
			return null
		}
		var raw = String(hash || "").split("=", 2)[1] || ""
		try {
			var data = JSON.parse(NetplayBeta.decodeBase64Url(decodeURIComponent(raw)))
			if (data && data.s && data.i) {
				return {
					server_id: String(data.s),
					invite_id: String(data.i)
				}
			}
		} catch (error) {}
		return null
	}

	init(songSelect) {
		this.songSelect = songSelect
		this.button = document.getElementById("song-netplay-btn")
		this.overlay = null
		this.servers = []
		this.hasServers = false
		this.loading = false
		this.loadError = false
		this.socket = null
		this.socketOpen = false
		this.selectedServer = null
		this.inviteLink = ""
		this.inviteExpiresAt = ""
		this.pendingInvite = NetplayBeta.parseInviteHash(location.hash)
		this.pendingInviteHandled = false
		this.role = ""
		this.statusText = ""
		this.logRows = []
		this.pingTimer = null
		this.beforeUnloadHandler = this.beforeUnload.bind(this)
		this.setActive(false)

		if (!this.button) {
			return
		}
		this.setButtonLabel()
		pageEvents.add(this.button, ["click", "touchend"], this.open.bind(this))
		window.addEventListener("beforeunload", this.beforeUnloadHandler)
		this.loadServers()
	}

	text(name, fallback) {
		var source = strings.netplayBeta || {}
		return source[name] || fallback || name
	}

	setButtonLabel() {
		var label = this.text("title", "Netplay Beta")
		this.button.setAttribute("aria-label", label)
		this.button.title = label
		var span = this.button.querySelector("span")
		if (span) {
			span.textContent = this.text("buttonShort", "Net")
		}
	}

	loadServers() {
		if (this.loading) {
			return
		}
		this.loading = true
		this.loadError = false
		loader.ajax("api/netplay/servers").then(response => {
			var data = JSON.parse(response)
			var servers = data && data.enabled && Array.isArray(data.servers) ? data.servers : []
			this.servers = servers.filter(server => server && server.endpoint)
			this.hasServers = this.servers.length > 0
			this.loading = false
			this.loadError = false
			this.songSelect.updateSearchButtonVisibility()
			this.handlePendingInvite()
			this.render()
		}).catch(error => {
			this.servers = []
			this.hasServers = false
			this.loading = false
			this.loadError = true
			if (console && console.debug) {
				console.debug("No netplay servers available", error)
			}
			this.handlePendingInvite()
			this.songSelect.updateSearchButtonVisibility()
			this.render()
		})
	}

	handlePendingInvite() {
		if (!this.pendingInvite || this.pendingInviteHandled) {
			return
		}
		this.pendingInviteHandled = true
		this.ensureOverlay()
		this.heading.textContent = this.text("title", "Netplay Beta")
		this.overlay.hidden = false
		cancelTouch = false
		noResizeRoot = true
		var server = this.servers.find(item => item.server_id === this.pendingInvite.server_id)
		if (!server) {
			this.statusText = this.text("inviteExpired", "This invite is no longer available.")
			this.pendingInvite = null
			this.render()
			return
		}
		this.connect(server, "guest", this.pendingInvite.invite_id)
		this.pendingInvite = null
	}

	ensureOverlay() {
		if (this.overlay) {
			return
		}
		this.overlay = document.createElement("div")
		this.overlay.id = "netplay-overlay"
		this.overlay.hidden = true
		this.overlay.innerHTML = [
			'<div id="netplay-panel" role="dialog" aria-modal="true">',
			'<div class="netplay-header">',
			'<h2 id="netplay-heading"></h2>',
			'<button id="netplay-close" type="button" aria-label="Close" title="Close">x</button>',
			'</div>',
			'<div id="netplay-body"></div>',
			'</div>'
		].join("")
		loader.screen.appendChild(this.overlay)
		this.heading = this.overlay.querySelector("#netplay-heading")
		this.body = this.overlay.querySelector("#netplay-body")
		this.closeButton = this.overlay.querySelector("#netplay-close")
		pageEvents.add(this.closeButton, ["click", "touchend"], this.close.bind(this))
		pageEvents.add(this.overlay, ["click", "touchend"], event => {
			event.stopPropagation()
			if (event.target === this.overlay) {
				this.close(event)
			}
		})
		pageEvents.add(this.body, ["click", "touchend"], this.onBodyClick.bind(this))
	}

	open(event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		if (!this.hasServers && !this.pendingInvite) {
			return
		}
		this.ensureOverlay()
		this.heading.textContent = this.text("title", "Netplay Beta")
		this.overlay.hidden = false
		cancelTouch = false
		noResizeRoot = true
		this.songSelect.playSound("se_pause")
		this.render()
		this.songSelect.updateSearchButtonVisibility()
	}

	close(event) {
		if (event) {
			event.preventDefault()
			event.stopPropagation()
		}
		this.leaveSession()
		if (this.overlay) {
			this.overlay.hidden = true
		}
		cancelTouch = true
		noResizeRoot = false
		this.songSelect.updateSearchButtonVisibility()
	}

	isOpen() {
		return this.overlay && !this.overlay.hidden
	}

	keyPress(pressed, name) {
		if (!pressed) {
			return
		}
		if (name === "back") {
			this.close()
		}
	}

	onBodyClick(event) {
		var target = event.target
		var actionButton = target && target.closest ? target.closest("[data-netplay-action]") : null
		if (!actionButton) {
			return
		}
		event.preventDefault()
		event.stopPropagation()
		var action = actionButton.dataset.netplayAction
		if (action === "host") {
			var server = this.servers.find(item => item.server_id === actionButton.dataset.serverId)
			if (server) {
				this.connect(server, "host")
			}
		} else if (action === "ready") {
			this.sendJson({type: "ready"})
		} else if (action === "start") {
			this.sendJson({type: "start"})
		} else if (action === "leave") {
			this.close(event)
		} else if (action === "copy") {
			this.copyInvite()
		} else if (action === "refresh") {
			this.loadServers()
		}
	}

	connect(server, role, inviteId) {
		this.disconnect(false)
		this.selectedServer = server
		this.role = role
		this.inviteLink = ""
		this.inviteExpiresAt = ""
		this.socketOpen = false
		this.logRows = []
		this.statusText = this.text("connecting", "Connecting...") + " " + (server.name || server.server_id)
		this.render()
		try {
			this.socket = new WebSocket(server.endpoint)
		} catch (error) {
			this.statusText = this.text("connectionFailed", "Connection failed")
			this.render()
			return
		}
		var opened = false
		this.socket.addEventListener("open", () => {
			opened = true
			this.socketOpen = true
			this.setActive(true)
			this.statusText = role === "guest" ? this.text("joiningInvite", "Joining invite...") : this.text("creatingInvite", "Creating invite...")
			this.sendJson(role === "guest" ? {
				type: "join_invite",
				invite_id: inviteId,
				player_name: this.playerName()
			} : {
				type: "create_invite",
				player_name: this.playerName()
			}, false)
			this.pingTimer = setInterval(() => this.sendJson({type: "ping"}, false), 25000)
			this.render()
		})
		this.socket.addEventListener("message", event => this.onSocketMessage(event))
		this.socket.addEventListener("close", () => {
			this.socketOpen = false
			this.setActive(false)
			this.clearPingTimer()
			if (!this.statusText || !opened) {
				this.statusText = opened ? this.text("disconnected", "Disconnected") : this.text("connectionFailed", "Connection failed")
			}
			this.render()
		})
		this.socket.addEventListener("error", () => {
			this.statusText = this.text("connectionFailed", "Connection failed")
			this.render()
		})
	}

	onSocketMessage(event) {
		var message = null
		try {
			message = JSON.parse(event.data)
		} catch (error) {
			return
		}
		switch (message.type) {
			case "invite_created":
				this.onInviteCreated(message)
				break
			case "invite_joined":
			case "player_joined":
				this.statusText = this.text("connected", "Connected")
				this.addLog(this.text("peerJoined", "Peer joined"))
				break
			case "room_closed":
			case "player_left":
				this.statusText = this.text("inviteClosed", "Invite closed")
				this.addLog(this.text("inviteClosed", "Invite closed"))
				this.clearInviteHash()
				this.disconnect(true)
				break
			case "error":
				this.statusText = message.message || this.text("connectionFailed", "Connection failed")
				this.addLog(this.statusText)
				this.clearInviteHash()
				this.disconnect(true)
				break
			case "pong":
				break
			default:
				this.addLog(message.type || "message")
		}
		this.render()
	}

	onInviteCreated(message) {
		var inviteId = String(message.invite_id || "")
		if (!inviteId || !this.selectedServer) {
			return
		}
		var hash = NetplayBeta.inviteHash(this.selectedServer.server_id, inviteId)
		this.inviteLink = location.origin + location.pathname + hash
		this.inviteExpiresAt = message.expires_at || ""
		this.statusText = this.text("inviteReady", "Invite link ready")
		this.addLog(this.text("inviteReady", "Invite link ready"))
	}

	playerName() {
		return account && account.displayName || strings.defaultName || "Player"
	}

	sendJson(message, log) {
		if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
			return
		}
		this.socket.send(JSON.stringify(message))
		if (log !== false) {
			this.addLog(message.type)
			this.render()
		}
	}

	leaveSession() {
		if (this.socket && this.socket.readyState === WebSocket.OPEN) {
			this.sendJson({type: "leave"}, false)
		}
		this.disconnect(true)
		this.clearInviteHash()
	}

	disconnect(reset) {
		this.clearPingTimer()
		if (this.socket) {
			try {
				this.socket.close()
			} catch (error) {}
		}
		this.socket = null
		this.socketOpen = false
		this.setActive(false)
		if (reset) {
			this.selectedServer = null
			this.role = ""
			this.inviteLink = ""
			this.inviteExpiresAt = ""
			this.statusText = ""
		}
	}

	clearPingTimer() {
		if (this.pingTimer) {
			clearInterval(this.pingTimer)
			this.pingTimer = null
		}
	}

	beforeUnload() {
		if (this.socket && this.socket.readyState === WebSocket.OPEN) {
			try {
				this.socket.send(JSON.stringify({type: "leave"}))
			} catch (error) {}
		}
	}

	clearInviteHash() {
		if (NetplayBeta.isInviteHash(location.hash)) {
			history.replaceState("", "", location.pathname + location.search)
		}
	}

	setActive(active) {
		window.netplayActive = !!active
	}

	copyInvite() {
		if (!this.inviteLink || !navigator.clipboard) {
			return
		}
		navigator.clipboard.writeText(this.inviteLink).then(() => {
			this.addLog(this.text("copied", "Copied"))
			this.render()
		}).catch(() => {})
	}

	addLog(text) {
		this.logRows.unshift(String(text || "message"))
		this.logRows = this.logRows.slice(0, 6)
	}

	render() {
		if (!this.overlay || this.overlay.hidden) {
			return
		}
		this.body.textContent = ""
		if (this.loading) {
			this.body.appendChild(this.stateElement(this.text("loading", "Loading...")))
			return
		}
		if (!this.hasServers && !this.pendingInvite) {
			var empty = this.stateElement(this.text("noneAvailable", "No netplay servers available"))
			this.body.appendChild(empty)
			this.body.appendChild(this.actionButton("refresh", this.text("refresh", "Refresh")))
			return
		}
		if (this.statusText) {
			this.body.appendChild(this.stateElement(this.statusText, "netplay-state netplay-status"))
		}
		if (this.inviteLink) {
			this.body.appendChild(this.inviteElement())
		}
		if (!this.socketOpen && !this.pendingInvite) {
			this.body.appendChild(this.serverListElement())
		}
		if (this.socketOpen) {
			this.body.appendChild(this.sessionControlsElement())
		}
		if (this.logRows.length) {
			this.body.appendChild(this.logElement())
		}
	}

	serverListElement() {
		var serverList = document.createElement("div")
		serverList.className = "netplay-server-list"
		this.servers.forEach(server => {
			var card = document.createElement("article")
			card.className = "netplay-server"
			var info = document.createElement("div")
			var title = document.createElement("h3")
			title.textContent = server.name || server.server_id
			info.appendChild(title)
			var usage = document.createElement("p")
			usage.textContent = [
				server.region || "--",
				" · ",
				server.current_players || 0,
				" / ",
				server.max_players || 0,
				" ",
				this.text("players", "players"),
				" · ",
				server.current_rooms || 0,
				" / ",
				server.max_rooms || 0,
				" ",
				this.text("rooms", "rooms")
			].join("")
			info.appendChild(usage)
			var badge = document.createElement("span")
			badge.className = "netplay-official"
			badge.textContent = this.text("officialServer", "Official Server")
			info.appendChild(badge)
			card.appendChild(info)
			var button = document.createElement("button")
			button.type = "button"
			button.dataset.netplayAction = "host"
			button.dataset.serverId = server.server_id
			button.textContent = this.text("createInvite", "Create invite")
			card.appendChild(button)
			serverList.appendChild(card)
		})
		return serverList
	}

	inviteElement() {
		var wrapper = document.createElement("div")
		wrapper.className = "netplay-invite"
		var label = document.createElement("strong")
		label.textContent = this.text("inviteLink", "Invite link")
		wrapper.appendChild(label)
		var input = document.createElement("input")
		input.type = "text"
		input.readOnly = true
		input.value = this.inviteLink
		input.addEventListener("focus", () => input.select())
		wrapper.appendChild(input)
		var copy = this.actionButton("copy", this.text("copy", "Copy"))
		wrapper.appendChild(copy)
		var note = document.createElement("small")
		note.textContent = this.inviteExpiresAt ? this.text("expiresInFive", "Expires if unopened after 5 minutes") : ""
		wrapper.appendChild(note)
		return wrapper
	}

	sessionControlsElement() {
		var controls = document.createElement("div")
		controls.className = "netplay-controls"
		var actionRow = document.createElement("div")
		actionRow.className = "netplay-action-row"
		;[
			["ready", this.text("ready", "Ready")],
			["start", this.text("start", "Start")],
			["leave", this.text("leave", "Leave")]
		].forEach(item => {
			actionRow.appendChild(this.actionButton(item[0], item[1]))
		})
		controls.appendChild(actionRow)
		return controls
	}

	actionButton(action, text) {
		var button = document.createElement("button")
		button.type = "button"
		button.dataset.netplayAction = action
		button.textContent = text
		return button
	}

	logElement() {
		var log = document.createElement("div")
		log.className = "netplay-log"
		this.logRows.forEach(row => {
			var item = document.createElement("span")
			item.textContent = row
			log.appendChild(item)
		})
		return log
	}

	stateElement(text, className) {
		var div = document.createElement("div")
		div.className = className || "netplay-state"
		div.textContent = text
		return div
	}

	clean() {
		this.leaveSession()
		window.removeEventListener("beforeunload", this.beforeUnloadHandler)
		if (this.button) {
			pageEvents.remove(this.button, ["click", "touchend"])
		}
		if (this.overlay) {
			this.overlay.remove()
		}
		delete this.button
		delete this.overlay
	}
}
