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
        self.bpm_values = []
        self.courses: Dict[str, Dict[str, Optional[int]]] = {}
        self._parse()

    def _parse(self) -> None:
        lines = self.text.split("\n")
        current_course: Optional[str] = None
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            # TJA files use both ``#BPMCHANGE:180`` and ``#BPMCHANGE 180``.
            bpm_change = re.match(r'^#BPMCHANGE\s+([-+]?\d+(?:\.\d+)?)$', line, re.IGNORECASE)
            if bpm_change:
                try:
                    bpm = float(bpm_change.group(1))
                    if 1 <= bpm <= 1000:
                        self.bpm_values.append(bpm)
                except ValueError:
                    pass
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
                elif key in ("BPM", "#BPMCHANGE"):
                    try:
                        bpm = float(re.split(r"\s+", val)[0])
                        if 1 <= bpm <= 1000:
                            self.bpm_values.append(bpm)
                    except ValueError:
                        pass
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
                    current_course = course_map.get(val.strip().upper())
                    if current_course and current_course not in self.courses:
                        self.courses[current_course] = {"stars": None, "branch": False}
                elif key == "LEVEL" and current_course:
                    try:
                        stars = int(re.split(r"\s+", val)[0])
                    except ValueError:
                        stars = None
                    self.courses[current_course]["stars"] = stars
            else:
                if current_course and (line.startswith("BRANCHSTART") or line.startswith("#BRANCHSTART")):
                    self.courses[current_course]["branch"] = True

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
        if self.bpm_values:
            output["bpm_min"] = min(self.bpm_values)
            output["bpm_max"] = max(self.bpm_values)
        return output
