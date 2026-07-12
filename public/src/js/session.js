class Session{
	constructor(...args){
		this.init(...args)
	}
	init(touchEnabled){
		this.touchEnabled = touchEnabled
		loader.changePage("session", true)
		this.endButton = this.getElement("view-end-button")
		this.copyButton = this.getElement("session-copy-button")
		if(touchEnabled){
			this.getElement("view-outer").classList.add("touch-enabled")
		}
		this.sessionInvite = document.getElementById("session-invite")
		
		var tutorialTitle = this.getElement("view-title")
		tutorialTitle.innerText = strings.session.multiplayerSession
		tutorialTitle.setAttribute("alt", strings.session.multiplayerSession)
		this.sessionInvite.parentNode.insertBefore(document.createTextNode(strings.session.linkTutorial), this.sessionInvite)
		this.endButton.innerText = strings.session.cancel
		this.endButton.setAttribute("alt", strings.session.cancel)
		this.copyButton.innerText = strings.session.copy
		this.copyButton.setAttribute("alt", strings.session.copy)
		
		pageEvents.add(window, ["mousedown", "touchstart"], this.mouseDown.bind(this))
		this.keyboard = new Keyboard({
			confirm: ["esc"]
		}, this.keyPress.bind(this))
		this.gamepad = new Gamepad({
			confirm: ["start", "b", "ls", "rs"]
		}, this.keyPress.bind(this))
		
		p2.hashLock = true
		pageEvents.add(p2, "message", response => {
			if(response.type === "invite"){
				var inviteHash = p2.inviteHash(response.value)
				this.sessionInvite.innerText = location.origin + location.pathname + "#" + inviteHash
				p2.hash(inviteHash)
			}else if(response.type === "songsel"){
				p2.clearMessage("users")
				this.onEnd(true)
				pageEvents.send("session-start", "host")
			}
		})
		p2.send("invite", {
			id: null,
			name: account.loggedIn ? account.displayName : null,
			don: account.loggedIn ? account.don : null
		})
		pageEvents.send("session")
	}
	getElement(name){
		return loader.screen.getElementsByClassName(name)[0]
	}
	mouseDown(event){
		if(event.type === "mousedown" && event.which !== 1){
			return
		}
		if(event.target === this.sessionInvite){
			this.sessionInvite.focus()
		}else{
			getSelection().removeAllRanges()
			this.sessionInvite.blur()
		}
		if(event.target === this.copyButton){
			this.copyInvite()
		}else if(event.target === this.endButton){
			this.onEnd()
		}
	}
	copyInvite(){
		var inviteLink = this.sessionInvite.innerText.trim()
		if(!inviteLink){
			return
		}
		var copied = () => this.showCopied()
		if(navigator.clipboard && navigator.clipboard.writeText){
			navigator.clipboard.writeText(inviteLink).then(copied, () => {
				if(this.copyInviteFallback(inviteLink)){
					copied()
				}
			})
		}else if(this.copyInviteFallback(inviteLink)){
			copied()
		}
	}
	copyInviteFallback(inviteLink){
		var textarea = document.createElement("textarea")
		textarea.value = inviteLink
		textarea.style.position = "fixed"
		textarea.style.opacity = "0"
		document.body.appendChild(textarea)
		textarea.select()
		var copied = false
		try{
			copied = document.execCommand("copy")
		}catch(e){}
		document.body.removeChild(textarea)
		return copied
	}
	showCopied(){
		if(!this.copyButton){
			return
		}
		clearTimeout(this.copyFeedbackTimer)
		this.copyButton.innerText = strings.session.copied
		this.copyButton.setAttribute("alt", strings.session.copied)
		this.copyFeedbackTimer = setTimeout(() => {
			this.copyButton.innerText = strings.session.copy
			this.copyButton.setAttribute("alt", strings.session.copy)
		}, 1500)
	}
	keyPress(pressed){
		if(pressed){
			this.onEnd()
		}
	}
	onEnd(fromP2){
		if(!p2.session){
			p2.send("leave")
			p2.hash("")
			p2.hashLock = false
			pageEvents.send("session-cancel")
		}else if(!fromP2){
			return p2.send("songsel")
		}
		this.clean()
		assets.sounds["se_don"].play()
		setTimeout(() => {
			new SongSelect(false, false, this.touchEnabled)
		}, 500)
	}
	clean(){
		clearTimeout(this.copyFeedbackTimer)
		this.keyboard.clean()
		this.gamepad.clean()
		pageEvents.remove(window, ["mousedown", "touchstart"])
		pageEvents.remove(p2, "message")
		delete this.endButton
		delete this.copyButton
		delete this.sessionInvite
	}
}
