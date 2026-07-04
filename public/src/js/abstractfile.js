function readFile(file, arrayBuffer, encoding){
	var reader = new FileReader()
	var promise = pageEvents.load(reader).then(event => event.target.result)
	reader[arrayBuffer ? "readAsArrayBuffer" : "readAsText"](file, encoding)
	return promise
}
function filePermission(file){
	return file.queryPermission().then(response => {
		if(response === "granted"){
			return file
		}else{
			return file.requestPermission().then(response => {
				if(response === "granted"){
					return file
				}else{
					return Promise.reject(strings.accessNotGrantedError)
				}
			})
		}
	})
}
class RemoteFile{
	constructor(...args){
		this.init(...args)
	}
	init(url){
		this.url = url
		try{
			this.path = new URL(url).pathname
		}catch(e){
			this.path = url
		}
		if(this.path.startsWith("/")){
			this.path = this.path.slice(1)
		}
		if(this.url.startsWith("data:")){
			this.name = "datauri"
			if(this.url.startsWith("data:audio/ogg")){
				this.name += ".ogg"
			}
		}else{
			this.name = this.path
			var index = this.name.lastIndexOf("/")
			if(index !== -1){
				this.name = this.name.slice(index + 1)
			}
		}
	}
	arrayBuffer(loadOptions){
		return loader.ajax(this.url, request => {
			request.responseType = "arraybuffer"
		}, null, loadOptions).catch(error => {
			if(!this.shouldRetryArrayBufferOnMainThread(error)){
				return Promise.reject(error)
			}
			return loader.fetchWithRetry(this.url, Object.assign({}, loadOptions || {}, {
				resourceType: loader.inferResourceType(this.url),
				responseType: "arraybuffer",
				fetchOptions: Object.assign({
					cache: "reload"
				}, loadOptions && loadOptions.fetchOptions || {})
			}))
		})
	}
	shouldRetryArrayBufferOnMainThread(error){
		if(this.isCancelError(error)){
			return false
		}
		var detail = error && error.detail || {}
		var code = error && error.code || detail.code
		var status = error && error.status || detail.status
		if(status >= 400 && status < 500 && [408, 425, 429].indexOf(status) === -1){
			return false
		}
		if(code === "RESOURCE_FETCH_FAILED" || code === "WORKER_STALLED" || code === "WORKER_CRASHED" || code === "WORKER_MESSAGE_ERROR"){
			return true
		}
		var name = error && error.name || detail.name || ""
		var message = error && error.message || detail.message || ""
		return !status && /AbortError|NetworkError|Failed to fetch|Load failed|resource worker/i.test(name + " " + message)
	}
	isCancelError(error){
		return error === "cancel" || error && error.code === "RESOURCE_CANCELLED" || Array.isArray(error) && this.isCancelError(error[0])
	}
	read(encoding, loadOptions){
		if(encoding){
			return this.blob(loadOptions).then(blob => readFile(blob, false, encoding))
		}else{
			return loader.ajax(this.url, null, null, loadOptions)
		}
	}
	blob(loadOptions){
		return loader.ajax(this.url, request => {
			request.responseType = "blob"
		}, null, loadOptions)
	}
}
class LocalFile{
	constructor(...args){
		this.init(...args)
	}
	init(file, path){
		this.file = file
		this.path = path || file.webkitRelativePath
		this.url = this.path
		this.name = file.name
	}
	arrayBuffer(loadOptions){
		return readFile(this.file, true)
	}
	read(encoding, loadOptions){
		return readFile(this.file, false, encoding)
	}
	blob(loadOptions){
		return Promise.resolve(this.file)
	}
}
class FilesystemFile{
	constructor(...args){
		this.init(...args)
	}
	init(file, path){
		this.file = file
		this.path = path
		this.url = this.path
		this.name = file.name
	}
	arrayBuffer(loadOptions){
		return this.blob(loadOptions).then(blob => blob.arrayBuffer())
	}
	read(encoding, loadOptions){
		return this.blob(loadOptions).then(blob => readFile(blob, false, encoding))
	}
	blob(loadOptions){
		return filePermission(this.file).then(file => file.getFile())
	}
}
class GdriveFile{
	constructor(...args){
		this.init(...args)
	}
	init(fileObj){
		this.path = fileObj.path
		this.name = fileObj.name
		this.id = fileObj.id
		this.url = gpicker.filesUrl + this.id + "?alt=media"
	}
	arrayBuffer(loadOptions){
		return gpicker.downloadFile(this.id, "arraybuffer")
	}
	read(encoding, loadOptions){
		if(encoding){
			return this.blob(loadOptions).then(blob => readFile(blob, false, encoding))
		}else{
			return gpicker.downloadFile(this.id)
		}
	}
	blob(loadOptions){
		return gpicker.downloadFile(this.id, "blob")
	}
}
class CachedFile{
	constructor(...args){
		this.init(...args)
	}
	init(contents, oldFile){
		this.contents = contents
		this.oldFile = oldFile
		this.path = oldFile.path
		this.name = oldFile.name
		this.url = oldFile.url
	}
	arrayBuffer(loadOptions){
		return Promise.resolve(this.contents)
	}
	read(encoding, loadOptions){
		return this.arrayBuffer()
	}
	blob(loadOptions){
		return this.arrayBuffer()
	}
}
