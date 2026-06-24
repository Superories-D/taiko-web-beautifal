class Search{
	constructor(...args){
		this.init(...args)
	}
	init(songSelect){
		this.songSelect = songSelect
		this.opened = false
		this.enabled = true
		this.filterAliases = {
			easy: "easy", "\u304b\u3093\u305f\u3093": "easy", "\u7b80\u5355": "easy", "\u7c21\u55ae": "easy", "\uc26c\uc6c0": "easy",
			normal: "normal", "\u3075\u3064\u3046": "normal", "\u666e\u901a": "normal", "\ubcf4\ud1b5": "normal",
			hard: "hard", "\u3080\u305a\u304b\u3057\u3044": "hard", "\u56f0\u96be": "hard", "\u56f0\u96e3": "hard", "\uc5b4\ub824\uc6c0": "hard",
			oni: "oni", extreme: "oni", "\u304a\u306b": "oni", "\u9b54\u738b": "oni", "\u9b3c": "oni", "\uadc0\uc2e0": "oni",
			ura: "ura", "\u88cf": "ura",
			clear: "clear", "\u901a\u5173": "clear", "\u901a\u95dc": "clear", "\u30af\u30ea\u30a2": "clear",
			silver: "silver", "\u94f6": "silver", "\u9280": "silver",
			gold: "gold", "\u91d1": "gold",
			genre: "genre", category: "genre", "\u7c7b\u578b": "genre", "\u985e\u578b": "genre", "\u30b8\u30e3\u30f3\u30eb": "genre",
			lyrics: "lyrics", lyric: "lyrics", "\u6b4c\u8bcd": "lyrics", "\u6b4c\u8a5e": "lyrics",
			creative: "creative", "\u521b\u4f5c": "creative", "\u5275\u4f5c": "creative",
			played: "played", "\u5df2\u73a9": "played", "\u5df2\u904a\u73a9": "played",
			maker: "maker", creator: "maker", author: "maker", "\u5236\u4f5c\u8005": "maker", "\u88fd\u4f5c\u8005": "maker",
			diverge: "diverge", branch: "diverge", "\u5206\u6b67": "diverge",
			random: "random", "\u968f\u673a": "random", "\u96a8\u6a5f": "random",
			all: "all", "\u5168\u90e8": "all"
		}
		this.valueAliases = {
			yes: "yes", y: "yes", true: "yes", "1": "yes", "\u662f": "yes", "\u6709": "yes", "\u3042\u308a": "yes", "\ub124": "yes",
			no: "no", n: "no", false: "no", "0": "no", "\u5426": "no", "\u65e0": "no", "\u7121": "no", "\u306a\u3057": "no", "\uc544\ub2c8\uc694": "no",
			any: "any", "\u4efb\u610f": "any", "\u4efb\u4f55": "any", "\u3059\u3079\u3066": "any", "\u5168\u90e8": "any"
		}
		this.style = document.createElement("style")
		var css = []
		for(var i in this.songSelect.songSkin){
			var skin = this.songSelect.songSkin[i]
			if("id" in skin || i === "default"){
				var id = "id" in skin ? ("cat" + skin.id) : i
				
				css.push(loader.cssRuleset({
					[".song-search-" + id]: {
						"background-color": skin.background
					},
					[".song-search-" + id + "::before"]: {
						"border-color": skin.border[0],
						"border-bottom-color": skin.border[1],
						"border-right-color": skin.border[1]
					},
					[".song-search-" + id + " .song-search-result-title::before, .song-search-" + id + " .song-search-result-subtitle::before"]: {
						"-webkit-text-stroke-color": skin.outline
					}
				}))
			}
		}
		this.style.appendChild(document.createTextNode(css.join("\n")))
		loader.screen.appendChild(this.style)
	}

	normalizeString(string){
		string = (string || "")
			.replace(/[\u2018\u2019]/g, "'")
			.replace(/[\u201c\u201d]/g, '"')
			.replace(/[\u3002\uff0e]/g, ".")
			.replace(/[\uff0c\u3001]/g, ",")
			.replace(/\uff1a/g, ":")
			.replace(/\u3000/g, " ")

		kanaPairs.forEach(pair => {
			string = string.replace(pair[1], pair[0])
		})

		return string.normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
	}

	normalizeToken(string){
		return this.normalizeString(string).trim().toLowerCase()
	}

	getFilterName(name){
		return this.filterAliases[this.normalizeToken(name)]
	}

	getFilterValue(value){
		var normalized = this.normalizeToken(value)
		return this.valueAliases[normalized] || normalized
	}

	getCategoryAliases(cat){
		var aliases = []
		if(cat.title){
			aliases.push(cat.title)
		}
		if(cat.aliases){
			aliases = aliases.concat(cat.aliases)
		}
		if(cat.title_lang){
			Object.keys(cat.title_lang).forEach(lang => {
				if(cat.title_lang[lang]){
					aliases.push(cat.title_lang[lang])
				}
			})
		}
		return aliases.map(alias => this.normalizeToken(alias))
	}

	getTextAliases(text, textLang){
		var aliases = []
		var addAlias = value => {
			if(value && aliases.indexOf(value) === -1){
				aliases.push(value)
			}
		}
		addAlias(text)
		if(textLang){
			Object.keys(textLang).forEach(lang => {
				addAlias(textLang[lang])
			})
		}
		return aliases
	}

	prepareSearchText(text){
		text = this.normalizeString(text || "")
		return text ? fuzzysort.prepare(text) : null
	}

	prepareSearchAliases(aliases){
		var normalized = []
		aliases.forEach(alias => {
			alias = this.normalizeString(alias || "")
			if(alias && normalized.indexOf(alias) === -1){
				normalized.push(alias)
			}
		})
		return normalized.length ? fuzzysort.prepare(normalized.join("\n")) : null
	}

	getSearchScore(result, query, penalty=0){
		if(!result){
			return -Infinity
		}

		var score = result.score + penalty
		result.ranges = this.indexesToRanges(result.indexes)
		if(result.indexes.length > 1){
			var rangeAmount = result.ranges.length
			var lastIdx = -3
			result.ranges.forEach(range => {
				if(range[0] - lastIdx <= 2){
					rangeAmount--
					score -= 1000
				}
				lastIdx = range[1]
			})
			var index = result.target.toLowerCase().indexOf(query.toLowerCase())
			if(index !== -1){
				result.ranges = [[index, index + query.length - 1]]
			}else if(rangeAmount > result.indexes.length / 2){
				score = -Infinity
				result.ranges = null
			}else if(rangeAmount !== 1){
				score -= 9000
			}
		}
		return score
	}
	
	perform(query){
		var results = []
		var filters = {}
		
		var querySplit = query.split(" ").filter(word => {
			if(word.length > 0){
				var parts = word.split(":")
				if(parts.length > 1){
					var filter = this.getFilterName(parts[0])
					var value = this.getFilterValue(parts.slice(1).join(":"))
					switch(filter){
						case "easy":
						case "normal":
						case "hard":
						case "oni":
						case "ura":
							var range = this.parseRange(value)
							if(range){
								filters[filter] = range
							}
							break
						case "extreme":
							var range = this.parseRange(value)
							if(range){
								filters.oni = range
							}
							break
						case "clear":
						case "silver":
						case "gold":
						case "genre":
						case "lyrics":
						case "creative":
						case "played":
						case "maker":
						case "diverge":
						case "random":
						case "all":
							filters[filter] = value
							break
						default:
							return true
					}
					return false
				}
			}
			return true
		})
		
		query = this.normalizeString(querySplit.join(" ").trim())
		
		var totalFilters = Object.keys(filters).length
		var random = false
		var allResults = false
		for(var i = 0; i < assets.songs.length; i++){
			var song = assets.songs[i]
			var passedFilters = 0
			
			Object.keys(filters).forEach(filter => {
				var value = filters[filter]
				switch(filter){
					case "easy":
					case "normal":
					case "hard":
					case "oni":
					case "ura":
						if(song.courses[filter] && song.courses[filter].stars >= value.min && song.courses[filter].stars <= value.max){
							passedFilters++
						}
						break
					case "clear":
					case "silver":
					case "gold":
						if(value === "any"){
							var score = scoreStorage.scores[song.hash]
							scoreStorage.difficulty.forEach(difficulty => {
								if(score && score[difficulty] && score[difficulty].crown && (filter === "clear" || score[difficulty].crown === filter)){
									passedFilters++
								}
							})
						} else {
							var score = scoreStorage.scores[song.hash]
							if(score && score[value] && score[value].crown && (filter === "clear" || score[value].crown === filter)){
								passedFilters++
							}
						}
						break
					case "played":
						var score = scoreStorage.scores[song.hash]
						if((value === "yes" && score) || (value === "no" && !score)){
							passedFilters++
						}
						break
					case "lyrics":
						if((value === "yes" && song.lyrics) || (value === "no" && !song.lyrics)){
							passedFilters++
						}
						break
					case "creative":
						if((value === "yes" && song.maker) || (value === "no" && !song.maker)){
							passedFilters++
						}
						break
					case "maker":
						if(song.maker && song.maker.name.toLowerCase().includes(value.toLowerCase())){
							passedFilters++
						}
						break
					case "genre":
						var cat = assets.categories.find(cat => cat.id === song.category_id)
						var aliases = cat ? this.getCategoryAliases(cat) : []
						
						if(aliases.find(alias => alias === this.normalizeToken(value))){
							passedFilters++
						}
						break
					case "diverge":
						var branch = Object.values(song.courses).find(course => course && course.branch)
						if((value === "yes" && branch) || (value === "no" && !branch)){
							passedFilters++
						}
						break
					case "random":
						if(value === "yes" || value === "no"){
							random = value === "yes"
							passedFilters++
						}
						break
					case "all":
						if(value === "yes" || value === "no"){
							allResults = value === "yes"
							passedFilters++
						}
						break
				}
			})
			
			if(passedFilters === totalFilters){
				results.push(song)
			}
		}
		
		var maxResults = allResults ? Infinity : (totalFilters > 0 && !query ? 100 : 50)
		
		if(query){
			results = fuzzysort.go(query, results, {
				keys: ["titlePrepared", "subtitlePrepared", "titleSearchPrepared", "subtitleSearchPrepared"],
				allowTypo: true,
				limit: maxResults,
				scoreFn: a => {
					var scores = [
						this.getSearchScore(a[0], query),
						this.getSearchScore(a[1], query, -1000),
						this.getSearchScore(a[2], query, -500),
						this.getSearchScore(a[3], query, -1500)
					]
					if(random){
						var rand = Math.random() * -9000
						for(var i = 0; i < scores.length; i++){
							if(scores[i] !== -Infinity){
								scores[i] = rand
							}
						}
					}
					return Math.max.apply(null, scores)
				}
			})
		}else{
			if(random){
				for(var i = results.length - 1; i > 0; i--){
					var j = Math.floor(Math.random() * (i + 1))
					var temp = results[i]
					results[i] = results[j]
					results[j] = temp
				}
			}
			results = results.slice(0, maxResults).map(result => {
				return {obj: result}
			})
		}
		
		return results
	}
	
	createResult(result, resultWidth, fontSize){
		var song = result.obj
		var title = this.songSelect.getLocalTitle(song.title, song.title_lang)
		var subtitle = this.songSelect.getLocalTitle(title === song.title ? song.subtitle : "", song.subtitle_lang)
		
		var id = "default"
		if(song.category_id){
			var cat = assets.categories.find(cat => cat.id === song.category_id)
			if(cat && "id" in cat){
				id = "cat" + cat.id
			}
		}
		
		var resultDiv = document.createElement("div")
		resultDiv.classList.add("song-search-result", "song-search-" + id)
		resultDiv.dataset.songId = song.id
		
		var resultInfoDiv = document.createElement("div")
		resultInfoDiv.classList.add("song-search-result-info")
		var resultInfoTitle = document.createElement("span")
		resultInfoTitle.classList.add("song-search-result-title")
		resultInfoTitle.style.fontFamily = strings.songFont || songTitleFont
		
		resultInfoTitle.appendChild(this.highlightResult(title, result[0]))
		resultInfoTitle.setAttribute("alt", title)
		
		resultInfoDiv.appendChild(resultInfoTitle)
		
		if(subtitle){
			resultInfoDiv.appendChild(document.createElement("br"))
			var resultInfoSubtitle = document.createElement("span")
			resultInfoSubtitle.classList.add("song-search-result-subtitle")
			resultInfoSubtitle.style.fontFamily = strings.font
			
			resultInfoSubtitle.appendChild(this.highlightResult(subtitle, result[1]))
			resultInfoSubtitle.setAttribute("alt", subtitle)
			
			resultInfoDiv.appendChild(resultInfoSubtitle)
		}
		
		resultDiv.appendChild(resultInfoDiv)
		
		var courses = ["easy", "normal", "hard", "oni", "ura"]
		courses.forEach(course => {
			var courseDiv = document.createElement("div")
			courseDiv.classList.add("song-search-result-course", "song-search-result-" + course)
			if (song.courses[course]) {
				var crown = "noclear"
				if (scoreStorage.scores[song.hash]) {
					if (scoreStorage.scores[song.hash][course]) {
						crown = scoreStorage.scores[song.hash][course].crown || "noclear"
					}
				}
				var courseCrown = document.createElement("div")
				courseCrown.classList.add("song-search-result-crown", "song-search-result-" + crown)
				var courseStars = document.createElement("div")
				courseStars.classList.add("song-search-result-stars")
				courseStars.innerText = song.courses[course].stars + "\u2605"
				
				courseDiv.appendChild(courseCrown)
				courseDiv.appendChild(courseStars)
			} else {
				courseDiv.classList.add("song-search-result-hidden")
			}
			
			resultDiv.appendChild(courseDiv)
		})
		
		this.songSelect.ctx.font = (1.2 * fontSize) + "px " + (strings.songFont || songTitleFont)
		var titleWidth = this.songSelect.ctx.measureText(title).width
		var titleRatio = resultWidth / titleWidth
		if(titleRatio < 1){
			resultInfoTitle.style.transform = "scale(" + titleRatio + ", 1)"
		}
		if(subtitle){
			this.songSelect.ctx.font =  (0.8 * 1.2 * fontSize) + "px " + strings.font
			var subtitleWidth = this.songSelect.ctx.measureText(subtitle).width
			var subtitleRatio = resultWidth / subtitleWidth
			if(subtitleRatio < 1){
				resultInfoSubtitle.style.transform = "scale(" + subtitleRatio + ", 1)"
			}
		}
		
		return resultDiv
	}
	
	highlightResult(text, result){
		var fragment = document.createDocumentFragment()
		var ranges = (result ? result.ranges : null) || []
		var lastIdx = 0
		ranges.forEach(range => {
			if(lastIdx !== range[0]){
				fragment.appendChild(document.createTextNode(text.slice(lastIdx, range[0])))
			}
			var span = document.createElement("span")
			span.classList.add("highlighted-text")
			span.innerText = text.slice(range[0], range[1] + 1)
			fragment.appendChild(span)
			lastIdx = range[1] + 1
		})
		if(text.length !== lastIdx){
			fragment.appendChild(document.createTextNode(text.slice(lastIdx)))
		}
		return fragment
	}
	
	setActive(idx){
		this.songSelect.playSound("se_ka")
		var active = this.div.querySelector(":scope .song-search-result-active")
		if(active){
			active.classList.remove("song-search-result-active")
		}
		
		if(idx === null){
			this.active = null
			return
		}
		
		var el = this.results[idx]
		this.input.blur()
		el.classList.add("song-search-result-active")
		this.scrollTo(el)
		
		this.active = idx
	}
	
	display(fromButton=false){
		if(!this.enabled){
			return
		}
		if(this.opened){
			return this.remove(true)
		}
		
		this.opened = true
		this.results = []
		this.div = document.createElement("div")
		this.div.innerHTML = assets.pages["search"]
		
		this.container = this.div.querySelector(":scope #song-search-container")
		if(this.touchEnabled){
			this.container.classList.add("touch-enabled")
		}
		pageEvents.add(this.container, ["mousedown", "touchstart"], this.onClick.bind(this))
		
		this.input = this.div.querySelector(":scope #song-search-input")
		this.input.setAttribute("placeholder", strings.search.searchInput)
		pageEvents.add(this.input, ["input"], () => this.onInput())
		
		this.songSelect.playSound("se_pause")
		loader.screen.appendChild(this.div)
		this.setTip()
		cancelTouch = false
		noResizeRoot = true
		if(this.songSelect.songs[this.songSelect.selectedSong].courses){
			snd.previewGain.setVolumeMul(0.5)
		}else if(this.songSelect.bgmEnabled){
			snd.musicGain.setVolumeMul(0.5)
		}
		
		setTimeout(() => {
			this.input.focus()
			this.input.setSelectionRange(0, this.input.value.length)
		}, 10)
		
		var lastQuery = localStorage.getItem("lastSearchQuery")
		if(lastQuery){
			this.input.value = lastQuery
			this.input.dispatchEvent(new Event("input", {
				value: lastQuery
			}))
		}
	}
	
	remove(byUser=false){
		if(this.opened){
			this.opened = false
			if(byUser){
				this.songSelect.playSound("se_cancel")
			}
			
			pageEvents.remove(this.div.querySelector(":scope #song-search-container"),
			["mousedown", "touchstart"])
			pageEvents.remove(this.input, ["input"])
			
			this.div.remove()
			delete this.results
			delete this.div
			delete this.input
			delete this.tip
			delete this.active
			cancelTouch = true
			noResizeRoot = false
			if(this.songSelect.songs[this.songSelect.selectedSong].courses){
				snd.previewGain.setVolumeMul(1)
			}else if(this.songSelect.bgmEnabled){
				snd.musicGain.setVolumeMul(1)
			}
		}
	}
	
	setTip(tip, error=false){
		if(this.tip){
			this.tip.remove()
			delete this.tip
		}
		
		if(!tip){
			tip = strings.search.tip + " " + strings.search.tips[Math.floor(Math.random() * strings.search.tips.length)]
		}
		
		var resultsDiv = this.div.querySelector(":scope #song-search-results")
		resultsDiv.innerHTML = ""
		this.results = []
		
		this.tip = document.createElement("div")
		this.tip.id = "song-search-tip"
		this.tip.innerText = tip
		this.div.querySelector(":scope #song-search").appendChild(this.tip)
		
		if(error){
			this.tip.classList.add("song-search-tip-error")
		}
	}
	
	proceed(songId){
		if (/^-?\d+$/.test(songId)) {
			songId = parseInt(songId)
		}

		var song = this.songSelect.songs.find(song => song.id === songId)
		this.remove()
		this.songSelect.playBgm(false)
		if(this.songSelect.previewing === "muted"){
			this.songSelect.previewing = null
		}
		
		var songIndex = this.songSelect.songs.findIndex(song => song.id === songId)
		this.songSelect.setSelectedSong(songIndex)
		this.songSelect.toSelectDifficulty()
	}
	
	scrollTo(element){
		var parentNode = element.parentNode
		var selected = element.getBoundingClientRect()
		var parent = parentNode.getBoundingClientRect()
		var scrollY = parentNode.scrollTop
		var selectedPosTop = selected.top - selected.height / 2
		if(Math.floor(selectedPosTop) < Math.floor(parent.top)){
			parentNode.scrollTop += selectedPosTop - parent.top
		}else{
			var selectedPosBottom = selected.top + selected.height * 1.5 - parent.top
			if(Math.floor(selectedPosBottom) > Math.floor(parent.height)){
				parentNode.scrollTop += selectedPosBottom - parent.height
			}
		}
	}
	
	parseRange(string){
		var range = string.split("-")
		if(range.length == 1){
			var min = parseInt(range[0]) || 0
			return min > 0 ? {min: min, max: min} : false
		} else if(range.length == 2){
			var min = parseInt(range[0]) || 0
			var max = parseInt(range[1]) || 0
			return min > 0 && max > 0 ? {min: min, max: max} : false
		}
	}
	
	indexesToRanges(indexes){
		var ranges = []
		var range
		indexes.forEach(idx => {
			if(range && range[1] === idx - 1){
				range[1] = idx
			}else{
				range = [idx, idx]
				ranges.push(range)
			}
		})
		return ranges
	}
	
	onInput(resize){
		var text = this.input.value
		localStorage.setItem("lastSearchQuery", text)
		text = text.toLowerCase()
		
		if(text.length === 0){
			if(!resize){
				this.setTip()
			}
			return
		}
		
		var new_results = this.perform(text)
		
		if(new_results.length === 0){
			this.setTip(strings.search.noResults, true)
			return
		}else if(this.tip){
			this.tip.remove()
			delete this.tip
		}
		
		var resultsDiv = this.div.querySelector(":scope #song-search-results")
		resultsDiv.innerHTML = ""
		this.results = []
		
		var fontSize = parseFloat(getComputedStyle(this.div.querySelector(":scope #song-search")).fontSize.slice(0, -2))
		var resultsWidth = parseFloat(getComputedStyle(resultsDiv).width.slice(0, -2))
		var vmin = Math.min(innerWidth, lastHeight) / 100
		var courseWidth = Math.min(3 * fontSize * 1.2, 7 * vmin)
		var resultWidth = resultsWidth - 1.8 * fontSize - 0.8 * fontSize - (courseWidth + 0.4 * fontSize * 1.2) * 5 - 0.6 * fontSize
		
		this.songSelect.ctx.save()
		
		var fragment = document.createDocumentFragment()
		new_results.forEach(result => {
			var result = this.createResult(result, resultWidth, fontSize)
			fragment.appendChild(result)
			this.results.push(result)
		})
		resultsDiv.appendChild(fragment)
		
		this.songSelect.ctx.restore()
	}
	
	onClick(e){
		if((e.target.id === "song-search-container" || e.target.id === "song-search-close") && e.which === 1){
			this.remove(true)
		}else if(e.which === 1){
			var songEl = e.target.closest(".song-search-result")
			if(songEl){
				var songId = songEl.dataset.songId
				this.proceed(songId)
			}
		}
	}
	
	keyPress(pressed, name, event, repeat, ctrl){
		if(name === "back" || (event && event.keyCode && event.keyCode === 70 && ctrl)) {
			this.remove(true)
			if(event){
				event.preventDefault()
			}
		}else if(name === "down" && this.results.length){
			if(this.input == document.activeElement && this.results){
				this.setActive(0)
			}else if(this.active === this.results.length - 1){
				this.setActive(null)
				this.input.focus()
			}else if(Number.isInteger(this.active)){
				this.setActive(this.active + 1)
			}else{
				this.setActive(0)
			}
		}else if(name === "up" && this.results.length){
			if(this.input == document.activeElement && this.results){
				this.setActive(this.results.length - 1)
			}else if(this.active === 0){
				this.setActive(null)
				this.input.focus()
				setTimeout(() => {
					this.input.setSelectionRange(this.input.value.length, this.input.value.length)
				}, 0)
			}else if(Number.isInteger(this.active)){
				this.setActive(this.active - 1)
			}else{
				this.setActive(this.results.length - 1)
			}	
		}else if(name === "confirm"){
			if(Number.isInteger(this.active)){
				this.proceed(this.results[this.active].dataset.songId)
			}else{
				this.onInput()
				if(event.keyCode === 13 && this.songSelect.touchEnabled){
					this.input.blur()
				}
			}
		}
	}
	
	redraw(){
		if(this.opened && this.container){
			var vmin = Math.min(innerWidth, lastHeight) / 100
			if(this.vmin !== vmin){
				this.container.style.setProperty("--vmin", vmin + "px")
				this.vmin = vmin
			}
		}else{
			this.vmin = null
		}
	}
	
	clean(){
		loader.screen.removeChild(this.style)
		fuzzysort.cleanup()
		delete this.container
		delete this.style
		delete this.songSelect
	}
}
