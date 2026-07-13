class P2Connection{
	constructor(...args){
		this.init(...args)
	}
	init(){
		this.closed = true
		this.connecting = false
		this.socket = null
		this.pendingMessages = []
		this.remoteSequence = 0
		this.networkRtt = 200
		this.networkJitter = 50
		this.pingTimer = null
		this.connectionAttempt = 0
		this.serverId = null
		this.requestedNodeId = null
		this.requireSingleServer = false
		this.lastMessages = {}
		this.otherConnected = false
		this.name = null
		this.player = 1
		this.allEvents = new Map()
		this.addEventListener("message", this.message.bind(this))
		this.currentHash = ""
		this.disabled = 0
		pageEvents.add(window, "hashchange", this.onhashchange.bind(this))
	}
	setRequestedNode(nodeId){
		this.requestedNodeId = /^[a-f0-9]{12}$/i.test(nodeId || "") ? nodeId.toLowerCase() : null
		this.requireSingleServer = false
	}
	setLegacyInvite(){
		this.requestedNodeId = null
		this.requireSingleServer = true
	}
	getClientId(){
		var key = "multiplayer-client-id"
		var clientId = localStorage.getItem(key)
		if(!clientId){
			if(window.crypto && window.crypto.randomUUID){
				clientId = window.crypto.randomUUID()
			}else{
				clientId = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2)
			}
			localStorage.setItem(key, clientId)
		}
		return clientId
	}
	selectorUrl(){
		var basedir = gameConfig.basedir || "/"
		if(!basedir.endsWith("/")){
			basedir += "/"
		}
		return basedir + "api/multiplayer/select"
	}
	resolveServer(){
		var params = new URLSearchParams({client_id: this.getClientId()})
		if(this.requestedNodeId){
			params.set("node_id", this.requestedNodeId)
		}else if(this.requireSingleServer){
			params.set("legacy_invite", "1")
		}
		return fetch(this.selectorUrl() + "?" + params.toString(), {
			credentials: "same-origin",
			cache: "no-store"
		}).then(response => {
			return response.json().catch(() => ({})).then(data => {
				if(!response.ok || !data || data.status !== "ok" || !data.server || !data.server.id || !data.server.ws_url){
					throw new Error((data && data.message) || "multiplayer_unavailable")
				}
				return data.server
			})
		})
	}
	showUnavailableNotice(reason){
		var message = reason === "multiplayer_node_unavailable" ? strings.multiplayerRoomUnavailable :
			reason === "multiplayer_full" ? strings.multiplayerFull : strings.multiplayerUnavailable
		var notice = document.getElementById("multiplayer-unavailable-notice")
		if(!notice){
			notice = document.createElement("div")
			notice.id = "multiplayer-unavailable-notice"
			notice.setAttribute("role", "alert")
			notice.addEventListener("click", () => notice.classList.remove("visible"))
			document.body.appendChild(notice)
		}
		notice.textContent = message
		notice.classList.add("visible")
		clearTimeout(this.unavailableTimer)
		this.unavailableTimer = setTimeout(() => notice.classList.remove("visible"), 7000)
	}
	addEventListener(type, callback){
		var addedType = this.allEvents.get(type)
		if(!addedType){
			addedType = new Set()
			this.allEvents.set(type, addedType)
		}
		return addedType.add(callback)
	}
	removeEventListener(type, callback){
		var addedType = this.allEvents.get(type)
		if(addedType){
			return addedType.delete(callback)
		}
	}
	open(){
		if(!this.closed || this.disabled || this.connecting){
			return
		}
		this.closed = false
		this.connecting = true
		var attempt = ++this.connectionAttempt
		this.resolveServer().then(server => {
			if(this.closed || attempt !== this.connectionAttempt){
				return
			}
			this.serverId = server.id
			this.socket = new WebSocket(server.ws_url)
			pageEvents.add(this.socket, "close", event => {
				if(event.code === 1013){
					this.showUnavailableNotice("multiplayer_full")
				}
			})
			pageEvents.race(this.socket, "open", "close").then(response => {
				if(attempt !== this.connectionAttempt){
					return
				}
				if(response.type === "open"){
					return this.openEvent()
				}
				return this.closeEvent()
			})
			pageEvents.add(this.socket, "message", this.messageEvent.bind(this))
		}, error => {
			if(attempt === this.connectionAttempt){
				this.showUnavailableNotice(error && error.message)
				pageEvents.send("p2-unavailable", error && error.message)
				this.pendingMessages = []
				this.requestedNodeId = null
				this.requireSingleServer = false
				this.closeEvent()
			}
		})
	}
	openEvent(){
		this.connecting = false
		this.startLatencyProbe()
		var messages = this.pendingMessages.splice(0)
		messages.forEach(message => this.send(message.type, message.value))
		var addedType = this.allEvents.get("open")
		if(addedType){
			addedType.forEach(callback => callback())
		}
	}
	close(){
		this.connectionAttempt++
		this.connecting = false
		this.closed = true
		if(this.socket){
			this.socket.close()
		}
		this.stopLatencyProbe()
	}
	closeEvent(){
		var wasActive = !this.closed || this.connecting
		this.connecting = false
		this.closed = true
		this.socket = null
		this.stopLatencyProbe()
		this.otherConnected = false
		this.session = false
		if(this.hashLock){
			this.hash("")
			this.hashLock = false
		}
		if(wasActive){
			pageEvents.send("p2-disconnected")
		}
		var addedType = this.allEvents.get("close")
		if(addedType){
			addedType.forEach(callback => callback())
		}
	}
	send(type, value){
		if(this.socket && this.socket.readyState === this.socket.OPEN){
			if(typeof value === "undefined"){
				this.socket.send(JSON.stringify({type: type}))
			}else{
				this.socket.send(JSON.stringify({type: type, value: value}))
			}
		}else if(!this.disabled){
			this.pendingMessages.push({type: type, value: value})
			this.open()
		}
	}
	startLatencyProbe(){
		this.stopLatencyProbe()
		var probe = () => {
			if(this.socket && this.socket.readyState === this.socket.OPEN){
				this.socket.send(JSON.stringify({
					type: "syncping",
					value: {sentAt: Date.now()}
				}))
			}
		}
		probe()
		this.pingTimer = setInterval(probe, 5000)
	}
	stopLatencyProbe(){
		if(this.pingTimer){
			clearInterval(this.pingTimer)
			this.pingTimer = null
		}
	}
	updateLatency(value){
		if(!value || !Number.isFinite(value.sentAt)){
			return
		}
		var sample = Math.max(0, Math.min(5000, Date.now() - value.sentAt))
		var difference = Math.abs(sample - this.networkRtt)
		this.networkRtt = this.networkRtt * 0.75 + sample * 0.25
		this.networkJitter = this.networkJitter * 0.75 + difference * 0.25
	}
	judgementGrace(){
		return Math.round(Math.max(350, Math.min(1500,
			this.networkRtt * 1.5 + this.networkJitter * 3 + 100
		)))
	}
	waitForJudgement(ms, endTime){
		return this.otherConnected && ms <= endTime + this.judgementGrace()
	}
	applyScoreState(mekadon, state){
		if(!state || !mekadon || !mekadon.game){
			return
		}
		var game = mekadon.game
		var score = game.globalScore
		var fields = ["points", "good", "ok", "bad", "maxCombo", "drumroll", "gauge"]
		fields.forEach(field => {
			if(Number.isFinite(state[field])){
				score[field] = state[field]
			}
		})
		if(Number.isFinite(state.combo)){
			game.combo = state.combo
			if(game.view){
				game.view.updateCombo(game.combo)
			}
		}
	}
	inviteHash(code){
		if(this.serverId && /^[a-f0-9]{12}$/i.test(this.serverId)){
			return "p2=" + this.serverId + ":" + code
		}
		return code
	}
	messageEvent(event){
		try{
			var response = JSON.parse(event.data)
		}catch(e){
			var response = {}
		}
		if(response.type === "syncpong"){
			this.updateLatency(response.value)
			return
		}
		if(Number.isFinite(response.seq)){
			if(response.seq <= this.remoteSequence){
				return
			}
			this.remoteSequence = response.seq
		}
		this.lastMessages[response.type] = response
		var addedType = this.allEvents.get("message")
		if(addedType){
			addedType.forEach(callback => callback(response))
		}
	}
	getMessage(type){
		if(type in this.lastMessages){
			return this.lastMessages[type]
		}
	}
	clearMessage(type){
		if(type in this.lastMessages){
			this.lastMessages[type] = null
		}
	}
	message(response){
		switch(response.type){
			case "gameload":
				if("player" in response.value){
					this.player = response.value.player === 2 ? 2 : 1
				}
			case "gamestart":
				this.otherConnected = true
				this.notes = []
				this.remoteSequence = 0
				this.pendingScoreState = null
				this.drumrollPace = 45
				this.dai = 2
				this.kaAmount = 0
				this.results = false
				this.branch = "normal"
				scoreStorage.clearP2()
				break
			case "gameend":
				this.otherConnected = false
				if(this.session){
					pageEvents.send("session-end")
				}else if(!this.results){
					pageEvents.send("p2-game-end")
				}
				this.session = false
				if(this.hashLock){
					this.hash("")
					this.hashLock = false
				}
				this.name = null
				this.don = null
				scoreStorage.clearP2()
				break
			case "gameresults":
				this.results = {}
				for(var i in response.value){
					this.results[i] = response.value[i] === null ? null : response.value[i].toString()
				}
				break
			case "note":
				if(response.value && typeof response.value === "object"){
					this.notes.push(response.value)
					if(response.value.dai){
						this.dai = response.value.dai
					}
				}
				break
			case "drumroll":
				if(response.value && typeof response.value === "object"){
					this.drumrollPace = response.value.pace
					this.pendingScoreState = response.value.state || null
					if("kaAmount" in response.value){
						this.kaAmount = response.value.kaAmount
					}
				}
				break
			case "branch":
				this.branch = response.value
				this.branchSet = false
				break
			case "session":
				if(typeof EasySettings !== "undefined"){
					EasySettings.enforceMultiplayerSettings()
				}
				this.clearMessage("users")
				this.otherConnected = true
				this.session = true
				scoreStorage.clearP2()
				if("player" in response.value){
					this.player = response.value.player === 2 ? 2 : 1
				}
				break
			case "name":
				this.name = response.value ? (response.value.name || "").toString() : ""
				this.don = response.value ? (response.value.don) : null
				break
			case "getcrowns":
				if(response.value){
					var output = {}
					for(var i in response.value){
						if(response.value[i]){
							var score = scoreStorage.get(response.value[i], false, true)
							if(score){
								var crowns = {}
								for(var diff in score){
									if(diff !== "title"){
										crowns[diff] = {
											crown: score[diff].crown
										}
									}
								}
							}else{
								var crowns = null
							}
							output[response.value[i]] = crowns
						}
					}
					p2.send("crowns", output)
				}
				break
			case "crowns":
				if(response.value){
					for(var i in response.value){
						scoreStorage.addP2(i, false, response.value[i], true)
					}
				}
				break
		}
	}
	onhashchange(){
		if(this.hashLock){
			this.hash(this.currentHash)
		}else{
			location.reload()
		}
	}
	hash(string){
		this.currentHash = string
		history.replaceState("", "", location.pathname + (string ? "#" + string : ""))
	}
	play(circle, mekadon){
		if(this.pendingScoreState){
			this.applyScoreState(mekadon, this.pendingScoreState)
			this.pendingScoreState = null
		}
		if(this.otherConnected || this.notes.length > 0){
			var type = circle.type
			var drumrollNotes = type === "balloon" || type === "drumroll" || type === "daiDrumroll"
			
			if(drumrollNotes && mekadon.getMS() > circle.endTime + mekadon.delay){
				circle.played(-1, false)
				mekadon.game.updateCurrentCircle()
			}
			
			if(drumrollNotes){
				mekadon.playDrumrollAt(circle, 0, this.drumrollPace, type === "drumroll" || type === "daiDrumroll" ? this.kaAmount : 0)
			}else if(this.notes.length === 0){
				mekadon.play(circle)
			}else{
				var note = this.notes[0]
				if(note.score >= 0){
					var dai = 1
					if(circle.type === "daiDon" || circle.type === "daiKa"){
						dai = this.dai
					}
					if(mekadon.playAt(circle, note.ms, note.score, dai, note.reverse)){
						this.notes.shift()
						this.applyScoreState(mekadon, note.state)
					}
				}else{
					if(mekadon.miss(circle)){
						this.notes.shift()
						this.applyScoreState(mekadon, note.state)
					}
				}
			}
		}else if(mekadon.miss(circle)){
			this.notes.shift()
		}
	}
	enable(){
		this.disabled = Math.max(0, this.disabled - 1)
		setTimeout(this.open.bind(this), 100)
	}
	disable(){
		this.disabled++
		this.pendingMessages = []
		this.close()
	}
}
