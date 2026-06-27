class Loader{
	constructor(...args){
		this.init(...args)
	}
	init(callback){
		this.callback = callback
		this.loadedAssets = 0
		this.assetsDiv = document.getElementById("assets")
		this.screen = document.getElementById("screen")
		this.startTime = Date.now()
		this.errorMessages = []
		this.failedResources = []
		this.warmupFailedResources = []
		this.clientErrors = []
		this.totalAssets = 0
		this.currentStage = "boot-minimal"
		this.currentStageLabel = "Boot Minimal"
		this.retryingResource = null
		this.songSearchGradient = "linear-gradient(to top, rgba(245, 246, 252, 0.08), #ff5963), "
		this.backgroundPromises = []
		this.backgroundRetryBaseDelay = 3000
		this.backgroundRetryMaxDelay = 60000
		this.backgroundRetryLimit = 5
		this.imageLoadPromises = {}
		this.soundLoadPromises = {}
		this.downloadedBytes = 0
		this.downloadSamples = []
		this.downloadSpeedTimer = null
		this.networkConnection = navigator.connection || navigator.mozConnection || navigator.webkitConnection
		this.networkProfile = null
		this.networkChangeHandler = this.onNetworkChange.bind(this)
		
		this.installClientErrorHandlers()
		this.initWorkers()

		if(this.isRepairRoute()){
			this.showRepairPage()
			return
		}
		
		var bootResources = []
		
		bootResources.push({
			url: "src/views/loader.html",
			resourceType: "view",
			promise: this.ajax("src/views/loader.html").then(page => {
				this.screen.innerHTML = page
			})
		})
		
		bootResources.push({
			url: "api/config",
			resourceType: "config",
			promise: this.ajax("api/config").then(conf => {
				gameConfig = JSON.parse(conf)
			})
		})
		
		Promise.allSettled(bootResources.map(resource => resource.promise)).then(results => {
			var failed = results
				.map((result, index) => {
					return {
						result: result,
						resource: bootResources[index]
					}
				})
				.filter(item => item.result.status === "rejected")
			if(failed.length){
				this.showBootError(failed.map(item => this.normalizeResourceError(item.result.reason, {
					url: item.resource.url,
					stage: "boot-minimal",
					resourceType: item.resource.resourceType,
					critical: true
				})))
				return
			}
			this.run()
		})
	}
	initWorkers(){
		this.workers = []
		this.workerQueue = []
		this.workerCallbacks = {}
		this.workerId = 0
		this.networkProfile = this.getNetworkProfile()
		this.workerTarget = this.networkProfile.concurrency
		this.resizeWorkers(this.workerTarget)
		if(this.networkConnection && this.networkConnection.addEventListener){
			this.networkConnection.addEventListener("change", this.networkChangeHandler)
		}
		window.addEventListener("online", this.networkChangeHandler)
		window.addEventListener("offline", this.networkChangeHandler)
	}
	getDownloadConcurrency(){
		return this.getNetworkProfile().concurrency
	}
	getNetworkProfile(){
		var connection = this.networkConnection || navigator.connection || navigator.mozConnection || navigator.webkitConnection
		var cpuConcurrency = navigator.hardwareConcurrency || 4
		var effectiveType = connection && connection.effectiveType || "unknown"
		var downlink = connection && Number(connection.downlink) || 0
		var rtt = connection && Number(connection.rtt) || 0
		var profile = {
			name: effectiveType === "4g" ? "fast" : "default",
			label: effectiveType === "unknown" ? "Auto" : effectiveType.toUpperCase(),
			concurrency: Math.min(24, Math.max(12, cpuConcurrency * 2)),
			retries: 3,
			timeout: 12000,
			baseDelay: 500,
			maxDelay: 5000,
			jitter: 300,
			workerRecoveries: 2
		}
		if(navigator.onLine === false){
			return Object.assign(profile, {
				name: "offline",
				label: "Offline recovery",
				concurrency: 2,
				retries: 8,
				timeout: 5000,
				baseDelay: 750,
				maxDelay: 5000,
				jitter: 500,
				workerRecoveries: 4
			})
		}
		if(connection && connection.saveData){
			return Object.assign(profile, {
				name: "save-data",
				label: "Data saver",
				concurrency: 4,
				retries: 5,
				timeout: 22000,
				baseDelay: 1200,
				maxDelay: 12000,
				jitter: 700,
				workerRecoveries: 3
			})
		}
		if(effectiveType === "slow-2g" || effectiveType === "2g" || downlink && downlink <= 0.5 || rtt >= 800){
			return Object.assign(profile, {
				name: "slow",
				label: effectiveType === "unknown" ? "Slow network" : effectiveType.toUpperCase(),
				concurrency: 4,
				retries: 5,
				timeout: 20000,
				baseDelay: 1200,
				maxDelay: 12000,
				jitter: 700,
				workerRecoveries: 3
			})
		}
		if(effectiveType === "3g" || downlink && downlink < 2 || rtt >= 300){
			return Object.assign(profile, {
				name: "moderate",
				label: effectiveType === "unknown" ? "Moderate network" : effectiveType.toUpperCase(),
				concurrency: 8,
				retries: 4,
				timeout: 18000,
				baseDelay: 800,
				maxDelay: 8000,
				jitter: 500,
				workerRecoveries: 3
			})
		}
		return profile
	}
	getRetryOptions(overrides){
		var profile = this.networkProfile || this.getNetworkProfile()
		var options = {
			retries: profile.retries,
			timeout: profile.timeout,
			baseDelay: profile.baseDelay,
			maxDelay: profile.maxDelay,
			jitter: profile.jitter,
			workerRecoveries: profile.workerRecoveries
		}
		overrides = overrides || {}
		for(var key in overrides){
			if(overrides[key] != null){
				options[key] = overrides[key]
			}
		}
		return options
	}
	getRetryBudget(options){
		options = this.getRetryOptions(options)
		var delayBudget = 0
		for(var attempt = 0; attempt < options.retries; attempt++){
			delayBudget += Math.min(options.baseDelay * Math.pow(2, attempt), options.maxDelay) + options.jitter
		}
		return (options.retries + 1) * options.timeout + delayBudget
	}
	onNetworkChange(){
		var previous = this.networkProfile
		this.networkProfile = this.getNetworkProfile()
		this.workerTarget = this.networkProfile.concurrency
		this.workerQueue.forEach(task => {
			task.options = this.getRetryOptions(task.retryOverrides)
			task.maxWorkerRecoveries = task.options.workerRecoveries
		})
		if(previous && (previous.name !== this.networkProfile.name || previous.concurrency !== this.networkProfile.concurrency)){
			this.requeueActiveTasksForNetworkChange()
		}
		this.resizeWorkers(this.workerTarget)
		this.workerRun()
		if(!previous || previous.name !== this.networkProfile.name || previous.concurrency !== this.networkProfile.concurrency){
			this.updateLoaderStatus()
		}
	}
	requeueActiveTasksForNetworkChange(){
		var tasks = []
		this.workers.slice().forEach(workerObj => {
			if(!workerObj.active || workerObj.taskId == null){
				return
			}
			var task = this.workerCallbacks[workerObj.taskId]
			if(task){
				delete this.workerCallbacks[task.id]
				clearTimeout(task.watchdog)
				task.worker = null
				task.loaded = 0
				task.options = this.getRetryOptions(task.retryOverrides)
				task.maxWorkerRecoveries = Math.max(task.maxWorkerRecoveries, task.options.workerRecoveries)
				tasks.push(task)
			}
			this.removeWorker(workerObj)
		})
		if(tasks.length){
			this.workerQueue = tasks.concat(this.workerQueue)
		}
	}
	createWorker(){
		var worker = new Worker("src/js/loader-worker.js")
		var workerObj = {
			worker: worker,
			active: false,
			taskId: null,
			retiring: false,
			failed: false
		}
		worker.onmessage = e => this.onWorkerMessage(e, workerObj)
		worker.onerror = event => {
			if(event && event.preventDefault){
				event.preventDefault()
			}
			this.handleWorkerFailure(workerObj, {
				code: "WORKER_CRASHED",
				message: event && event.message || "Resource worker crashed"
			})
		}
		worker.onmessageerror = () => {
			this.handleWorkerFailure(workerObj, {
				code: "WORKER_MESSAGE_ERROR",
				message: "Resource worker returned an unreadable message"
			})
		}
		this.workers.push(workerObj)
		return workerObj
	}
	resizeWorkers(target){
		target = Math.max(1, Math.min(32, Number(target) || 1))
		var current = this.workers.filter(worker => !worker.retiring && !worker.failed).length
		while(current < target){
			this.createWorker()
			current++
		}
		if(current > target){
			var excess = current - target
			for(var i = this.workers.length - 1; i >= 0 && excess > 0; i--){
				var workerObj = this.workers[i]
				if(workerObj.retiring || workerObj.failed){
					continue
				}
				if(workerObj.active){
					workerObj.retiring = true
				}else{
					this.removeWorker(workerObj)
				}
				excess--
			}
		}
	}
	removeWorker(workerObj){
		if(!workerObj){
			return
		}
		workerObj.failed = true
		workerObj.worker.onmessage = null
		workerObj.worker.onerror = null
		workerObj.worker.onmessageerror = null
		workerObj.worker.terminate()
		var index = this.workers.indexOf(workerObj)
		if(index !== -1){
			this.workers.splice(index, 1)
		}
	}
	onWorkerMessage(e, workerObj){
		var data = e.data
		var callback = this.workerCallbacks[data.id]
		if(callback && callback.worker === workerObj){
			this.armWorkerWatchdog(callback)
			if(data.progress || data.retry){
				this.updateDownloadProgress(callback, data.loaded, data.total)
				if(data.retry){
					this.retryingResource = {
						url: callback.url,
						attempt: data.attempt,
						retries: data.retries
					}
					this.updateLoaderStatus()
				}
				return
			}
			delete this.workerCallbacks[data.id]
			clearTimeout(callback.watchdog)
			this.updateDownloadProgress(callback, data.loaded, data.total)
			if(this.retryingResource && this.retryingResource.url === callback.url){
				this.retryingResource = null
			}
			if(data.error){
				callback.reject(data.error)
			}else{
				callback.resolve(data.data)
			}
			this.workerFree(workerObj)
		}
	}
	workerFetch(url, type, options){
		return new Promise((resolve, reject) => {
			var id = ++this.workerId
			var retryOverrides = Object.assign({}, options || {})
			var taskOptions = this.getRetryOptions(retryOverrides)
			this.workerQueue.push({
				id: id,
				url: new URL(url, location.href).href,
				type: type,
				options: taskOptions,
				retryOverrides: retryOverrides,
				resolve: resolve,
				reject: reject,
				loaded: 0,
				total: 0,
				recoveryAttempts: 0,
				maxWorkerRecoveries: taskOptions.workerRecoveries
			})
			this.workerRun()
		})
	}
	workerRun(){
		if(this.workerQueue.length === 0){
			return
		}
		for(var workerIndex = 0; workerIndex < this.workers.length && this.workerQueue.length; workerIndex++){
			var workerObj = this.workers[workerIndex]
			if(workerObj.active || workerObj.retiring || workerObj.failed){
				continue
			}
			var task = this.workerQueue.shift()
			workerObj.active = true
			workerObj.taskId = task.id
			task.worker = workerObj
			this.workerCallbacks[task.id] = task
			this.armWorkerWatchdog(task)
			workerObj.worker.postMessage({
				id: task.id,
				url: task.url,
				type: task.type,
				options: task.options
			})
		}
	}
	armWorkerWatchdog(task){
		clearTimeout(task.watchdog)
		var timeout = Math.max(15000, (task.options.timeout || 15000) + (task.options.maxDelay || 5000) + 5000)
		task.watchdog = setTimeout(() => {
			this.handleWorkerFailure(task.worker, {
				code: "WORKER_STALLED",
				message: "Resource worker stopped responding"
			})
		}, timeout)
	}
	handleWorkerFailure(workerObj, failure){
		if(!workerObj || workerObj.failed){
			return
		}
		var task = workerObj.taskId != null ? this.workerCallbacks[workerObj.taskId] : null
		if(task){
			delete this.workerCallbacks[task.id]
			clearTimeout(task.watchdog)
			task.worker = null
		}
		this.removeWorker(workerObj)
		if(task){
			task.recoveryAttempts++
			if(task.recoveryAttempts <= task.maxWorkerRecoveries){
				task.options = this.getRetryOptions(task.retryOverrides)
				task.maxWorkerRecoveries = Math.max(task.maxWorkerRecoveries, task.options.workerRecoveries)
				task.loaded = 0
				this.retryingResource = {
					url: task.url,
					attempt: task.recoveryAttempts + 1,
					retries: task.maxWorkerRecoveries + 1
				}
				this.workerQueue.unshift(task)
				this.updateLoaderStatus()
			}else{
				var error = new Error(failure.message)
				error.code = failure.code
				error.detail = {
					url: task.url,
					resourceType: task.options.resourceType,
					retries: task.recoveryAttempts - 1
				}
				if(this.retryingResource && this.retryingResource.url === task.url){
					this.retryingResource = null
				}
				task.reject(error)
			}
		}
		this.resizeWorkers(this.workerTarget || this.getDownloadConcurrency())
		this.workerRun()
	}
	workerFree(workerObj){
		if(workerObj && !workerObj.failed){
			workerObj.active = false
			workerObj.taskId = null
			if(workerObj.retiring){
				this.removeWorker(workerObj)
			}
			this.workerRun()
		}
	}
	updateDownloadProgress(task, loaded, total){
		if(!task || loaded == null){
			return
		}
		loaded = Math.max(0, Number(loaded) || 0)
		var delta = Math.max(0, loaded - task.loaded)
		task.loaded = loaded
		task.total = Math.max(task.total || 0, Number(total) || 0)
		if(delta){
			this.downloadedBytes += delta
			this.recordDownloadSample()
		}
	}
	recordDownloadSample(){
		var now = performance.now()
		this.downloadSamples.push({
			at: now,
			bytes: this.downloadedBytes
		})
		while(this.downloadSamples.length > 2 && this.downloadSamples[1].at < now - 2000){
			this.downloadSamples.shift()
		}
	}
	startDownloadSpeedMeter(){
		this.recordDownloadSample()
		clearInterval(this.downloadSpeedTimer)
		this.downloadSpeedTimer = setInterval(() => {
			this.updateDownloadSpeed()
		}, 250)
		this.updateDownloadSpeed()
	}
	updateDownloadSpeed(){
		if(!this.loaderSpeed){
			return
		}
		var now = performance.now()
		this.downloadSamples.push({
			at: now,
			bytes: this.downloadedBytes
		})
		while(this.downloadSamples.length > 2 && this.downloadSamples[1].at < now - 1500){
			this.downloadSamples.shift()
		}
		var first = this.downloadSamples[0]
		var last = this.downloadSamples[this.downloadSamples.length - 1]
		var elapsed = Math.max(1, last.at - first.at)
		var bytesPerSecond = (last.bytes - first.bytes) * 1000 / elapsed
		var active = this.workers.filter(worker => worker.active).length
		var networkLabel = this.networkProfile && this.networkProfile.label || "Auto"
		this.loaderSpeed.textContent = "Speed: " + this.formatBytes(bytesPerSecond) + "/s | " + active + " active | " + networkLabel
	}
	formatBytes(bytes){
		if(!isFinite(bytes) || bytes <= 0){
			return "0 B"
		}
		var units = ["B", "KB", "MB", "GB"]
		var unit = 0
		while(bytes >= 1024 && unit < units.length - 1){
			bytes /= 1024
			unit++
		}
		var precision = unit === 0 || bytes >= 100 ? 0 : bytes >= 10 ? 1 : 2
		return bytes.toFixed(precision) + " " + units[unit]
	}
	installClientErrorHandlers(){
		if(window.taikoClientErrorHandlersInstalled){
			return
		}
		window.taikoClientErrorHandlersInstalled = true
		window.taikoClientErrors = window.taikoClientErrors || []
		window.addEventListener("error", event => {
			this.reportClientError({
				code: "WINDOW_ERROR",
				message: event.message,
				filename: event.filename,
				lineno: event.lineno,
				colno: event.colno,
				stack: event.error && event.error.stack
			})
		})
		window.addEventListener("unhandledrejection", event => {
			this.reportClientError({
				code: "UNHANDLED_REJECTION",
				reason: String(event.reason),
				stack: event.reason && event.reason.stack
			})
		})
	}
	reportClientError(error){
		var detail = Object.assign({
			version: this.getVersion(),
			buildId: this.getBuildId(),
			stage: this.currentStage,
			browser: this.getBrowserName(),
			os: this.getOsName(),
			at: new Date().toISOString()
		}, error)
		window.taikoClientErrors.push(detail)
		this.clientErrors.push(detail)
		return detail
	}
	isRepairRoute(){
		return location.pathname.replace(/\/+$/, "").endsWith("/repair") || location.search.indexOf("repair=1") !== -1 || location.hash === "#repair"
	}
	inferResourceType(url){
		if(!url){
			return "unknown"
		}
		if(url.indexOf("api/songs") !== -1){
			return "song-list"
		}
		if(url.indexOf("api/config") !== -1){
			return "config"
		}
		if(url.indexOf("api/categories") !== -1){
			return "categories"
		}
		if(url.indexOf("audio/") !== -1 || /\.(ogg|mp3|wav)(\?|$)/.test(url)){
			return "audio"
		}
		if(url.indexOf("img/") !== -1 || /\.(png|jpg|jpeg|webp|gif|svg)(\?|$)/.test(url)){
			return "image"
		}
		if(url.indexOf("fonts/") !== -1 || /\.(ttf|otf|woff|woff2)(\?|$)/.test(url)){
			return "font"
		}
		if(/\.css(\?|$)/.test(url)){
			return "css"
		}
		if(/\.js(\?|$)/.test(url)){
			return "javascript"
		}
		if(/\.html(\?|$)/.test(url)){
			return "view"
		}
		return "unknown"
	}
	normalizeResourceError(error, resource){
		resource = resource || {}
		var detail = error && error.detail || error
		var message
		if(typeof error === "string"){
			message = error
		}else if(Array.isArray(error)){
			var arrayError = error[0]
			detail = arrayError && arrayError.detail || arrayError || detail
			message = this.formatErrorMessage(arrayError)
		}else if(error && error.message){
			message = error.message
		}else{
			message = this.formatErrorMessage(error)
		}
		return {
			code: error && error.code || "BOOT_RESOURCE_FAILED",
			message: message,
			name: error && error.name || detail && detail.name || "Error",
			status: error && error.status || detail && detail.status || null,
			url: resource.url || detail && detail.url || "unknown",
			resourceType: resource.resourceType || detail && detail.resourceType || this.inferResourceType(resource.url),
			stage: resource.stage || this.currentStage || "boot-minimal",
			critical: resource.critical !== false,
			attempts: detail && detail.retries != null ? detail.retries + 1 : resource.attempts || null,
			duration: detail && detail.duration || null
		}
	}
	formatErrorMessage(error){
		if(error == null){
			return "Unknown error"
		}
		if(typeof error === "string"){
			return error
		}
		if(error.message){
			return error.name && error.name !== "Error" ? error.name + ": " + error.message : error.message
		}
		if(error.name){
			return error.name
		}
		return String(error)
	}
	recordResourceFailure(error){
		this.failedResources.push(error)
		this.errorMessages.push(this.formatResourceError(error))
		pageEvents.send("loader-error", error)
		this.reportClientError(Object.assign({
			code: error.critical ? "BOOT_RESOURCE_FAILED" : "WARMUP_RESOURCE_FAILED"
		}, error))
		this.updateLoaderStatus()
	}
	recordWarmupFailure(error){
		this.warmupFailedResources.push(error)
		this.recordResourceFailure(error)
		this.showWarmupWarning()
	}
	formatResourceError(error){
		var status = error.status ? "HTTP " + error.status : error.name || "error"
		return "[" + (error.stage || "boot") + "] " + (error.url || "unknown") + " - " + status + ": " + (error.message || "")
	}
	waitForStage(promises, stage){
		var stagePromises = promises.filter(promise => !promise.resource || promise.resource.critical !== false)
		return Promise.allSettled(stagePromises).then(results => {
			var failed = results
				.filter(result => result.status === "rejected")
				.map(result => result.reason)
			if(failed.length){
				this.showBootError(failed)
				return Promise.reject(failed[0])
			}
		})
	}
	withTimeout(promise, resource, timeout){
		timeout = timeout || 15000
		if(!timeout){
			return promise
		}
		var timer
		var timeoutPromise = new Promise((resolve, reject) => {
			timer = setTimeout(() => {
				var error = new Error("Timeout after " + timeout + "ms")
				error.code = "RESOURCE_TIMEOUT"
				error.detail = {
					url: resource && resource.url,
					resourceType: resource && resource.resourceType,
					retries: 0
				}
				reject(error)
			}, timeout)
		})
		return Promise.race([promise, timeoutPromise]).then(value => {
			clearTimeout(timer)
			return value
		}, error => {
			clearTimeout(timer)
			return Promise.reject(error)
		})
	}
	sleep(ms){
		return new Promise(resolve => setTimeout(resolve, ms))
	}
	async fetchWithRetry(url, options){
		options = this.getRetryOptions(options)
		var retries = options.retries
		var timeout = options.timeout
		var baseDelay = options.baseDelay
		var maxDelay = options.maxDelay
		var jitter = options.jitter
		var retryOnStatus = options.retryOnStatus || [408, 425, 429, 500, 502, 503, 504]
		var resourceType = options.resourceType || this.inferResourceType(url)
		var critical = options.critical !== false
		var fetchOptions = options.fetchOptions || {}
		var lastError = null
		for(var attempt = 0; attempt <= retries; attempt++){
			var controller = new AbortController()
			var timer = setTimeout(() => controller.abort(), timeout)
			var startedAt = Date.now()
			if(attempt > 0){
				this.retryingResource = {
					url: url,
					attempt: attempt + 1,
					retries: retries + 1
				}
				this.updateLoaderStatus()
			}
			try{
				var response = await fetch(url, Object.assign({}, fetchOptions, {
					signal: controller.signal
				}))
				var duration = Date.now() - startedAt
				if(!response.ok){
					var httpError = new Error("HTTP " + response.status + " " + response.statusText)
					httpError.status = response.status
					httpError.url = url
					httpError.resourceType = resourceType
					httpError.duration = duration
					throw httpError
				}
				var result = response
				if(options.responseType === "arraybuffer"){
					result = await response.arrayBuffer()
				}else if(options.responseType === "blob"){
					result = await response.blob()
				}else if(options.responseType === "text"){
					result = await response.text()
				}
				clearTimeout(timer)
				this.retryingResource = null
				return result
			}catch(error){
				clearTimeout(timer)
				lastError = {
					message: error && error.message || String(error),
					name: error && error.name || "Error",
					status: error && error.status || null,
					url: url,
					resourceType: resourceType,
					attempt: attempt,
					retries: retries,
					critical: critical,
					duration: Date.now() - startedAt
				}
				var retryableStatus = !lastError.status || retryOnStatus.indexOf(lastError.status) !== -1
				if(attempt >= retries || !retryableStatus){
					break
				}
				var delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay) + Math.floor(Math.random() * jitter)
				await this.waitForNetworkRetry(delay)
			}
		}
		this.retryingResource = null
		var finalError = new Error("Failed to fetch resource after " + (retries + 1) + " attempts: " + url)
		finalError.code = "RESOURCE_FETCH_FAILED"
		finalError.detail = lastError
		throw finalError
	}
	waitForNetworkRetry(delay){
		if(navigator.onLine !== false){
			return this.sleep(delay)
		}
		return new Promise(resolve => {
			var done = () => {
				clearTimeout(timer)
				window.removeEventListener("online", done)
				resolve()
			}
			var timer = setTimeout(done, delay)
			window.addEventListener("online", done, {
				once: true
			})
		})
	}
	loadImageElement(image, url, options){
		options = options || {}
		return this.workerFetch(url, "blob", Object.assign({
			resourceType: "image"
		}, options)).then(blob => {
			var blobUrl = URL.createObjectURL(blob)
			var loadPromise = pageEvents.load(image)
			image.src = blobUrl
			return loadPromise.then(() => {
				return {
					image: image,
					blobUrl: blobUrl
				}
			}, error => {
				URL.revokeObjectURL(blobUrl)
				return Promise.reject(error)
			})
		})
	}
	loadStylesheet(url, options){
		options = this.getRetryOptions(options)
		var attempt = 0
		var run = () => {
			return new Promise((resolve, reject) => {
				var stylesheet = document.createElement("link")
				stylesheet.rel = "stylesheet"
				var timer
				var settled = false
				var cleanup = () => {
					clearTimeout(timer)
					stylesheet.onload = null
					stylesheet.onerror = null
				}
				stylesheet.onload = () => {
					if(settled){
						return
					}
					settled = true
					cleanup()
					resolve(stylesheet)
				}
				stylesheet.onerror = () => {
					if(settled){
						return
					}
					settled = true
					cleanup()
					stylesheet.remove()
					reject(new Error("Stylesheet failed to load: " + url))
				}
				timer = setTimeout(stylesheet.onerror, options.timeout)
				stylesheet.href = url
				document.head.appendChild(stylesheet)
			}).catch(error => {
				if(attempt >= options.retries){
					return Promise.reject(error)
				}
				var delay = Math.min(options.baseDelay * Math.pow(2, attempt), options.maxDelay) + Math.floor(Math.random() * options.jitter)
				attempt++
				this.retryingResource = {
					url: url,
					attempt: attempt + 1,
					retries: options.retries + 1
				}
				this.updateLoaderStatus()
				return this.waitForNetworkRetry(delay).then(run)
			})
		}
		return run().then(stylesheet => {
			if(this.retryingResource && this.retryingResource.url === url){
				this.retryingResource = null
			}
			return stylesheet
		})
	}
	getVersion(){
		if(gameConfig && gameConfig._version && gameConfig._version.version){
			return gameConfig._version.version
		}
		var versionLink = document.getElementById("version-link")
		return versionLink ? versionLink.textContent.trim() : "unknown"
	}
	getBuildId(){
		if(gameConfig && gameConfig._version){
			return gameConfig._version.commit_short || gameConfig._version.commit || "unknown"
		}
		return "unknown"
	}
	getBrowserName(){
		var ua = navigator.userAgent
		if(ua.indexOf("Edg/") !== -1){
			return "Edge"
		}
		if(ua.indexOf("Chrome/") !== -1){
			return "Chrome"
		}
		if(ua.indexOf("Safari/") !== -1 && ua.indexOf("Chrome/") === -1){
			return "Safari"
		}
		if(ua.indexOf("Firefox/") !== -1){
			return "Firefox"
		}
		return "unknown"
	}
	getOsName(){
		var ua = navigator.userAgent
		if(/Android/.test(ua)){
			return "Android"
		}
		if(/iPhone|iPad|iPod/.test(ua)){
			return "iOS"
		}
		if(/Windows/.test(ua)){
			return "Windows"
		}
		if(/Mac OS X/.test(ua)){
			return "macOS"
		}
		if(/Linux/.test(ua)){
			return "Linux"
		}
		return "unknown"
	}
	escapeHtml(value){
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;")
	}
	async collectDiagnostics(failures){
		var serviceWorker = false
		var serviceWorkerScript = null
		var cacheKeys = []
		try{
			if("serviceWorker" in navigator){
				var registration = await navigator.serviceWorker.getRegistration()
				serviceWorker = !!registration
				serviceWorkerScript = registration && registration.active && registration.active.scriptURL || null
			}
		}catch(e){}
		try{
			if("caches" in window){
				cacheKeys = await caches.keys()
			}
		}catch(e){}
		return {
			code: "BOOT_CRITICAL_RESOURCE_FAILED",
			version: this.getVersion(),
			buildId: this.getBuildId(),
			stage: this.currentStage,
			failures: failures,
			browser: this.getBrowserName(),
			os: this.getOsName(),
			userAgent: navigator.userAgent,
			serviceWorker: serviceWorker,
			serviceWorkerScript: serviceWorkerScript,
			cacheKeys: cacheKeys,
			clientErrors: window.taikoClientErrors || []
		}
	}
	showBootError(failures){
		failures = failures.map(error => this.normalizeResourceError(error))
		if(!failures.length){
			failures = [this.normalizeResourceError("Unknown boot failure")]
		}
		failures.forEach(error => {
			if(this.failedResources.indexOf(error) === -1){
				this.recordResourceFailure(error)
			}
		})
		if(this.error){
			return
		}
		this.error = true
		if(typeof cancelTouch !== "undefined"){
			cancelTouch = false
		}
		var first = failures[0]
		var failureRows = failures.map(error => {
			return "<li><code>" + this.escapeHtml(error.url) + "</code><span>" + this.escapeHtml(error.message || error.name) + "</span></li>"
		}).join("")
		this.screen.innerHTML = `
			<div class="view-outer loader-error-div boot-error-visible">
				<div class="view boot-error-panel">
					<div class="boot-error-title">taiko.asia loading failed</div>
					<div class="boot-error-code">BOOT_CRITICAL_RESOURCE_FAILED</div>
					<div class="boot-error-grid">
						<span>Version</span><strong>${this.escapeHtml(this.getVersion())}</strong>
						<span>Build ID</span><strong>${this.escapeHtml(this.getBuildId())}</strong>
						<span>Failed resource</span><strong>${this.escapeHtml(first.url)}</strong>
						<span>Error type</span><strong>${this.escapeHtml(first.status ? "HTTP " + first.status : first.message || first.name)}</strong>
						<span>Retries</span><strong>${this.escapeHtml(first.attempts == null ? "unknown" : first.attempts - 1)}</strong>
						<span>Browser</span><strong>${this.escapeHtml(this.getBrowserName())}</strong>
						<span>System</span><strong>${this.escapeHtml(this.getOsName())}</strong>
					</div>
					<ul class="boot-error-resources">${failureRows}</ul>
					<div class="boot-error-actions">
						<button type="button" class="boot-reload">Reload</button>
						<button type="button" class="boot-repair">Clear cache and retry</button>
						<button type="button" class="boot-copy">Copy error info</button>
					</div>
					<textarea class="boot-error-diag" readonly></textarea>
				</div>
			</div>
		`
		var diagTextarea = this.screen.querySelector(".boot-error-diag")
		var copyButton = this.screen.querySelector(".boot-copy")
		this.collectDiagnostics(failures).then(diagnostics => {
			var text = JSON.stringify(diagnostics, null, 2)
			diagTextarea.value = text
			copyButton.addEventListener("click", () => this.copyText(text, copyButton))
		})
		this.screen.querySelector(".boot-reload").addEventListener("click", () => location.reload())
		this.screen.querySelector(".boot-repair").addEventListener("click", () => this.repairLocalCache())
		this.clean(true)
	}
	copyText(text, button){
		var done = () => {
			button.textContent = "Copied"
			setTimeout(() => button.textContent = "Copy error info", 1500)
		}
		if(navigator.clipboard && navigator.clipboard.writeText){
			return navigator.clipboard.writeText(text).then(done, () => this.copyTextFallback(text, done))
		}
		return this.copyTextFallback(text, done)
	}
	copyTextFallback(text, done){
		var textarea = document.createElement("textarea")
		textarea.value = text
		document.body.appendChild(textarea)
		textarea.select()
		try{
			document.execCommand("copy")
		}catch(e){}
		document.body.removeChild(textarea)
		done()
	}
	showWarmupWarning(){
		var warning = document.querySelector(".loader-warmup-warning")
		if(warning){
			warning.style.display = "block"
			warning.textContent = "Some resources failed and will retry in the background. Basic play is still available."
		}
	}
	showRepairPage(){
		this.screen.innerHTML = `
			<div class="view-outer loader-error-div boot-error-visible">
				<div class="view boot-error-panel">
					<div class="boot-error-title">Repair local cache</div>
					<div class="boot-error-code">TAIKO_LOCAL_CACHE_REPAIR</div>
					<div class="boot-error-grid">
						<span>Version</span><strong>${this.escapeHtml(this.getVersion())}</strong>
						<span>Build ID</span><strong>${this.escapeHtml(this.getBuildId())}</strong>
						<span>Browser</span><strong>${this.escapeHtml(this.getBrowserName())}</strong>
						<span>System</span><strong>${this.escapeHtml(this.getOsName())}</strong>
					</div>
					<div class="boot-error-actions">
						<button type="button" class="boot-repair">Clear cache and reload</button>
						<button type="button" class="boot-reload">Back to game</button>
					</div>
				</div>
			</div>
		`
		this.screen.querySelector(".boot-repair").addEventListener("click", () => this.repairLocalCache())
		this.screen.querySelector(".boot-reload").addEventListener("click", () => location.href = gameConfig.basedir || "/")
	}
	async deleteIndexedDb(name){
		return new Promise(resolve => {
			var request = indexedDB.deleteDatabase(name)
			request.onsuccess = resolve
			request.onerror = resolve
			request.onblocked = resolve
		})
	}
	async repairLocalCache(){
		if("serviceWorker" in navigator){
			var registrations = await navigator.serviceWorker.getRegistrations()
			for(var registration of registrations){
				await registration.unregister()
			}
		}
		if("caches" in window){
			var keys = await caches.keys()
			for(var key of keys){
				await caches.delete(key)
			}
		}
		if("indexedDB" in window && indexedDB.databases){
			var databases = await indexedDB.databases()
			for(var dbInfo of databases){
				if(!dbInfo.name){
					continue
				}
				var safeToDelete =
					dbInfo.name.startsWith("taiko-cache") ||
					dbInfo.name.startsWith("taiko-assets") ||
					dbInfo.name.startsWith("taiko-temp") ||
					dbInfo.name.startsWith("taiko-song-cache")
				if(safeToDelete){
					await this.deleteIndexedDb(dbInfo.name)
				}
			}
		}
		localStorage.removeItem("taiko_boot_state")
		sessionStorage.clear()
		location.href = gameConfig.basedir || "/"
	}
	getVisitorId(){
		try{
			var id = localStorage.getItem("taiko_visitor_id")
			if(id && /^[a-f0-9]{32}$/.test(id)){
				return id
			}
			var bytes = new Uint8Array(16)
			if(window.crypto && window.crypto.getRandomValues){
				window.crypto.getRandomValues(bytes)
			}else{
				for(var i = 0; i < bytes.length; i++){
					bytes[i] = Math.floor(Math.random() * 256)
				}
			}
			id = Array.from(bytes).map(byte => byte.toString(16).padStart(2, "0")).join("")
			localStorage.setItem("taiko_visitor_id", id)
			return id
		}catch(e){
			return ""
		}
	}
	recordVisit(){
		try{
			fetch("api/visits/record", {
				method: "POST",
				headers: {
					"Content-Type": "application/json"
				},
				body: JSON.stringify({
					visitor_id: this.getVisitorId()
				}),
				keepalive: true
			}).catch(() => {})
		}catch(e){}
	}
	run(){
		this.promises = []
		this.currentStage = "boot-minimal"
		this.currentStageLabel = "Boot Minimal"
		this.loaderDiv = document.querySelector("#loader")
		this.loaderPercentage = document.querySelector("#loader .percentage")
		this.loaderProgress = document.querySelector("#loader .progress")
		this.loaderStatusText = document.querySelector("#loader .loader-status-text")
		this.loaderStage = document.querySelector("#loader .loader-stage")
		this.loaderCount = document.querySelector("#loader .loader-count")
		this.loaderFailed = document.querySelector("#loader .loader-failed")
		this.loaderSpeed = document.querySelector("#loader .loader-speed")
		this.loaderRetry = document.querySelector("#loader .loader-retry")
		this.startDownloadSpeedMeter()
		
		this.queryString = gameConfig._version.commit_short ? "?" + gameConfig._version.commit_short : ""
		this.recordVisit()
		
		if(gameConfig.custom_js){
			this.addPromise(this.loadScript(gameConfig.custom_js), gameConfig.custom_js)
		}
		assets.js.forEach(name => {
			this.addPromise(this.loadScript("src/js/" + name), "src/js/" + name)
		})
		
		var pageVersion = versionLink.href
		var index = pageVersion.lastIndexOf("/")
		if(index !== -1){
			pageVersion = pageVersion.slice(index + 1)
		}
		this.addPromise(new Promise((resolve, reject) => {
			if(
				versionLink.href !== gameConfig._version.url &&
				gameConfig._version.commit &&
				versionLink.href.indexOf(gameConfig._version.commit) === -1
			){
				reject("Version on the page and config does not match\n(page:  " + pageVersion + ",\nconfig: "+ gameConfig._version.commit + ")")
			}
			Promise.all(assets.css.map(name => {
				return this.loadStylesheet("src/css/" + name + this.queryString)
			})).then(resolve, reject)
		}))
		
		for(var name in assets.fonts){
			var url = gameConfig.assets_baseurl + "fonts/" + assets.fonts[name]
			this.addPromise(this.workerFetch(url, "arraybuffer", {
				resourceType: "font"
			}).then(buffer => new FontFace(name, buffer).load()).then(font => {
				document.fonts.add(font)
			}), url, {
				critical: false,
				resourceType: "font",
				stage: "background-warmup"
			})
		}
		
		assets.img.forEach(name => {
			var id = this.getFilename(name)
			var image = document.createElement("img")
			image.crossOrigin = "anonymous"
			var url = gameConfig.assets_baseurl + "img/" + name
			image.id = name
			this.assetsDiv.appendChild(image)
			assets.image[id] = image
			this.addPromise(this.loadImageElement(image, url), url)
		})
		
		var css = []
		for(let selector in assets.cssBackground){
			let name = assets.cssBackground[selector]
			var url = gameConfig.assets_baseurl + "img/" + name
			this.addPromise(loader.ajax(url, request => {
				request.responseType = "blob"
			}).then(blob => {
				var id = this.getFilename(name)
				var image = document.createElement("img")
				let blobUrl = URL.createObjectURL(blob)
				var promise = pageEvents.load(image).then(() => {
					var gradient = ""
					if(selector === ".pattern-bg"){
						loader.screen.style.backgroundImage = "url(\"" + blobUrl + "\")"
					}else if(selector === "#song-search"){
						gradient = this.songSearchGradient
					}
					css.push(this.cssRuleset({
						[selector]: {
							"background-image": gradient + "url(\"" + blobUrl + "\")"
						}
					}))
				})
				image.id = name
				image.src = blobUrl
				this.assetsDiv.appendChild(image)
				assets.image[id] = image
				return promise
			}), url)
		}
		
		assets.views.forEach(name => {
			var id = this.getFilename(name)
			var url = "src/views/" + name + this.queryString
			this.addPromise(this.ajax(url).then(page => {
				assets.pages[id] = page
			}), url)
		})
		
		this.addPromise(this.ajax("api/categories").then(cats => {
			assets.categories = JSON.parse(cats)
			assets.categories.forEach(cat => {
				if(cat.song_skin){
					cat.songSkin = cat.song_skin //rename the song_skin property and add category title to categories array
					delete cat.song_skin
					cat.songSkin.infoFill = cat.songSkin.info_fill
					delete cat.songSkin.info_fill
				}
			})
			if(!assets.categories.some(cat => cat.title === "12 Custom")){
				assets.categories.push({
					id: 12,
					title: "12 Custom",
					title_lang: {
						ja: "カスタム",
						en: "Custom",
						cn: "自定义",
						tw: "自訂",
						ko: "커스텀"
					},
					songSkin: {
						sort: 12,
						background: "#2fb7ac",
						border: ["#a8fff2", "#08736f"],
						outline: "#07585f",
						infoFill: "#07585f"
					}
				})
			}
			
			assets.categories.push({
				title: "default",
				songSkin: {
					background: "#ececec",
					border: ["#fbfbfb", "#8b8b8b"],
					outline: "#656565",
					infoFill: "#656565"
				}
			})
		}), "api/categories")
		
		var url = gameConfig.assets_baseurl + "img/vectors.json" + this.queryString
		this.addPromise(this.ajax(url).then(response => {
			vectors = JSON.parse(response)
		}), url)
		
		this.afterJSCount =
			[
				"api/songs",
				"blurPerformance",
				"categories"
			].length +
			assets.audioSfx.length +
			assets.audioSfxLR.length +
			assets.audioSfxLoud.length +
			(gameConfig.accounts ? 1 : 0)
		
		this.waitForStage(this.promises, "boot-minimal").then(() => {
			if(this.error){
				return
			}
			
			var style = document.createElement("style")
			style.appendChild(document.createTextNode(css.join("\n")))
			document.head.appendChild(style)
			this.currentStage = "boot-minimal"
			this.currentStageLabel = "Boot Minimal"
			
			this.addPromise(this.ajax("api/songs").then(songs => {
				songs = JSON.parse(songs)
				songs.forEach(song => {
					var directory = gameConfig.songs_baseurl + song.id + "/"
					var songExt = song.music_type ? song.music_type : "mp3"
					song.music = new RemoteFile(directory + "main." + songExt)
					if(song.type === "tja"){
						song.chart = new RemoteFile(directory + "main.tja")
					}else{
						song.chart = {separateDiff: true}
						for(var diff in song.courses){
							if(song.courses[diff]){
								song.chart[diff] = new RemoteFile(directory + diff + ".osu")
							}
						}
					}
					if(song.lyrics){
						song.lyricsFile = new RemoteFile(directory + "main.vtt")
					}
					if(song.preview > 0){
						song.previewMusic = new RemoteFile(directory + "preview." + gameConfig.preview_type)
					}
				})
				assets.songsDefault = songs
				assets.songs = assets.songsDefault
			}), "api/songs")
			
			var categoryPromises = []
			assets.categories //load category backgrounds to DOM
				.filter(cat => cat.songSkin && cat.songSkin.bg_img)
				.forEach(cat => {
					let name = cat.songSkin.bg_img
					var url = gameConfig.assets_baseurl + "img/" + name
					categoryPromises.push(loader.ajax(url, request => {
						request.responseType = "blob"
					}).then(blob => {
						var id = this.getFilename(name)
						var image = document.createElement("img")
						let blobUrl = URL.createObjectURL(blob)
						var promise = pageEvents.load(image)
						image.id = name
						image.src = blobUrl
						this.assetsDiv.appendChild(image)
						assets.image[id] = image
						return promise
					}))
				})
			this.addPromise(Promise.allSettled(categoryPromises).then(results => {
				var failed = results.filter(result => result.status === "rejected")
				if(failed.length){
					return Promise.reject(failed.map(result => result.reason).join("\n"))
				}
			}), "category-backgrounds", {
				critical: false,
				resourceType: "category-background",
				stage: "background-warmup"
			})
			
			snd.buffer = new SoundBuffer()
			snd.musicGain = snd.buffer.createGain()
			snd.sfxGain = snd.buffer.createGain()
			snd.previewGain = snd.buffer.createGain()
			snd.sfxGainL = snd.buffer.createGain("left")
			snd.sfxGainR = snd.buffer.createGain("right")
			snd.sfxLoudGain = snd.buffer.createGain()
			snd.buffer.setCrossfade(
				[snd.musicGain, snd.previewGain],
				[snd.sfxGain, snd.sfxGainL, snd.sfxGainR],
				0.5
			)
			snd.sfxLoudGain.setVolume(1.2)
			snd.buffer.saveSettings()
			
			this.afterJSCount = 0
			
			assets.audioSfx.forEach(name => {
				this.addPromise(this.loadSound(name, snd.sfxGain), this.soundUrl(name))
			})
			assets.audioSfxLR.forEach(name => {
				this.addPromise(this.loadSound(name, snd.sfxGain).then(sound => {
					var id = this.getFilename(name)
					assets.sounds[id + "_p1"] = assets.sounds[id].copy(snd.sfxGainL)
					assets.sounds[id + "_p2"] = assets.sounds[id].copy(snd.sfxGainR)
				}), this.soundUrl(name))
			})
			assets.audioSfxLoud.forEach(name => {
				this.addPromise(this.loadSound(name, snd.sfxLoudGain), this.soundUrl(name))
			})
			
			this.canvasTest = new CanvasTest()
			this.addPromise(this.canvasTest.blurPerformance().then(result => {
				perf.blur = result
				if(result > 1000 / 50){
					// Less than 50 fps with blur enabled
					disableBlur = true
				}
			}), "blurPerformance")
			
			if(gameConfig.accounts){
				this.addPromise(this.ajax("api/scores/get").then(response => {
					response = JSON.parse(response)
					if(response.status === "ok"){
						account.loggedIn = true
						account.username = response.username
						account.displayName = response.display_name
						account.don = response.don
						scoreStorage.load(response.scores)
						pageEvents.send("login", account.username)
					}
				}), "api/scores/get")
			}
			
			settings = new Settings()
			pageEvents.setKbd()
			scoreStorage = new ScoreStorage()
			db = new IDB("taiko", "store")
			plugins = new Plugins()
			
			if(localStorage.getItem("lastSearchQuery")){
				localStorage.removeItem("lastSearchQuery")
			}

			this.startBackgroundPreload()

			this.waitForStage(this.promises, "boot-minimal").then(() => {
				if(this.error){
					return
				}
				if(!account.loggedIn){
					scoreStorage.load()
				}
				for(var i in assets.songsDefault){
					var song = assets.songsDefault[i]
					if(!song.hash){
						song.hash = song.title
					}
					scoreStorage.songTitles[song.title] = song.hash
					var score = scoreStorage.get(song.hash, false, true)
					if(score){
						score.title = song.title
					}
				}
				var promises = []
				
				var readyEvent = "normal"
				var songId
				var hashLower = location.hash.toLowerCase()
				p2 = new P2Connection()
				if(hashLower.startsWith("#song=")){
					var number = parseInt(location.hash.slice(6))
					if(number > 0){
						songId = number
						readyEvent = "song-id"
					}
				}else if(location.hash.length === 6){
					p2.hashLock = true
					promises.push(new Promise(resolve => {
						p2.open()
						pageEvents.add(p2, "message", response => {
							if(response.type === "session"){
								pageEvents.send("session-start", "invited")
								readyEvent = "session-start"
								resolve()
							}else if(response.type === "gameend"){
								p2.hash("")
								p2.hashLock = false
								readyEvent = "session-expired"
								resolve()
							}
						})
						p2.send("invite", {
							id: location.hash.slice(1).toLowerCase(),
							name: account.loggedIn ? account.displayName : null,
							don: account.loggedIn ? account.don : null
						})
						setTimeout(() => {
							if(p2.socket.readyState !== 1){
								p2.hash("")
								p2.hashLock = false
								resolve()
							}
						}, 10000)
					}).then(() => {
						pageEvents.remove(p2, "message")
					}))
				}else{
					p2.hash("")
				}
				
				promises.push(this.canvasTest.drawAllImages().then(result => {
					perf.allImg = result
				}))
				
				if(gameConfig.plugins){
					gameConfig.plugins.forEach(obj => {
						if(obj.url){
							var plugin = plugins.add(obj.url, {
								hide: obj.hide
							})
							if(plugin){
								plugin.loadErrors = true
								promises.push(plugin.load(true).then(() => {
									if(obj.start){
										return plugin.start(false, true)
									}
								}).catch(response => {
									this.recordWarmupFailure(this.normalizeResourceError(response, {
										url: obj.url,
										stage: "background-warmup",
										resourceType: "plugin",
										critical: false
									}))
									return null
								}))
							}
						}
					})
				}
				
				Promise.allSettled(promises).then(results => {
					var failed = results.filter(result => result.status === "rejected")
					if(failed.length){
						this.showBootError(failed.map(result => this.normalizeResourceError(result.reason, {
							url: "boot-finalize",
							stage: "boot-minimal",
							resourceType: "finalize",
							critical: true
						})))
						return
					}
					perf.load = Date.now() - this.startTime
					this.canvasTest.clean()
					this.clean()
					this.callback(songId)
					this.ready = true
					pageEvents.send("ready", readyEvent)
				})
			}, () => {})
		}, () => {})
	}
	addPromise(promise, url, options){
		options = options || {}
		var resource = {
			url: url || "unknown",
			critical: options.critical !== false,
			stage: options.stage || this.currentStage || "boot-minimal",
			resourceType: options.resourceType || this.inferResourceType(url),
			attempts: options.retries == null ? null : options.retries + 1
		}
		this.totalAssets++
		this.updateLoaderStatus(resource)
		var timeout = options.timeout || Math.max(resource.critical ? 20000 : 15000, this.getRetryBudget() + 10000)
		var trackedPromise = this.withTimeout(Promise.resolve(promise), resource, timeout).then(value => {
			this.assetLoaded()
			return value
		}, response => {
			var error = this.normalizeResourceError(response, resource)
			if(resource.critical){
				this.recordResourceFailure(error)
				return Promise.reject(error)
			}
			this.recordWarmupFailure(error)
			this.assetLoaded()
			return null
		})
		this.promises.push(trackedPromise)
		trackedPromise.resource = resource
		return trackedPromise
	}
	addBackgroundPromise(promise, url){
		this.backgroundPromises.push(promise)
		promise.catch(response => {
			var error = Array.isArray(response) ? response[0] : response
			if(url){
				error = (error ? error + ": " : "") + url
			}
			console.warn("Background preload failed", error || response)
			pageEvents.send("background-load-error", url || error || response)
		})
		return promise
	}
	addBackgroundTask(task, url, options){
		options = options || {}
		var retries = options.retries == null ? this.backgroundRetryLimit : options.retries
		var baseDelay = options.baseDelay || this.backgroundRetryBaseDelay
		var maxDelay = options.maxDelay || this.backgroundRetryMaxDelay
		var attempt = 0
		var run = () => {
			attempt++
			var promise = Promise.resolve().then(task)
			this.backgroundPromises.push(promise)
			promise.catch(response => {
				var error = Array.isArray(response) ? response[0] : response
				if(url){
					error = (error ? error + ": " : "") + url
				}
				if(attempt <= retries){
					var delay = Math.min(baseDelay * Math.pow(2, attempt - 1), maxDelay) + Math.floor(Math.random() * 300)
					console.warn("Background preload failed, retrying", {
						url: url,
						attempt: attempt,
						nextRetryMs: delay,
						error: error || response
					})
					pageEvents.send("background-load-retry", {
						url: url,
						attempt: attempt,
						nextRetryMs: delay
					})
					setTimeout(run, delay)
				}else{
					console.warn("Background preload failed", error || response)
					pageEvents.send("background-load-error", url || error || response)
					this.recordWarmupFailure(this.normalizeResourceError(response, {
						url: url,
						stage: "background-warmup",
						resourceType: this.inferResourceType(url),
						critical: false,
						attempts: retries + 1
					}))
				}
			})
			return promise
		}
		return run()
	}
	soundUrl(name){
		return gameConfig.assets_baseurl + "audio/" + name
	}
	loadSound(name, gain){
		var id = this.getFilename(name)
		if(assets.sounds[id]){
			return Promise.resolve(assets.sounds[id])
		}
		if(this.soundLoadPromises[id]){
			return this.soundLoadPromises[id]
		}
		this.soundLoadPromises[id] = gain.load(new RemoteFile(this.soundUrl(name))).then(sound => {
			assets.sounds[id] = sound
			delete this.soundLoadPromises[id]
			return sound
		}, response => {
			delete this.soundLoadPromises[id]
			return Promise.reject(response)
		})
		return this.soundLoadPromises[id]
	}
	playBgm(name, args, shouldPlay){
		var id = this.getFilename(name)
		var play = sound => {
			if(!shouldPlay || shouldPlay()){
				sound.playLoop.apply(sound, args)
			}
		}
		if(assets.sounds[id]){
			play(assets.sounds[id])
		}else{
			this.addBackgroundTask(() => this.loadSound(name, snd.musicGain).then(play), this.soundUrl(name), {
				baseDelay: 1000
			})
		}
	}
	loadScaledImage(filename, url, options){
		options = options || {}
		var prefix = options.prefix || ""
		var id = prefix + filename
		if(assets.image[id]){
			return Promise.resolve(assets.image[id])
		}
		if(this.imageLoadPromises[id]){
			return this.imageLoadPromises[id]
		}
		var img = document.createElement("img")
		if(options.crossOrigin !== false){
			img.crossOrigin = "anonymous"
		}
		var sourceUrl
		this.imageLoadPromises[id] = this.workerFetch(url, "blob", {
			resourceType: "image",
			timeout: options.timeout,
			retries: options.retries
		}).then(blob => {
			sourceUrl = URL.createObjectURL(blob)
			var loaded = pageEvents.load(img)
			img.src = sourceUrl
			return loaded
		}).then(() => {
			return this.scaleImage(img, filename, prefix, options.force)
		}).then(image => {
			URL.revokeObjectURL(sourceUrl)
			delete this.imageLoadPromises[id]
			return image
		}, response => {
			if(sourceUrl){
				URL.revokeObjectURL(sourceUrl)
			}
			delete this.imageLoadPromises[id]
			return Promise.reject(response)
		})
		return this.imageLoadPromises[id]
	}
	scaleImage(img, filename, prefix, force){
		return new Promise((resolve, reject) => {
			var scale = this.getImageScale(force)
			var canvas = document.createElement("canvas")
			var w = Math.floor(img.width * scale)
			var h = Math.floor(img.height * scale)
			canvas.width = Math.max(1, w)
			canvas.height = Math.max(1, h)
			var ctx = canvas.getContext("2d")
			ctx.drawImage(img, 0, 0, w, h)
			var saveScaled = url => {
				var id = (prefix || "") + filename
				let img2 = document.createElement("img")
				pageEvents.load(img2).then(() => {
					assets.image[id] = img2
					this.assetsDiv.appendChild(img2)
					resolve(img2)
				}, reject)
				img2.id = id
				img2.src = url
			}
			if("toBlob" in canvas){
				canvas.toBlob(blob => {
					saveScaled(URL.createObjectURL(blob))
				})
			}else{
				saveScaled(canvas.toDataURL())
			}
		})
	}
	getImageScale(force){
		var scale = 1
		if(typeof settings !== "undefined" && settings){
			var resolution = settings.getItem("resolution")
			if(resolution === "medium"){
				scale = 0.75
			}else if(resolution === "low"){
				scale = 0.5
			}else if(resolution === "lowest"){
				scale = 0.25
			}
		}
		if(force && scale > 0.5){
			scale = 0.5
		}
		return scale
	}
	startBackgroundPreload(force){
		if(this.backgroundPreloadStarted && !force){
			return
		}
		this.backgroundPreloadStarted = true
		this.preloadGameImages()
		this.preloadComboVoices()
		assets.audioMusic.forEach(name => {
			this.addBackgroundTask(() => this.loadSound(name, snd.musicGain), this.soundUrl(name))
		})
	}
	preloadComboVoices(){
		var names = ["v_combo_50.ogg"]
		for(var combo = 100; combo <= 5000; combo += 100){
			names.push("v_combo_" + combo + ".ogg")
		}
		names.forEach(name => {
			var id = this.getFilename(name)
			this.addBackgroundTask(() => this.loadSound(name, snd.sfxGain).then(() => {
				if(!assets.sounds[id + "_p1"]){
					assets.sounds[id + "_p1"] = assets.sounds[id].copy(snd.sfxGainL)
				}
				if(!assets.sounds[id + "_p2"]){
					assets.sounds[id + "_p2"] = assets.sounds[id].copy(snd.sfxGainR)
				}
			}), this.soundUrl(name))
		})
	}
	preloadGameImages(){
		var names = []
		for(var i = 1; i <= 5; i++){
			names.push("bg_song_" + i + "a", "bg_song_" + i + "b")
		}
		for(var i = 1; i <= 3; i++){
			names.push("bg_stage_" + i)
		}
		for(var i = 1; i <= 6; i++){
			names.push("bg_don_" + i + "a", "bg_don_" + i + "b", "bg_don2_" + i + "a", "bg_don2_" + i + "b")
		}
		names.push("touch_drum", "results_flowers", "results_mikoshi", "results_tetsuohana", "results_tetsuohana2")
		var touch = /Android|iPhone|iPad/.test(navigator.userAgent)
		names.forEach(name => {
			var url = gameConfig.assets_baseurl + "img/" + name + ".png"
			this.addBackgroundTask(() => this.loadScaledImage(name, url, {
				force: touch && name.startsWith("bg_song_")
			}), url)
		})
	}
	getFilename(name){
		return name.slice(0, name.lastIndexOf("."))
	}
	errorMsg(error, url){
		var detail = this.normalizeResourceError(error, {
			url: url,
			stage: this.currentStage || "boot-minimal",
			resourceType: this.inferResourceType(url),
			critical: true
		})
		this.showBootError([detail])
		console.error(error || detail)
		return Promise.reject(detail)
	}
	assetLoaded(){
		if(!this.error){
			this.loadedAssets++
			var total = Math.max(1, this.totalAssets + (this.afterJSCount || 0))
			var percentage = Math.min(100, Math.floor(this.loadedAssets * 100 / total))
			if(this.loaderProgress){
				this.loaderProgress.style.width = percentage + "%"
			}
			if(this.loaderPercentage && this.loaderPercentage.firstChild){
				this.loaderPercentage.firstChild.data = percentage + "%"
			}
			this.updateLoaderStatus()
		}
	}
	updateLoaderStatus(resource){
		if(this.loaderStatusText){
			this.loaderStatusText.textContent = resource && resource.url ? "Loading: " + resource.url : "Loading"
		}
		if(this.loaderStage){
			this.loaderStage.textContent = "Stage: " + (this.currentStageLabel || this.currentStage || "Boot Minimal")
		}
		if(this.loaderCount){
			var total = Math.max(1, this.totalAssets + (this.afterJSCount || 0))
			this.loaderCount.textContent = "Progress: " + this.loadedAssets + " / " + total
		}
		if(this.loaderFailed){
			this.loaderFailed.textContent = "Failed: " + this.failedResources.length
		}
		if(this.loaderRetry){
			if(this.retryingResource){
				this.loaderRetry.style.display = "block"
				this.loaderRetry.textContent = "Retrying: " + this.retryingResource.url + " (" + this.retryingResource.attempt + " / " + this.retryingResource.retries + ")"
			}else{
				this.loaderRetry.style.display = "none"
				this.loaderRetry.textContent = ""
			}
		}
	}
	changePage(name, patternBg){
		this.pageName = name
		this.screen.innerHTML = assets.pages[name]
		this.screen.classList[patternBg ? "add" : "remove"]("pattern-bg")
	}
	cssRuleset(rulesets){
		var css = []
		for(var selector in rulesets){
			var declarationsObj = rulesets[selector]
			var declarations = []
			for(var property in declarationsObj){
				var value = declarationsObj[property]
				declarations.push("\t" + property + ": " + value + ";")
			}
			css.push(selector + "{\n" + declarations.join("\n") + "\n}")
		}
		return css.join("\n")
	}
	ajax(url, customRequest, customResponse, retryOptions){
		retryOptions = retryOptions || {}
		var type = "text"
		if(customRequest){
			var reqStub = {}
			customRequest(reqStub)
			if(reqStub.responseType){
				type = reqStub.responseType
			}
		}
		if(!customResponse && (url.startsWith("src/") || url.startsWith("assets/") || url.indexOf("img/") !== -1 || url.indexOf("audio/") !== -1 || url.indexOf("fonts/") !== -1 || url.indexOf("views/") !== -1)){
			return this.workerFetch(url, type, Object.assign({
				resourceType: this.inferResourceType(url)
			}, retryOptions))
		}
		if(!customResponse){
			return this.fetchWithRetry(url, Object.assign({
				resourceType: this.inferResourceType(url),
				responseType: type
			}, retryOptions))
		}
		var request = new XMLHttpRequest()
		request.open("GET", url)
		request.timeout = this.getRetryOptions(retryOptions).timeout
		var promise = pageEvents.load(request)
		if(customRequest){
			customRequest(request)
		}
		request.send()
		return promise
	}
	loadScript(url){
		var url = url + this.queryString
		return this.workerFetch(url, "text", {
			resourceType: "javascript"
		}).then(code => {
			var script = document.createElement("script")
			code += "\n//# sourceURL=" + url
			script.text = code
			document.head.appendChild(script)
		})
	}
	getCsrfToken(){
		return this.ajax("api/csrftoken").then(response => {
			var json = JSON.parse(response)
			if(json.status === "ok"){
				return Promise.resolve(json.token)
			}else{
				return Promise.reject()
			}
		})
	}
	clean(error){
		if(!error && this.loaderDiv){
			this.loaderDiv.classList.add("loader-fade-out")
		}
		delete this.loaderDiv
		delete this.loaderPercentage
		delete this.loaderProgress
		delete this.loaderStatusText
		delete this.loaderStage
		delete this.loaderCount
		delete this.loaderFailed
		delete this.loaderSpeed
		delete this.loaderRetry
		clearInterval(this.downloadSpeedTimer)
		this.downloadSpeedTimer = null
		if(!error){
			delete this.promises
			delete this.errorText
		}
		if(typeof root !== "undefined"){
			pageEvents.remove(root, "touchstart")
		}
	}
}
