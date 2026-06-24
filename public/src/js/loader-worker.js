function sleep(ms){
	return new Promise(resolve => setTimeout(resolve, ms))
}

function waitForNetworkRetry(delay){
	if(self.navigator && self.navigator.onLine !== false){
		return sleep(delay)
	}
	return new Promise(resolve => {
		var done = () => {
			clearTimeout(timer)
			self.removeEventListener("online", done)
			resolve()
		}
		var timer = setTimeout(done, delay)
		self.addEventListener("online", done, {
			once: true
		})
	})
}

async function fetchWithRetry(url, options, onRetry, consumeResponse){
	options = options || {}
	var retries = options.retries == null ? 3 : options.retries
	var timeout = options.timeout || 12000
	var baseDelay = options.baseDelay || 500
	var maxDelay = options.maxDelay || 5000
	var jitter = options.jitter == null ? 300 : options.jitter
	var retryOnStatus = options.retryOnStatus || [408, 425, 429, 500, 502, 503, 504]
	var lastError = null
	for(var attempt = 0; attempt <= retries; attempt++){
		var controller = new AbortController()
		var timer = setTimeout(() => controller.abort(), timeout)
		var startedAt = Date.now()
		try{
			var response = await fetch(url, {
				signal: controller.signal,
				cache: options.cache || "default"
			})
			if(!response.ok){
				var httpError = new Error("HTTP " + response.status + " " + response.statusText)
				httpError.status = response.status
				throw httpError
			}
			var result = consumeResponse ? await consumeResponse(response) : response
			clearTimeout(timer)
			return result
		}catch(error){
			clearTimeout(timer)
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
			await waitForNetworkRetry(delay)
		}
	}
	var finalError = new Error("Failed to fetch resource after " + (retries + 1) + " attempts: " + url)
	finalError.code = "RESOURCE_FETCH_FAILED"
	finalError.detail = lastError
	throw finalError
}

async function readResponse(response, id, type){
	var total = Number(response.headers.get("content-length")) || 0
	if(!response.body || !response.body.getReader){
		var fallback
		if(type === "arraybuffer"){
			fallback = await response.arrayBuffer()
		}else if(type === "blob"){
			fallback = await response.blob()
		}else{
			fallback = await response.text()
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
		var result = await reader.read()
		if(result.done){
			break
		}
		chunks.push(result.value)
		loaded += result.value.byteLength
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
	const { id, url, type, options } = e.data
	try{
		const result = await fetchWithRetry(url, options, retry => {
			self.postMessage(Object.assign({
				id: id,
				retry: true
			}, retry))
		}, response => readResponse(response, id, type))
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
	}
})
