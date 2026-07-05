import os
import re
from typing import Dict, Optional

class Tja:
    def __init__(self, text: str):
        self.text = text
        self.title: Optional[str] = None
        self.subtitle: Optional[str] = None
        self.title_ja: Optional[str] = None
        self.subtitle_ja: Optional[str] = None
        self.wave: Optional[str] = None
        self.offset: Optional[float] = None
        self.courses: Dict[str, Dict[str, Optional[int]]] = {}
        self.dan_dojo: Dict = {"enabled": False, "exams": [], "songs": []}
        self.is_dan: bool = False
        self._parse()

    def _parse(self) -> None:
        lines = self.text.split("\n")
        current_course: Optional[str] = None
        current_song_index: Optional[int] = None
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                command = line[1:].strip()
                if command.upper().startswith("NEXTSONG"):
                    next_song = self._parse_nextsong(command[8:].strip())
                    if next_song.get("wave"):
                        next_song["songIndex"] = len(self.dan_dojo["songs"])
                        current_song_index = next_song["songIndex"]
                        if self.is_dan:
                            self.dan_dojo["enabled"] = True
                            self.dan_dojo["songs"].append(next_song)
                elif current_course and (command.startswith("BRANCHSTART") or command.startswith("#BRANCHSTART")):
                    self.courses[current_course]["branch"] = True
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                key = k.strip().upper()
                val = v.strip()
                if key == "TITLE":
                    self.title = val or None
                elif key == "TITLEJA":
                    self.title_ja = val or None
                elif key == "SUBTITLE":
                    self.subtitle = val or None
                elif key == "SUBTITLEJA":
                    self.subtitle_ja = val or None
                elif key == "WAVE":
                    self.wave = val or None
                elif key == "OFFSET":
                    try:
                        self.offset = float(val)
                    except ValueError:
                        self.offset = None
                elif key == "COURSE":
                    course_map = {
                        "EASY": "easy",
                        "NORMAL": "normal",
                        "HARD": "hard",
                        "ONI": "oni",
                        "EDIT": "ura",
                        "URA": "ura",
                        "DAN": "oni",
                        "TOWER": "oni",
                    }
                    raw_course = val.strip().upper()
                    self.is_dan = raw_course == "DAN"
                    current_song_index = None
                    current_course = course_map.get(raw_course)
                    if current_course and current_course not in self.courses:
                        self.courses[current_course] = {"stars": None, "branch": False}
                elif key == "LEVEL" and current_course:
                    try:
                        stars = int(re.split(r"\s+", val)[0])
                    except ValueError:
                        stars = None
                    self.courses[current_course]["stars"] = stars
                elif key.startswith("EXAM"):
                    exam = self._parse_exam(key, val, current_song_index)
                    if exam:
                        self.dan_dojo["enabled"] = True
                        self.dan_dojo["exams"].append(exam)
                elif key == "DANTICK":
                    ticks = []
                    for part in val.split(","):
                        try:
                            ticks.append(float(part.strip()))
                        except ValueError:
                            pass
                    self.dan_dojo["enabled"] = True
                    self.dan_dojo["tick"] = ticks
                elif key == "DANTICKCOLOR":
                    self.dan_dojo["enabled"] = True
                    self.dan_dojo["tickColor"] = val

    @staticmethod
    def _parse_nextsong(value: str) -> Dict:
        parts = [part.strip() for part in (value or "").split(",")]
        if len(parts) > 6:
            parts = [",".join(parts[:len(parts) - 5])] + parts[len(parts) - 5:]
        song = {
            "title": parts[0] if len(parts) > 0 else "",
            "subtitle": parts[1] if len(parts) > 1 else "",
            "genre": parts[2] if len(parts) > 2 else "",
            "wave": parts[3] if len(parts) > 3 else "",
        }
        for key, index in (("score", 4), ("bpm", 5)):
            if len(parts) > index and parts[index] != "":
                try:
                    song[key] = float(parts[index])
                except ValueError:
                    pass
        return song

    @staticmethod
    def _parse_exam(name: str, value: str, song_index: Optional[int]) -> Optional[Dict]:
        parts = [part.strip() for part in (value or "").split(",")]
        if not parts or not parts[0]:
            return None
        try:
            red = float(parts[1])
        except (IndexError, ValueError):
            red = 0.0
        try:
            gold = float(parts[2])
        except (IndexError, ValueError):
            gold = red
        mode = parts[3].lower() if len(parts) > 3 else "m"
        number = re.sub(r"\D", "", name)
        return {
            "id": int(number) if number else 0,
            "type": parts[0].lower(),
            "red": red,
            "gold": gold,
            "compare": "max" if mode == "l" else "min",
            "scope": "song" if song_index is not None else "global",
            "songIndex": song_index,
            "raw": f"{name}:{value}",
        }

    def to_mongo(self, song_id: str, created_ns: int) -> Dict:
        ext = None
        if self.wave:
            base = os.path.basename(self.wave)
            _, e = os.path.splitext(base)
            if e:
                ext = e.lstrip(".").lower()
        if not ext:
            ext = "mp3"
        courses_out: Dict[str, Optional[Dict[str, Optional[int]]]] = {}
        for name in ["easy", "normal", "hard", "oni", "ura"]:
            courses_out[name] = self.courses.get(name) or None
        output = {
            "id": song_id,
            "type": "tja",
            "title": self.title,
            "subtitle": self.subtitle,
            "title_lang": {
                "ja": self.title_ja or self.title,
                "en": None,
                "cn": self.title_ja or None,
                "tw": None,
                "ko": None,
            },
            "subtitle_lang": {
                "ja": self.subtitle_ja or self.subtitle,
                "en": None,
                "cn": self.subtitle_ja or None,
                "tw": None,
                "ko": None,
            },
            "courses": courses_out,
            "enabled": False,
            "category_id": None,
            "music_type": ext,
            # DB 的 offset 是“额外偏移”，TJA 自身的 OFFSET 会在前端解析时应用
            # 为避免双重偏移，这里固定为 0
            "offset": 0,
            "skin_id": None,
            "preview": 0,
            "volume": 1.0,
            "maker_id": None,
            "hash": None,
            "order": song_id,
            "created_ns": created_ns,
        }
        if self.dan_dojo.get("enabled"):
            output["dan_dojo"] = self.dan_dojo
        return output
