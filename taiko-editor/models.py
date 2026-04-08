"""
Data models for TJA chart editor.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Dict


class NoteType(IntEnum):
    """TJA note type codes."""
    NONE = 0
    DON = 1
    KA = 2
    DAI_DON = 3
    DAI_KA = 4
    DRUMROLL = 5
    DAI_DRUMROLL = 6
    BALLOON = 7
    END = 8
    KUSUDAMA = 9

    @property
    def display_name(self) -> str:
        names = {
            0: "", 1: "ドン", 2: "カッ", 3: "大ドン", 4: "大カッ",
            5: "連打", 6: "大連打", 7: "風船", 8: "終", 9: "くす玉"
        }
        return names.get(self.value, "")

    @property
    def is_long(self) -> bool:
        return self.value in (5, 6, 7, 9)


class KeyframeType(IntEnum):
    """Types of keyframe events on the timeline."""
    BPM = 0
    SCROLL = 1
    MEASURE = 2
    GOGO_START = 3
    GOGO_END = 4
    BARLINE_ON = 5
    BARLINE_OFF = 6
    DELAY = 7

    @property
    def display_name(self) -> str:
        names = {
            0: "BPM", 1: "SCROLL", 2: "拍子", 3: "GoGo開始",
            4: "GoGo終了", 5: "小節線ON", 6: "小節線OFF", 7: "DELAY"
        }
        return names.get(self.value, "")

    @property
    def color_hex(self) -> str:
        colors = {
            0: "#FF6B6B", 1: "#4ECDC4", 2: "#45B7D1", 3: "#F7DC6F",
            4: "#AF7AC5", 5: "#58D68D", 6: "#E74C3C", 7: "#85929E"
        }
        return colors.get(self.value, "#FFFFFF")


COURSE_NAMES = ["easy", "normal", "hard", "oni", "ura"]
COURSE_DISPLAY = {
    "easy": "かんたん", "normal": "ふつう", "hard": "むずかしい",
    "oni": "おに", "ura": "裏"
}


@dataclass(eq=False)
class Note:
    """A single note in a measure."""
    note_type: NoteType = NoteType.NONE
    balloon_hits: int = 0  # only for BALLOON / KUSUDAMA

    def to_char(self) -> str:
        if self.note_type.value <= 9:
            return str(self.note_type.value)
        return "0"


@dataclass
class Keyframe:
    """A timeline keyframe event."""
    kf_type: KeyframeType = KeyframeType.BPM
    value: float = 120.0
    measure_index: int = 0  # which measure this keyframe belongs to
    sub_position: int = 0   # position within the measure (0 = start)

    def to_command(self) -> str:
        cmd_map = {
            KeyframeType.BPM: f"#BPMCHANGE {self.value}",
            KeyframeType.SCROLL: f"#SCROLL {self.value}",
            KeyframeType.MEASURE: f"#MEASURE {self.value}",
            KeyframeType.GOGO_START: "#GOGOSTART",
            KeyframeType.GOGO_END: "#GOGOEND",
            KeyframeType.BARLINE_ON: "#BARLINEON",
            KeyframeType.BARLINE_OFF: "#BARLINEOFF",
            KeyframeType.DELAY: f"#DELAY {self.value}",
        }
        return cmd_map.get(self.kf_type, "")


@dataclass
class Measure:
    """A single measure (小節) containing notes."""
    notes: List[Note] = field(default_factory=lambda: [Note()])
    
    def to_string(self) -> str:
        return "".join(n.to_char() for n in self.notes)

    @classmethod
    def from_string(cls, s: str) -> "Measure":
        notes = []
        for ch in s:
            if ch.isdigit():
                notes.append(Note(NoteType(int(ch))))
            elif ch.upper() == 'A':
                notes.append(Note(NoteType.DAI_DON))
            elif ch.upper() == 'B':
                notes.append(Note(NoteType.DAI_KA))
            else:
                notes.append(Note(NoteType.NONE))
        if not notes:
            notes = [Note(NoteType.NONE)]
        return cls(notes=notes)

    @property
    def subdivision(self) -> int:
        return len(self.notes)


@dataclass
class Course:
    """A difficulty course (Easy/Normal/Hard/Oni/Ura)."""
    name: str = "oni"
    level: int = 1
    balloon: List[int] = field(default_factory=list)
    score_init: Optional[int] = None
    score_diff: Optional[int] = None
    score_mode: Optional[int] = None
    measures: List[Measure] = field(default_factory=list)
    keyframes: List[Keyframe] = field(default_factory=list)
    has_branch: bool = False

    @property
    def display_name(self) -> str:
        return COURSE_DISPLAY.get(self.name, self.name)


@dataclass
class Song:
    """Top-level song data model."""
    title: str = ""
    title_ja: str = ""
    subtitle: str = ""
    subtitle_ja: str = ""
    wave: str = ""
    offset: float = 0.0
    demostart: float = 0.0
    bpm: float = 120.0
    courses: Dict[str, Course] = field(default_factory=dict)

    def get_or_create_course(self, name: str) -> Course:
        if name not in self.courses:
            self.courses[name] = Course(name=name)
        return self.courses[name]
