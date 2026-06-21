class SoundBuffer{
	constructor(...args){
		this.init(...args)
	}
	init(){
		var AudioContext = window.AudioContext || window.webkitAudioContext
		this.context = new AudioContext()
		this.audioDecoder = this.context.decodeAudioData.bind(this.context)
		this.oggDecoder = this.audioDecoder
		this.oggmentedPromise = null
		this.oggFallbackQueue = Promise.resolve()
		this.oggFallbackActive = false
		pageEvents.add(window, ["click", "touchend", "keypress"], this.pageClicked.bind(this))
		this.gainList = []
	}
	load(file, gain){
		var promise = file.name.endsWith(".ogg") ? this.loadOgg(file) : this.loadAudio(file, this.audioDecoder)
		return promise.then(buffer => {
			return new Sound(gain || {soundBuffer: this}, buffer)
		})
	}
	loadAudio(file, decoder){
		return file.arrayBuffer().then(response => {
			return this.decodeBuffer(decoder, response)
		}).catch(error => Promise.reject([error, file.url]))
	}
	loadOgg(file){
		if(this.oggFallbackActive && this.canUseOggFallback()){
			return this.loadOggFallbackFile(file, new Error("Skipped native OGG decoder after previous native decode failure"))
		}
		return file.arrayBuffer().then(response => {
			return this.decodeBuffer(this.oggDecoder, response).catch(nativeError => {
				if(!this.canUseOggFallback()){
					return Promise.reject(nativeError)
				}
				return this.loadOggFallbackFile(file, nativeError).then(buffer => {
					this.oggFallbackActive = true
					return buffer
				})
			})
		}).catch(error => Promise.reject([error, file.url]))
	}
	decodeBuffer(decoder, response){
		return new Promise((resolve, reject) => {
			var promise
			try{
				promise = decoder(response, resolve, reject)
			}catch(error){
				reject(error)
			}
			if(promise && typeof promise.then === "function"){
				promise.then(resolve, reject)
			}
		})
	}
	canUseOggFallback(){
		return "WebAssembly" in window
	}
	loadOggFallbackFile(file, nativeError){
		return file.arrayBuffer().then(response => {
			return this.decodeOggFallback(response)
		}).catch(fallbackError => {
			return Promise.reject(this.createOggFallbackError(nativeError, fallbackError))
		})
	}
	decodeOggFallback(response){
		var task = this.oggFallbackQueue.then(() => {
			return this.getOggmented().then(oggmented => {
				return new Promise((resolve, reject) => {
					try{
						oggmented.decodeOggData(response, resolve, reject)
					}catch(error){
						reject(error)
					}
				})
			})
		})
		this.oggFallbackQueue = task.catch(() => {})
		return task
	}
	getOggmented(){
		if(typeof Oggmented === "function"){
			return Oggmented()
		}
		if(!this.oggmentedPromise){
			this.oggmentedPromise = this.loadOggmentedScript().then(() => {
				if(typeof Oggmented !== "function"){
					throw new Error("Oggmented decoder did not load")
				}
				return Oggmented()
			}, error => {
				this.oggmentedPromise = null
				return Promise.reject(error)
			})
		}
		return this.oggmentedPromise
	}
	loadOggmentedScript(){
		return new Promise((resolve, reject) => {
			var script = document.createElement("script")
			script.src = this.getOggmentedScriptUrl()
			script.async = true
			script.setAttribute("data-taiko-oggmented", "true")
			script.onload = resolve
			script.onerror = () => {
				reject(new Error("Failed to load OGG fallback decoder: " + script.src))
			}
			document.head.appendChild(script)
		})
	}
	getOggmentedScriptUrl(){
		var queryString = ""
		if(typeof loader !== "undefined" && loader && loader.queryString){
			queryString = loader.queryString
		}else if(typeof gameConfig !== "undefined" && gameConfig._version && gameConfig._version.commit_short){
			queryString = "?" + gameConfig._version.commit_short
		}
		return "src/js/lib/oggmented-wasm.js" + queryString
	}
	createOggFallbackError(nativeError, fallbackError){
		var error = new Error(
			"OGG decode failed (native: " + this.formatDecodeError(nativeError) +
			"; fallback: " + this.formatDecodeError(fallbackError) + ")"
		)
		error.name = "AudioDecodeError"
		error.nativeError = nativeError
		error.fallbackError = fallbackError
		return error
	}
	formatDecodeError(error){
		if(!error){
			return "Unknown error"
		}
		if(typeof error === "string"){
			return error
		}
		if(error.name && error.message){
			return error.name + ": " + error.message
		}
		if(error.message){
			return error.message
		}
		if(error.name){
			return error.name
		}
		return String(error)
	}
	createGain(channel){
		var gain = new SoundGain(this, channel)
		this.gainList.push(gain)
		return gain
	}
	setCrossfade(gain1, gain2, median){
		if(!Array.isArray(gain1)){
			gain1 = [gain1]
		}
		if(!Array.isArray(gain2)){
			gain2 = [gain2]
		}
		gain1.forEach(gain => gain.setCrossfade(1 - median))
		gain2.forEach(gain => gain.setCrossfade(median))
	}
	getTime(){
		return this.context.currentTime
	}
	convertTime(time, absolute){
		time = (time || 0)
		if(time < 0){
			time = 0
		}
		return time + (absolute ? 0 : this.getTime())
	}
	createSource(sound){
		var source = this.context.createBufferSource()
		source.buffer = sound.buffer
		source.connect(sound.gain.gainNode || this.context.destination)
		return source
	}
	pageClicked(){
		if(this.context.state === "suspended"){
			this.context.resume()
		}
	}
	saveSettings(){
		for(var i = 0; i < this.gainList.length; i++){
			var gain = this.gainList[i]
			gain.defaultVol = gain.volume
		}
	}
	loadSettings(){
		for(var i = 0; i < this.gainList.length; i++){
			var gain = this.gainList[i]
			gain.setVolume(gain.defaultVol)
		}
	}
	fallbackDecoder(buffer, resolve, reject){
		Oggmented().then(oggmented => oggmented.decodeOggData(buffer, resolve, reject), reject)
	}
}
class SoundGain{
	constructor(...args){
		this.init(...args)
	}
	init(soundBuffer, channel){
		this.soundBuffer = soundBuffer
		this.gainNode = soundBuffer.context.createGain()
		if(channel){
			var index = channel === "left" ? 0 : 1
			this.merger = soundBuffer.context.createChannelMerger(2)
			this.merger.connect(soundBuffer.context.destination)
			this.gainNode.connect(this.merger, 0, index)
		}else{
			this.gainNode.connect(soundBuffer.context.destination)
		}
		this.setVolume(1)
	}
	load(url){
		return this.soundBuffer.load(url, this)
	}
	convertTime(time, absolute){
		return this.soundBuffer.convertTime(time, absolute)
	}
	setVolume(amount){
		this.gainNode.gain.value = amount * amount
		this.volume = amount
	}
	setVolumeMul(amount){
		this.setVolume(amount * this.defaultVol)
	}
	setCrossfade(amount){
		this.setVolume(Math.sqrt(Math.sin(Math.PI / 2 * amount)))
	}
	fadeIn(duration, time, absolute){
		this.fadeVolume(0, this.volume * this.volume, duration, time, absolute)
	}
	fadeOut(duration, time, absolute){
		this.fadeVolume(this.volume * this.volume, 0, duration, time, absolute)
	}
	fadeVolume(vol1, vol2, duration, time, absolute){
		time = this.convertTime(time, absolute)
		this.gainNode.gain.linearRampToValueAtTime(vol1, time)
		this.gainNode.gain.linearRampToValueAtTime(vol2, time + (duration || 0))
	}
	mute(){
		this.gainNode.gain.value = 0
	}
	unmute(){
		this.setVolume(this.volume)
	}
}
class Sound{
	constructor(...args){
		this.init(...args)
	}
	init(gain, buffer){
		this.gain = gain
		this.buffer = buffer
		this.soundBuffer = gain.soundBuffer
		this.duration = buffer.duration
		this.timeouts = new Set()
		this.sources = new Set()
	}
	copy(gain){
		return new Sound(gain || this.gain, this.buffer)
	}
	getTime(){
		return this.soundBuffer.getTime()
	}
	convertTime(time, absolute){
		return this.soundBuffer.convertTime(time, absolute)
	}
	setTimeouts(time){
		return new Promise(resolve => {
			var relTime = time - this.getTime()
			if(relTime > 0){
				var timeout = setTimeout(() => {
					this.timeouts.delete(timeout)
					resolve()
				}, relTime * 1000)
				this.timeouts.add(timeout)
			}else{
				resolve()
			}
		})
	}
	clearTimeouts(){
		this.timeouts.forEach(timeout => {
			clearTimeout(timeout)
			this.timeouts.delete(timeout)
		})
	}
	playLoop(time, absolute, seek1, seek2, until){
		time = this.convertTime(time, absolute)
		seek1 = seek1 || 0
		if(typeof seek2 === "undefined"){
			seek2 = seek1
		}
		until = until || this.duration
		if(seek1 >= until || seek2 >= until){
			return
		}
		this.loop = {
			started: time + until - seek1,
			seek: seek2,
			until: until
		}
		this.play(time, true, seek1, until)
		this.addLoop()
		this.loop.interval = setInterval(() => {
			this.addLoop()
		}, 100)
	}
	addLoop(){
		while(this.getTime() > this.loop.started - 1){
			this.play(this.loop.started, true, this.loop.seek, this.loop.until)
			this.loop.started += this.loop.until - this.loop.seek
		}
	}
	play(time, absolute, seek, until){
		time = this.convertTime(time, absolute)
		var source = this.soundBuffer.createSource(this)
		seek = seek || 0
		until = until || this.duration
		this.setTimeouts(time).then(() => {
			this.cfg = {
				started: time,
				seek: seek,
				until: until
			}
		})
		source.start(time, Math.max(0, seek || 0), Math.max(0, until - seek))
		source.startTime = time
		this.sources.add(source)
		source.onended = () => {
			this.sources.delete(source)
		}
	}
	stop(time, absolute){
		time = this.convertTime(time, absolute)
		this.sources.forEach(source => {
			try{
				source.stop(Math.max(source.startTime, time))
			}catch(e){}
		})
		this.setTimeouts(time).then(() => {
			if(this.loop){
				clearInterval(this.loop.interval)
			}
			this.clearTimeouts()
		})
	}
	pause(time, absolute){
		if(this.cfg){
			time = this.convertTime(time, absolute)
			this.stop(time, true)
			this.cfg.pauseSeek = time - this.cfg.started + this.cfg.seek
		}
	}
	resume(time, absolute){
		if(this.cfg){
			if(this.loop){
				this.playLoop(time, absolute, this.cfg.pauseSeek, this.loop.seek, this.loop.until)
			}else{
				this.play(time, absolute, this.cfg.pauseSeek, this.cfg.until)
			}
		}
	}
	clean(){
		delete this.buffer
	}
}
