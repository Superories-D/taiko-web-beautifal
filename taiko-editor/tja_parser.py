"""
Full bidirectional TJA parser and serializer.
Reads TJA text → Song model, and writes Song model → TJA text.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple
from models import (
    Song, Course, Measure, Note, NoteType,
    Keyframe, KeyframeType, COURSE_NAMES
)


# ──────────────────────── Parser ────────────────────────

COURSE_MAP = {
    "EASY": "easy", "0": "easy",
    "NORMAL": "normal", "1": "normal",
    "HARD": "hard", "2": "hard",
    "ONI": "oni", "3": "oni",
    "EDIT": "ura", "URA": "ura", "4": "ura",
}


def parse_tja(text: str) -> Song:
    """Parse TJA file text into a Song model."""
    song = Song()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    current_course_name = "oni"
    current_course: Optional[Course] = None
    in_song = False
    current_measure_str = ""
    pending_keyframes: List[Keyframe] = []
    measure_index = 0

    for raw_line in lines:
        # Strip comments (but keep MAKER: lines)
        line = raw_line.strip()
        if not line:
            continue
        comment_idx = line.find("//")
        if comment_idx >= 0 and not line.upper().startswith("MAKER:"):
            line = line[:comment_idx].strip()
        if not line:
            continue

        # ─── Header metadata (before #START) ───
        if not in_song and ":" in line and not line.startswith("#"):
            key, val = line.split(":", 1)
            key = key.strip().upper()
            val = val.strip()
            _parse_header(song, key, val, current_course_name)
            # Per-course metadata
            if key == "COURSE":
                mapped = COURSE_MAP.get(val.upper(), val.lower())
                current_course_name = mapped
            elif key in ("LEVEL", "BALLOON", "SCOREINIT", "SCOREDIFF", "SCOREMODE"):
                course = song.get_or_create_course(current_course_name)
                _parse_course_meta(course, key, val)
            continue

        # ─── #START ───
        if line.upper() in ("#START", "#START P1"):
            in_song = True
            current_course = song.get_or_create_course(current_course_name)
            current_measure_str = ""
            pending_keyframes = []
            measure_index = 0
            continue

        # ─── #END ───
        if line.upper() == "#END":
            in_song = False
            current_course = None
            continue

        if not in_song or current_course is None:
            continue

        # ─── In-song commands ───
        if line.startswith("#"):
            cmd_line = line[1:]
            parts = cmd_line.split(None, 1)
            cmd_name = parts[0].upper() if parts else ""
            cmd_val = parts[1].strip() if len(parts) > 1 else ""

            kf = _parse_command_to_keyframe(cmd_name, cmd_val, measure_index)
            if kf is not None:
                pending_keyframes.append(kf)
                current_course.keyframes.append(kf)

            if cmd_name.startswith("BRANCHSTART"):
                current_course.has_branch = True
            continue

        # ─── Note data lines ───
        for ch in line:
            if ch == ",":
                # End of measure
                measure = Measure.from_string(current_measure_str)
                # Attach pending keyframes sub_position
                for kf in pending_keyframes:
                    kf.sub_position = 0
                pending_keyframes = []
                current_course.measures.append(measure)
                current_measure_str = ""
                measure_index += 1
            elif ch in "0123456789ABab":
                current_measure_str += ch.upper()

    return song


def _parse_header(song: Song, key: str, val: str, course_name: str):
    """Parse global header metadata."""
    if key == "TITLE":
        song.title = val
    elif key == "TITLEJA":
        song.title_ja = val
    elif key == "SUBTITLE":
        song.subtitle = val.lstrip("+-")
    elif key == "SUBTITLEJA":
        song.subtitle_ja = val.lstrip("+-")
    elif key == "WAVE":
        song.wave = val
    elif key == "OFFSET":
        try:
            song.offset = float(val)
        except ValueError:
            pass
    elif key == "DEMOSTART":
        try:
            song.demostart = float(val)
        except ValueError:
            pass
    elif key == "BPM":
        try:
            song.bpm = float(val)
        except ValueError:
            pass


def _parse_course_meta(course: Course, key: str, val: str):
    """Parse per-course metadata."""
    if key == "LEVEL":
        try:
            course.level = int(re.split(r"\s+", val)[0])
        except ValueError:
            pass
    elif key == "BALLOON":
        if val:
            course.balloon = [int(x) for x in val.split(",") if x.strip().isdigit()]
    elif key == "SCOREINIT":
        try:
            course.score_init = int(val.split(",")[0])
        except (ValueError, IndexError):
            pass
    elif key == "SCOREDIFF":
        try:
            course.score_diff = int(val)
        except ValueError:
            pass
    elif key == "SCOREMODE":
        try:
            course.score_mode = int(val)
        except ValueError:
            pass


def _parse_command_to_keyframe(cmd: str, val: str, measure_idx: int) -> Optional[Keyframe]:
    """Convert a # command into a Keyframe, or None if not a keyframe type."""
    if cmd == "BPMCHANGE":
        try:
            return Keyframe(KeyframeType.BPM, float(val), measure_idx)
        except ValueError:
            return None
    elif cmd == "SCROLL":
        try:
            return Keyframe(KeyframeType.SCROLL, float(val), measure_idx)
        except ValueError:
            return None
    elif cmd == "MEASURE":
        # Store as "numerator/denominator" string; value = numerator/denominator * 4
        try:
            nums = val.split("/")
            ratio = float(nums[0]) / float(nums[1]) * 4
            return Keyframe(KeyframeType.MEASURE, ratio, measure_idx)
        except (ValueError, IndexError, ZeroDivisionError):
            return None
    elif cmd == "GOGOSTART":
        return Keyframe(KeyframeType.GOGO_START, 1.0, measure_idx)
    elif cmd == "GOGOEND":
        return Keyframe(KeyframeType.GOGO_END, 0.0, measure_idx)
    elif cmd == "BARLINEON":
        return Keyframe(KeyframeType.BARLINE_ON, 1.0, measure_idx)
    elif cmd == "BARLINEOFF":
        return Keyframe(KeyframeType.BARLINE_OFF, 0.0, measure_idx)
    elif cmd == "DELAY":
        try:
            return Keyframe(KeyframeType.DELAY, float(val), measure_idx)
        except ValueError:
            return None
    return None


# ──────────────────────── Serializer ────────────────────────

COURSE_NAME_TO_TJA = {
    "easy": "Easy", "normal": "Normal", "hard": "Hard",
    "oni": "Oni", "ura": "Edit",
}


def serialize_tja(song: Song) -> str:
    """Serialize a Song model to TJA file text."""
    lines: List[str] = []

    # ─── Global header ───
    if song.title:
        lines.append(f"TITLE:{song.title}")
    if song.title_ja:
        lines.append(f"TITLEJA:{song.title_ja}")
    if song.subtitle:
        lines.append(f"SUBTITLE:--{song.subtitle}")
    if song.subtitle_ja:
        lines.append(f"SUBTITLEJA:--{song.subtitle_ja}")
    lines.append(f"BPM:{song.bpm}")
    if song.wave:
        lines.append(f"WAVE:{song.wave}")
    lines.append(f"OFFSET:{song.offset}")
    if song.demostart:
        lines.append(f"DEMOSTART:{song.demostart}")
    lines.append("")

    # ─── Per-course ───
    for course_name in COURSE_NAMES:
        if course_name not in song.courses:
            continue
        course = song.courses[course_name]
        tja_name = COURSE_NAME_TO_TJA.get(course_name, course_name)
        lines.append(f"COURSE:{tja_name}")
        lines.append(f"LEVEL:{course.level}")
        if course.balloon:
            lines.append(f"BALLOON:{','.join(str(b) for b in course.balloon)}")
        if course.score_init is not None:
            lines.append(f"SCOREINIT:{course.score_init}")
        if course.score_diff is not None:
            lines.append(f"SCOREDIFF:{course.score_diff}")
        if course.score_mode is not None:
            lines.append(f"SCOREMODE:{course.score_mode}")
        lines.append("")

        # Build keyframe lookup: measure_index → list of keyframes
        kf_by_measure: dict[int, List[Keyframe]] = {}
        for kf in course.keyframes:
            kf_by_measure.setdefault(kf.measure_index, []).append(kf)

        lines.append("#START")

        for i, measure in enumerate(course.measures):
            # Insert keyframes before this measure
            if i in kf_by_measure:
                for kf in kf_by_measure[i]:
                    cmd = kf.to_command()
                    if cmd:
                        # Format MEASURE back to fraction if applicable
                        if kf.kf_type == KeyframeType.MEASURE:
                            # Try to reconstruct a reasonable fraction
                            ratio = kf.value / 4
                            num, den = _float_to_fraction(ratio)
                            lines.append(f"#MEASURE {num}/{den}")
                        else:
                            lines.append(cmd)

            lines.append(measure.to_string() + ",")

        lines.append("#END")
        lines.append("")

    return "\n".join(lines)


def _float_to_fraction(value: float, max_denom: int = 16) -> Tuple[int, int]:
    """Approximate a float as a simple fraction."""
    best_num, best_den = round(value), 1
    best_err = abs(value - best_num)
    for den in range(1, max_denom + 1):
        num = round(value * den)
        err = abs(value - num / den)
        if err < best_err:
            best_err = err
            best_num = num
            best_den = den
            if err == 0:
                break
    return best_num, best_den
