function sleep(ms){
	return new Promise(resolve => setTimeout(resolve, ms))
}

var activeControllers = {}
var retryCancelHandlers = {}
var cancelledTasks = {}

function createCancelError(url){
	var error = new Error("cancel")
	error.code = "RESOURCE_CANCELLED"
	error.detail = {
		url: url
	}
	return error
}

function isCancelled(id){
	return !!cancelledTasks[id]
}

function cancelTask(id){
	cancelledTasks[id] = true
	if(activeControllers[id]){
		activeControllers[id].abort()
	}
	if(retryCancelHandlers[id]){
		retryCancelHandlers[id]()
	}
}

function waitForNetworkRetry(delay, id, url){
	if(isCancelled(id)){
		return Promise.reject(createCancelError(url))
	}
	if(self.navigator && self.navigator.onLine !== false){
		return new Promise((resolve, reject) => {
			var timer = setTimeout(done, delay)
			function done(){
				delete retryCancelHandlers[id]
				resolve()
			}
			retryCancelHandlers[id] = () => {
				clearTimeout(timer)
				delete retryCancelHandlers[id]
				reject(createCancelError(url))
			}
		})
	}
	return new Promise((resolve, reject) => {
		var done = () => {
			clearTimeout(timer)
			self.removeEventListener("online", done)
			delete retryCancelHandlers[id]
			resolve()
		}
		var timer = setTimeout(done, delay)
		retryCancelHandlers[id] = () => {
			clearTimeout(timer)
			self.removeEventListener("online", done)
			delete retryCancelHandlers[id]
			reject(createCancelError(url))
		}
		self.addEventListener("online", done, {
			once: true
		})
	})
}

async function fetchWithRetry(id, url, options, onRetry, consumeResponse){
	options = options || {}
	var retries = options.retries == null ? 3 : options.retries
	var timeout = options.timeout || 12000
	var baseDelay = options.baseDelay || 500
	var maxDelay = options.maxDelay || 5000
	var jitter = options.jitter == null ? 300 : options.jitter
	var retryOnStatus = options.retryOnStatus || [408, 425, 429, 500, 502, 503, 504]
	var lastError = null
	for(var attempt = 0; attempt <= retries; attempt++){
		if(isCancelled(id)){
			throw createCancelError(url)
		}
		var controller = new AbortController()
		activeControllers[id] = controller
		var timer = null
		var refreshTimeout = () => {
			clearTimeout(timer)
			timer = setTimeout(() => controller.abort(), timeout)
		}
		var clearRequestTimeout = () => clearTimeout(timer)
		refreshTimeout()
		var startedAt = Date.now()
		try{
			var response = await fetch(url, {
				signal: controller.signal,
				cache: options.cache || "default"
			})
			if(isCancelled(id)){
				throw createCancelError(url)
			}
			if(!response.ok){
				var httpError = new Error("HTTP " + response.status + " " + response.statusText)
				httpError.status = response.status
				throw httpError
			}
			var result = consumeResponse ? await consumeResponse(response, refreshTimeout, clearRequestTimeout) : response
			clearRequestTimeout()
			delete activeControllers[id]
			if(isCancelled(id)){
				throw createCancelError(url)
			}
			return result
		}catch(error){
			clearRequestTimeout()
			delete activeControllers[id]
			if(isCancelled(id) || error && error.code === "RESOURCE_CANCELLED"){
				throw createCancelError(url)
			}
			lastError = {
				message: error && error.message || String(error),
				name: error && error.name || "Error",
				status: error && error.status || null,
				url: url,
				attempt: attempt,
				retries: retries,
				duration: Date.now() - startedAt
			}
			var retryableStatus = !lastError.status || retryOnStatus.indexOf(lastError.status) !== -1
			if(attempt >= retries || !retryableStatus){
				break
			}
			var delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay) + Math.floor(Math.random() * jitter)
			if(onRetry){
				onRetry({
					attempt: attempt + 2,
					retries: retries + 1,
					delay: delay,
					loaded: 0,
					total: 0
				})
			}
			await waitForNetworkRetry(delay, id, url)
		}
	}
	var finalError = new Error("Failed to fetch resource after " + (retries + 1) + " attempts: " + url)
	finalError.code = "RESOURCE_FETCH_FAILED"
	finalError.detail = lastError
	throw finalError
}

async function readResponse(response, id, type, refreshTimeout, clearRequestTimeout){
	var total = Number(response.headers.get("content-length")) || 0
	if(!response.body || !response.body.getReader){
		var fallback
		if(clearRequestTimeout){
			clearRequestTimeout()
		}
		if(type === "arraybuffer"){
			fallback = await response.arrayBuffer()
		}else if(type === "blob"){
			fallback = await response.blob()
		}else{
			fallback = await response.text()
		}
		if(isCancelled(id)){
			throw createCancelError(response.url)
		}
		var loaded = fallback.byteLength || fallback.size || new TextEncoder().encode(fallback).byteLength
		self.postMessage({
			id: id,
			progress: true,
			loaded: loaded,
			total: total || loaded
		})
		return {
			data: fallback,
			loaded: loaded,
			total: total || loaded
		}
	}

	var reader = response.body.getReader()
	var chunks = []
	var loaded = 0
	while(true){
		if(isCancelled(id)){
			throw createCancelError(response.url)
		}
		if(refreshTimeout){
			refreshTimeout()
		}
		var result = await reader.read()
		if(result.done){
			break
		}
		chunks.push(result.value)
		loaded += result.value.byteLength
		if(refreshTimeout){
			refreshTimeout()
		}
		self.postMessage({
			id: id,
			progress: true,
			loaded: loaded,
			total: total
		})
	}

	var data
	if(type === "blob"){
		data = new Blob(chunks, {
			type: response.headers.get("content-type") || "application/octet-stream"
		})
	}else{
		var bytes = new Uint8Array(loaded)
		var offset = 0
		for(var chunk of chunks){
			bytes.set(chunk, offset)
			offset += chunk.byteLength
		}
		if(type === "arraybuffer"){
			data = bytes.buffer
		}else{
			data = new TextDecoder().decode(bytes)
		}
	}
	return {
		data: data,
		loaded: loaded,
		total: total || loaded
	}
}

self.addEventListener('message', async e => {
	if(e.data && e.data.cancel){
		cancelTask(e.data.id)
		return
	}
	const { id, url, type, options } = e.data
	delete cancelledTasks[id]
	try{
		const result = await fetchWithRetry(id, url, options, retry => {
			self.postMessage(Object.assign({
				id: id,
				retry: true
			}, retry))
		}, (response, refreshTimeout, clearRequestTimeout) => readResponse(response, id, type, refreshTimeout, clearRequestTimeout))
		self.postMessage({
			id: id,
			data: result.data,
			loaded: result.loaded,
			total: result.total
		}, type === "arraybuffer" ? [result.data] : undefined)
	}catch(e){
		self.postMessage({
			id: id,
			error: {
				message: e && e.message || e.toString(),
				code: e && e.code,
				detail: e && e.detail
			}
		})
	}finally{
		delete activeControllers[id]
		delete retryCancelHandlers[id]
		delete cancelledTasks[id]
	}
})
