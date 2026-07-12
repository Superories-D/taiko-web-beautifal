class MultiplayerChat{
	constructor(connection){
		this.connection = connection
		this.active = false
		this.opened = false
		this.unread = 0
		this.messages = []
		this.lastSentAt = 0
		this.createView()
		this.keyDown = this.onKeyDown.bind(this)
		this.keyUp = this.onKeyUp.bind(this)
		window.addEventListener("keydown", this.keyDown, true)
		window.addEventListener("keyup", this.keyUp, true)
	}
	createView(){
		this.root = document.createElement("div")
		this.root.id = "multiplayer-chat"
		this.root.hidden = true

		this.button = document.createElement("button")
		this.button.id = "multiplayer-chat-button"
		this.button.type = "button"
		this.button.setAttribute("aria-expanded", "false")
		this.button.setAttribute("aria-label", strings.multiplayerChat.open)
		this.button.title = strings.multiplayerChat.shortcut
		this.button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5h16v11H9l-5 3v-14Z"/><path d="M8 9h8M8 13h5"/></svg>'

		this.badge = document.createElement("span")
		this.badge.id = "multiplayer-chat-badge"
		this.badge.hidden = true
		this.button.appendChild(this.badge)

		this.panel = document.createElement("section")
		this.panel.id = "multiplayer-chat-panel"
		this.panel.hidden = true
		this.panel.setAttribute("aria-label", strings.multiplayerChat.title)

		var header = document.createElement("div")
		header.className = "multiplayer-chat-header"
		var title = document.createElement("strong")
		title.textContent = strings.multiplayerChat.title
		var hint = document.createElement("span")
		hint.textContent = strings.multiplayerChat.shortcut
		header.appendChild(title)
		header.appendChild(hint)

		this.list = document.createElement("div")
		this.list.id = "multiplayer-chat-list"
		this.list.setAttribute("aria-live", "polite")

		this.form = document.createElement("form")
		this.form.id = "multiplayer-chat-form"
		this.input = document.createElement("input")
		this.input.id = "multiplayer-chat-input"
		this.input.type = "text"
		this.input.maxLength = 200
		this.input.autocomplete = "off"
		this.input.placeholder = strings.multiplayerChat.placeholder
		this.input.setAttribute("aria-label", strings.multiplayerChat.placeholder)
		this.sendButton = document.createElement("button")
		this.sendButton.type = "submit"
		this.sendButton.textContent = strings.multiplayerChat.send
		this.form.appendChild(this.input)
		this.form.appendChild(this.sendButton)

		this.toast = document.createElement("div")
		this.toast.id = "multiplayer-chat-toast"
		this.toast.hidden = true
		this.toast.setAttribute("role", "status")

		this.panel.appendChild(header)
		this.panel.appendChild(this.list)
		this.panel.appendChild(this.form)
		this.root.appendChild(this.button)
		this.root.appendChild(this.panel)
		this.root.appendChild(this.toast)
		document.body.appendChild(this.root)

		var stoppedEvents = ["mousedown", "mouseup", "touchstart", "touchmove", "touchend"]
		stoppedEvents.forEach(type => {
			this.root.addEventListener(type, event => event.stopPropagation())
		})
		this.button.addEventListener("click", () => this.toggle())
		this.form.addEventListener("submit", event => {
			event.preventDefault()
			this.send()
		})
	}
	activate(){
		if(this.active){
			return
		}
		this.active = true
		this.root.hidden = false
	}
	deactivate(){
		this.active = false
		this.close()
		this.root.hidden = true
		this.messages = []
		this.list.textContent = ""
		this.setUnread(0)
		clearTimeout(this.toastTimer)
		this.toast.hidden = true
	}
	toggle(){
		if(this.opened){
			this.close()
		}else{
			this.open()
		}
	}
	open(){
		if(!this.active){
			return
		}
		this.opened = true
		this.panel.hidden = false
		this.button.setAttribute("aria-expanded", "true")
		this.setUnread(0)
		clearTimeout(this.toastTimer)
		this.toast.hidden = true
		setTimeout(() => this.input.focus(), 0)
	}
	close(){
		this.opened = false
		this.panel.hidden = true
		this.button.setAttribute("aria-expanded", "false")
		if(document.activeElement === this.input){
			this.input.blur()
		}
	}
	onKeyDown(event){
		if(!this.active){
			return
		}
		if(this.opened){
			if(event.key === "Escape"){
				event.preventDefault()
				this.close()
			}
			if(event.target === this.input || event.key === "Escape" || event.key === "Shift"){
				event.stopImmediatePropagation()
			}
			return
		}
		if(event.key === "Shift" && !event.repeat && !event.ctrlKey && !event.altKey && !event.metaKey){
			event.preventDefault()
			event.stopImmediatePropagation()
			this.open()
		}
	}
	onKeyUp(event){
		if(this.active && (this.opened && event.target === this.input || event.key === "Shift" || event.key === "Escape")){
			event.stopImmediatePropagation()
		}
	}
	send(){
		var text = this.cleanText(this.input.value)
		if(!text){
			return
		}
		if(!this.connection.otherConnected || !this.connection.socket || this.connection.socket.readyState !== 1){
			return
		}
		var now = Date.now()
		if(now - this.lastSentAt < 500){
			return
		}
		this.lastSentAt = now
		var value = {
			text: text
		}
		try{
			this.connection.send("chat", value)
		}catch(e){
			return
		}
		this.addMessage(value, true)
		this.input.value = ""
	}
	receive(value){
		if(!this.active || !value || typeof value !== "object"){
			return
		}
		var text = this.cleanText(value.text)
		if(!text){
			return
		}
		var message = {
			text: text,
			name: this.cleanName(this.connection.name) || strings.multiplayerChat.other
		}
		this.addMessage(message, false)
		if(!this.opened){
			this.setUnread(this.unread + 1)
			this.showToast(message)
		}
	}
	cleanText(value){
		if(typeof value !== "string"){
			return ""
		}
		return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 200)
	}
	cleanName(value){
		if(typeof value !== "string"){
			return ""
		}
		return value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 32)
	}
	addMessage(message, own){
		this.messages.push({message: message, own: own})
		if(this.messages.length > 50){
			this.messages.shift()
			if(this.list.firstChild){
				this.list.removeChild(this.list.firstChild)
			}
		}
		var item = document.createElement("div")
		item.className = "multiplayer-chat-message " + (own ? "is-own" : "is-other")
		var name = document.createElement("span")
		name.className = "multiplayer-chat-name"
		name.textContent = own ? strings.multiplayerChat.you : message.name
		var body = document.createElement("span")
		body.className = "multiplayer-chat-text"
		body.textContent = message.text
		item.appendChild(name)
		item.appendChild(body)
		this.list.appendChild(item)
		this.list.scrollTop = this.list.scrollHeight
	}
	setUnread(amount){
		this.unread = Math.max(0, amount)
		this.badge.textContent = this.unread > 99 ? "99+" : this.unread
		this.badge.hidden = this.unread === 0
	}
	showToast(message){
		this.toast.textContent = message.name + ": " + message.text
		this.toast.hidden = false
		clearTimeout(this.toastTimer)
		this.toastTimer = setTimeout(() => {
			this.toast.hidden = true
		}, 6000)
	}
}
