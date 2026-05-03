class DailyChallenge {
	constructor() {
		this.challenge = null
	}

	async get(force) {
		if(this.challenge && !force) {
			return this.challenge
		}
		var response = await fetch("api/daily_challenge")
		var data = await response.json()
		if(data.status === "ok") {
			this.challenge = data
			return data
		}
		throw new Error("daily_challenge_failed")
	}

	async start(songSelect) {
		var challenge = await this.get()
		if(!challenge.song) {
			return false
		}
		var index = songSelect.songs.findIndex(song => song.id === challenge.song.id && song.courses)
		if(index === -1) {
			return false
		}
		songSelect.setSelectedSong(index)
		var diffIndex = songSelect.difficultyId.indexOf(challenge.difficulty)
		if(diffIndex !== -1) {
			songSelect.selectedDiff = diffIndex + songSelect.diffOptions.length
		}
		try {
			localStorage.setItem("dailyChallengeActive", JSON.stringify({
				date: challenge.date,
				hash: challenge.song.hash || challenge.song.title,
				difficulty: challenge.difficulty
			}))
		} catch(e) {}
		songSelect.toSelectDifficulty(false)
		return true
	}

	isActive(hash, difficulty) {
		try {
			var active = JSON.parse(localStorage.getItem("dailyChallengeActive") || "null")
			return active && active.hash === hash && active.difficulty === difficulty
		} catch(e) {
			return false
		}
	}
}

var dailyChallenge = new DailyChallenge()
