class SiteMessages{
	constructor(...args){
		this.init(...args)
	}
	init(songSelect){
		this.songSelect = songSelect
		this.button = document.getElementById("site-message-button")
		this.badge = document.getElementById("site-message-badge")
		this.overlay = document.getElementById("site-message-overlay")
		this.modal = document.getElementById("site-message-modal")
		this.heading = document.getElementById("site-message-heading")
		this.closeButton = document.getElementById("site-message-close")
		this.list = document.getElementById("site-message-list")
		this.messages = []
		this.loggedIn = false
		this.unreadCount = 0
		this.loaded = false
		this.loading = false
		this.loadError = false
		this.reading = {}

		if(!this.button || !this.overlay || !this.list){
			return
		}

		this.setLabels()
		pageEvents.add(this.button, ["click", "touchend"], this.open.bind(this))
		pageEvents.add(this.closeButton, ["click", "touchend"], this.close.bind(this))
		pageEvents.add(this.overlay, ["click", "touchend"], this.onOverlay.bind(this))
		pageEvents.add(this.list, ["click", "touchend"], this.onListAction.bind(this))
		this.load()
	}
	text(name){
		var source = strings.siteMessages || {}
		var fallback = {
			title: "Messages",
			buttonLabel: "Messages",
			close: "Close",
			loading: "Loading...",
			empty: "No messages.",
			loadError: "Could not load messages.",
			markRead: "Mark as read",
			read: "Read",
			loginToRead: "Log in to mark as read",
			imageAlt: "Message image"
		}
		return source[name] || fallback[name] || name
	}
	setLabels(){
		this.button.setAttribute("aria-label", this.text("buttonLabel"))
		this.button.title = this.text("buttonLabel")
		this.closeButton.setAttribute("aria-label", this.text("close"))
		this.closeButton.title = this.text("close")
		this.heading.textContent = this.text("title")
	}
	open(event){
		if(event){
			event.preventDefault()
			event.stopPropagation()
		}
		this.overlay.hidden = false
		if(!this.loaded && !this.loading){
			this.load()
		}
		this.render()
	}
	close(event){
		if(event){
			event.preventDefault()
			event.stopPropagation()
		}
		this.overlay.hidden = true
	}
	isOpen(){
		return this.overlay && !this.overlay.hidden
	}
	onOverlay(event){
		event.stopPropagation()
		if(event.target === this.overlay){
			this.close(event)
		}
	}
	onListAction(event){
		var button = event.target.closest ? event.target.closest(".site-message-read-button") : null
		if(!button){
			return
		}
		event.preventDefault()
		event.stopPropagation()
		this.markRead(button.dataset.messageId, button)
	}
	load(){
		this.loading = true
		this.loadError = false
		this.render()
		return loader.ajax("api/site-messages").then(response => {
			var json = JSON.parse(response)
			if(json.status !== "ok"){
				return Promise.reject()
			}
			this.messages = json.messages || []
			this.loggedIn = !!json.logged_in
			this.unreadCount = json.unread_count || 0
			this.loaded = true
			this.loading = false
			this.updateBadge()
			this.render()
		}, () => {
			this.loading = false
			this.loadError = true
			this.updateBadge()
			this.render()
		})
	}
	updateBadge(){
		if(!this.badge){
			return
		}
		if(this.unreadCount > 0){
			this.badge.hidden = false
			this.badge.textContent = this.unreadCount > 99 ? "99+" : String(this.unreadCount)
		}else{
			this.badge.hidden = true
			this.badge.textContent = ""
		}
	}
	render(){
		if(!this.list || this.overlay.hidden){
			return
		}
		this.list.textContent = ""
		if(this.loading && !this.loaded){
			this.list.appendChild(this.stateElement(this.text("loading")))
			return
		}
		if(this.loadError){
			this.list.appendChild(this.stateElement(this.text("loadError")))
			return
		}
		if(!this.messages.length){
			this.list.appendChild(this.stateElement(this.text("empty")))
			return
		}
		var fragment = document.createDocumentFragment()
		this.messages.forEach(message => {
			fragment.appendChild(this.messageElement(message))
		})
		this.list.appendChild(fragment)
	}
	stateElement(text){
		var div = document.createElement("div")
		div.className = "site-message-state"
		div.textContent = text
		return div
	}
	messageElement(message){
		var card = document.createElement("article")
		card.className = "site-message-card" + (message.read ? " is-read" : "")

		if(message.title){
			var title = document.createElement("h3")
			title.textContent = message.title
			card.appendChild(title)
		}

		var meta = document.createElement("div")
		meta.className = "site-message-meta"
		meta.textContent = this.formatDate(message.created_at)
		card.appendChild(meta)

		if(message.image_url){
			var image = document.createElement("img")
			image.className = "site-message-image"
			image.src = message.image_url
			image.alt = message.title || this.text("imageAlt")
			image.loading = "lazy"
			card.appendChild(image)
		}

		if(message.body){
			var body = document.createElement("div")
			body.className = "site-message-body"
			body.textContent = message.body
			card.appendChild(body)
		}

		var actions = document.createElement("div")
		actions.className = "site-message-actions"
		if(message.read){
			var read = document.createElement("span")
			read.className = "site-message-read-label"
			read.textContent = this.text("read")
			actions.appendChild(read)
		}else if(this.loggedIn){
			var button = document.createElement("button")
			button.type = "button"
			button.className = "site-message-read-button"
			button.dataset.messageId = message.id
			button.textContent = this.text("markRead")
			actions.appendChild(button)
		}else{
			var login = document.createElement("span")
			login.className = "site-message-login-note"
			login.textContent = this.text("loginToRead")
			actions.appendChild(login)
		}
		card.appendChild(actions)

		return card
	}
	formatDate(value){
		if(!value){
			return ""
		}
		var date = new Date(value)
		if(isNaN(date.getTime())){
			return value
		}
		return date.toLocaleString()
	}
	markRead(messageId, button){
		if(!messageId || this.reading[messageId]){
			return
		}
		this.reading[messageId] = true
		if(button){
			button.disabled = true
		}
		this.postRead(messageId).then(() => {
			this.messages.forEach(message => {
				if(message.id === messageId && !message.read){
					message.read = true
					this.unreadCount = Math.max(0, this.unreadCount - 1)
				}
			})
			delete this.reading[messageId]
			this.updateBadge()
			this.render()
		}, () => {
			delete this.reading[messageId]
			if(button){
				button.disabled = false
			}
		})
	}
	postRead(messageId){
		return loader.getCsrfToken().then(token => {
			return new Promise((resolve, reject) => {
				var request = new XMLHttpRequest()
				request.open("POST", "api/site-messages/" + encodeURIComponent(messageId) + "/read")
				pageEvents.load(request).then(() => {
					if(request.status !== 200){
						reject()
						return
					}
					try{
						var json = JSON.parse(request.response)
					}catch(e){
						reject()
						return
					}
					if(json.status === "ok"){
						resolve()
					}else{
						reject()
					}
				}, reject)
				request.setRequestHeader("X-CSRFToken", token)
				request.send()
			})
		})
	}
	clean(){
		if(!this.button){
			return
		}
		pageEvents.remove(this.button, ["click", "touchend"])
		pageEvents.remove(this.closeButton, ["click", "touchend"])
		pageEvents.remove(this.overlay, ["click", "touchend"])
		pageEvents.remove(this.list, ["click", "touchend"])
		delete this.button
		delete this.badge
		delete this.overlay
		delete this.modal
		delete this.heading
		delete this.closeButton
		delete this.list
	}
}
