class Favorites {
	constructor() {
		this.favoriteKey = "favoriteSongs"
		this.recentKey = "recentSongs"
		this.recentLimit = 20
	}

	read(key) {
		try {
			var value = JSON.parse(localStorage.getItem(key) || "[]")
			return Array.isArray(value) ? value : []
		} catch(e) {
			return []
		}
	}

	write(key, value) {
		try {
			localStorage.setItem(key, JSON.stringify(value))
		} catch(e) {}
	}

	getFavorites() {
		return this.read(this.favoriteKey)
	}

	isFavorite(hash) {
		return this.getFavorites().indexOf(hash) !== -1
	}

	toggle(hash) {
		var favorites = this.getFavorites()
		var index = favorites.indexOf(hash)
		if(index === -1) {
			favorites.unshift(hash)
		} else {
			favorites.splice(index, 1)
		}
		this.write(this.favoriteKey, favorites)
		return index === -1
	}

	getRecent() {
		return this.read(this.recentKey)
	}

	addRecent(hash) {
		if(!hash) return
		var recent = this.getRecent().filter(item => item !== hash)
		recent.unshift(hash)
		this.write(this.recentKey, recent.slice(0, this.recentLimit))
	}

	firstAvailable(songs, type) {
		var hashes = type === "recent" ? this.getRecent() : this.getFavorites()
		for(var i = 0; i < hashes.length; i++) {
			var index = songs.findIndex(song => song.hash === hashes[i] && song.courses)
			if(index !== -1) {
				return index
			}
		}
		return -1
	}
}

var favorites = new Favorites()
