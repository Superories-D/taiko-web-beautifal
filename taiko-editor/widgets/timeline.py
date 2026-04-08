"""
Timeline Widget for TJA Editor (PyQt5).
CapCut-inspired design — optimized with waveform cache, note track band, quick-add support.
"""
from __future__ import annotations
from typing import Optional, List
from PyQt5.QtWidgets import QWidget, QMenu
from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, QRect, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QPixmap,
    QMouseEvent, QWheelEvent, QPainterPath, QFont
)

from models import Song, Course, Measure, Note, NoteType, Keyframe, KeyframeType
from audio_engine import AudioEngine

# ─── Palette ───
COL_BG = QColor("#121215")
COL_TRACK = QColor("#1a1a1f")
COL_NOTE_BAND = QColor(28, 30, 42, 220)
COL_NOTE_BAND_BORDER = QColor("#2e3040")
COL_WAVE_FILL = QColor(0, 220, 180, 40)
COL_WAVE_LINE = QColor(0, 220, 180, 90)
COL_GRID_MEAS = QColor("#383840")
COL_GRID_BEAT = QColor("#262630")
COL_PLAYHEAD = QColor("#00e6bb")

NOTE_COLORS = {
    NoteType.DON: QColor("#ff5252"),      # Vibrant red
    NoteType.KA: QColor("#448aff"),       # Vivid blue
    NoteType.DAI_DON: QColor("#ff8a80"),  # Light coral
    NoteType.DAI_KA: QColor("#82b1ff"),   # Light blue
    NoteType.DRUMROLL: QColor("#ffab40"), # Warm amber
    NoteType.DAI_DRUMROLL: QColor("#ffd180"),
    NoteType.BALLOON: QColor("#ff6e40"),  # Deep orange
    NoteType.KUSUDAMA: QColor("#ff4081"), # Pink
    NoteType.END: QColor("#78909c"),      # Cool grey
}


# Default high-resolution subdivision for new measures.
# 48 is divisible by 2,3,4,6,8,12,16,24 — covers all common time signatures.
DEFAULT_SUBDIV = 48
# When quantization error exceeds this threshold (ms), the measure is auto-expanded.
QUANT_THRESHOLD_MS = 10.0

# GoGo band color
COL_GOGO_BAND = QColor(0, 210, 120, 22)
COL_GOGO_LINE = QColor(0, 210, 120, 55)
COL_GRID_SUB = QColor("#1e1e28")


class TimelineWidget(QWidget):
    positionChanged = pyqtSignal(float)
    noteSelected = pyqtSignal(object, object, int, int, int)

    RULER_H = 28
    KF_LANE_H = 24
    TRACK_TOP = 52
    NOTE_BAND_H = 56
    NOTE_RADIUS = 12

    def __init__(self, audio: AudioEngine, parent=None):
        super().__init__(parent)
        self.audio = audio
        self.song: Optional[Song] = None
        self.course: Optional[Course] = None

        self.zoom = 200.0
        self.scroll_x = 0.0
        self.cursor_ms = 0.0
        self.selected_obj = None

        self.current_note_type = NoteType.DON
        self.edit_mode = "select"
        self.preview_enabled = True
        self.snap_divisor = 16

        # Interaction State
        self.selected_notes: List[Note] = []
        self._drag_mode = "none"  # "box", "move", "pen"
        self._drag_start_pos = QPointF()
        self._drag_start_ms = 0.0
        self._selection_rect = QRectF()
        self._move_delta_ms = 0.0
        self._drag_orig_ms = {}

        self._drag_active = False
        self._drag_end_ms = 0.0
        self._last_play_ms = 0.0

        # Waveform cache — oversized to avoid regen on every scroll
        self._wc_pix: Optional[QPixmap] = None
        self._wc_s_ms = 0.0
        self._wc_e_ms = 0.0
        self._wc_zoom = -1.0
        self._wc_h = -1

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(200)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_song_and_course(self, song: Song, course: Course):
        self.song = song
        self.course = course
        self.selected_notes = []
        self.selected_obj = None
        self._wc_pix = None
        self.update()

    # ─── Coordinates ───

    def ms_to_px(self, ms: float) -> float:
        return ms / 1000.0 * self.zoom

    def px_to_ms(self, px: float) -> float:
        return px / self.zoom * 1000.0

    def world_x(self, ms: float) -> float:
        return self.ms_to_px(ms) - self.scroll_x

    def screen_to_ms(self, sx: float) -> float:
        return self.px_to_ms(sx + self.scroll_x)

    @property
    def _note_band_y(self):
        """Y position of the note track band (bottom area of main track)."""
        h = self.height()
        return h - self.NOTE_BAND_H - 20  # 20px bottom margin for labels

    @property
    def _note_mid_y(self):
        return self._note_band_y + self.NOTE_BAND_H / 2

    # ─── Public API ───

    def quick_add(self, note_type: NoteType):
        """Place a note at the current cursor position (works during playback)."""
        if not self.song or not self.course:
            return
        ms = self.cursor_ms
        self._ensure_measures(ms)
        self._place_note_at_snap(ms, note_type)
        self._play_sfx(note_type)
        self.update()

    def move_cursor(self, direction: int):
        """Move cursor to next/previous grid division based on snap_divisor."""
        if not self.song:
            return
        if self.snap_divisor > 0:
            meas_start, bpm, ml = self._measure_at_ms(self.cursor_ms)
            grid = (60000.0 / bpm) * (ml / self.snap_divisor)
            offset_in_meas = self.cursor_ms - meas_start
            if direction > 0:
                self.cursor_ms = meas_start + (int(offset_in_meas / grid) + 1) * grid
            else:
                snapped = meas_start + int(offset_in_meas / grid) * grid
                if abs(self.cursor_ms - snapped) < 0.5:
                    self.cursor_ms = max(0, snapped - grid)
                else:
                    self.cursor_ms = max(0, snapped)
        else:
            self.cursor_ms = max(0, self.cursor_ms + direction * 50.0)
        if not self.audio.is_playing:
            self.audio.seek(self.cursor_ms)
        # Keep cursor visible
        px = self.world_x(self.cursor_ms)
        w = self.width()
        if px < 50:
            self.scroll_x = max(0, self.ms_to_px(self.cursor_ms) - 100)
        elif px > w - 50:
            self.scroll_x = self.ms_to_px(self.cursor_ms) - w + 100
        self.update()

    def select_all(self):
        """Select every non-NONE note in the current course."""
        self.selected_notes = []
        if not self.course:
            return
        for m in self.course.measures:
            for n in m.notes:
                if n.note_type != NoteType.NONE:
                    self.selected_notes.append(n)
        self.update()

    def get_copy_data(self):
        """Return selected notes as portable data: list of (offset_ms, NoteType, balloon_hits)."""
        if not self.selected_notes or not self.course:
            return []
        # Find the minimum ms of selected notes as reference
        entries = []
        for n in self.selected_notes:
            ms = self._get_note_ms(n)
            entries.append((ms, n.note_type, n.balloon_hits))
        entries.sort(key=lambda e: e[0])
        base_ms = entries[0][0]
        return [(ms - base_ms, nt, bh) for ms, nt, bh in entries]

    def paste_copy_data(self, data, target_ms):
        """Paste copy data at target_ms."""
        if not data or not self.course:
            return
        new_sel = []
        for offset, ntype, bh in data:
            ms = target_ms + offset
            self._ensure_measures(ms)
            self._place_note_at_snap(ms, ntype)
            if self.selected_obj:
                self.selected_obj.balloon_hits = bh
                new_sel.append(self.selected_obj)
        self.selected_notes = new_sel
        self.update()

    def _ensure_measures(self, ms: float):
        """Create empty measures (high-res) so that `ms` falls within one."""
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        # Build keyframe lookup
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)

        # Walk existing measures using their actual BPM/measure-length keyframes
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM:
                            bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE:
                            ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            t += dur
        # Append new measures using the last-known BPM/measure-length
        while t < ms + 1:
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            t += dur
            self.course.measures.append(
                Measure(notes=[Note() for _ in range(DEFAULT_SUBDIV)])
            )

    @staticmethod
    def _expand_subdiv(measure: Measure, target_subdiv: int):
        """Grow a measure's subdivision while preserving existing notes."""
        cur = len(measure.notes)
        if cur >= target_subdiv:
            return
        factor = target_subdiv // cur
        new_sub = cur * factor
        new_notes = [Note() for _ in range(new_sub)]
        for i, n in enumerate(measure.notes):
            new_notes[i * factor] = Note(
                note_type=n.note_type, balloon_hits=n.balloon_hits
            )
        measure.notes = new_notes

    # ─── Timer ───

    def _tick(self):
        if not self.audio.is_playing:
            self._last_play_ms = self.cursor_ms
            return

        cur = self.audio.get_position_ms()
        if self.preview_enabled and self.course:
            self._preview_sfx(self._last_play_ms, cur)
        self.cursor_ms = cur
        self._last_play_ms = cur

        # Smooth auto-scroll
        px = self.world_x(cur)
        w = self.width()
        if px > w * 0.7:
            self.scroll_x = self.ms_to_px(cur) - w * 0.3
        elif px < 0:
            self.scroll_x = max(0, self.ms_to_px(cur) - w * 0.15)

        self.positionChanged.emit(cur)
        self.update()

    # ─── SFX ───

    def _preview_sfx(self, t0, t1):
        if t0 >= t1 or not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        
        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            # Apply keyframes before the measure
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM:
                            bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE:
                            ml = kf.value
                            
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            
            if t + dur > t0:
                ns = m.notes
                if ns:
                    step = dur / len(ns)
                    for j, n in enumerate(ns):
                        if n.note_type == NoteType.NONE:
                            continue
                        nt_t = t + j * step
                        if t0 <= nt_t < t1:
                            self._play_sfx(n.note_type)
            t += dur
            if t > t1:
                break

    def _play_sfx(self, nt: NoteType):
        if nt in (NoteType.DON, NoteType.DAI_DON):
            self.audio.play_sfx("don")
        elif nt in (NoteType.KA, NoteType.DAI_KA):
            self.audio.play_sfx("ka")
        elif nt in (NoteType.BALLOON, NoteType.KUSUDAMA):
            self.audio.play_sfx("balloon")
        elif nt in (NoteType.DRUMROLL, NoteType.DAI_DRUMROLL):
            self.audio.play_sfx("don")

    # ─── Paint ───

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, COL_BG)
        p.fillRect(0, self.TRACK_TOP, w, h - self.TRACK_TOP, COL_TRACK)

        if not self.song or not self.course:
            # Premium empty state
            p.setPen(Qt.NoPen)
            grad = QLinearGradient(0, h * 0.3, 0, h * 0.7)
            grad.setColorAt(0, QColor(0, 220, 180, 8))
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(grad)
            p.drawRect(0, 0, w, h)
            p.setPen(QColor("#444"))
            p.setFont(QFont("Segoe UI", 16, QFont.Light))
            p.drawText(self.rect(), Qt.AlignCenter, "拖放 TJA 或 OGG 文件到此处")
            p.setPen(QColor("#2a2a2a"))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(0, h * 0.55, w, 30), Qt.AlignHCenter, "或使用 文件 → 打开谱面 / 打开音频")
            p.end()
            return

        s_ms = self.screen_to_ms(0)
        e_ms = self.screen_to_ms(w)
        note_y = self._note_mid_y

        # Waveform (cached)
        wf_h = self._note_band_y - self.TRACK_TOP
        wf_mid = self.TRACK_TOP + wf_h / 2
        self._draw_waveform(p, s_ms, e_ms, wf_mid, wf_h, w)

        # Grid (full height)
        self._draw_grid(p, s_ms, e_ms, w, h)

        # Note track band
        band_y = self._note_band_y
        # Subtle top gradient on the note band
        band_grad = QLinearGradient(0, band_y, 0, band_y + self.NOTE_BAND_H)
        band_grad.setColorAt(0, QColor(28, 30, 45, 240))
        band_grad.setColorAt(1, QColor(22, 24, 35, 200))
        p.fillRect(QRectF(0, band_y, w, self.NOTE_BAND_H), band_grad)
        p.setPen(QPen(COL_NOTE_BAND_BORDER, 1))
        p.drawLine(0, int(band_y), w, int(band_y))
        p.drawLine(0, int(band_y + self.NOTE_BAND_H), w, int(band_y + self.NOTE_BAND_H))
        # Label
        p.setPen(QColor("#383850"))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(4, int(band_y + 12), "♪ Notes")

        # Notes
        self._draw_notes(p, s_ms, e_ms, note_y)

        # GoGo highlighting
        self._draw_gogo(p, s_ms, e_ms, h)

        # KF + Ruler
        self._draw_kf_lane(p, s_ms, e_ms)
        self._draw_ruler(p, s_ms, e_ms)

        # Drag preview (Pen)
        if self._drag_mode == "pen" and self.current_note_type.is_long:
            x1 = self.world_x(self._drag_start_ms)
            x2 = self.world_x(self._drag_end_ms)
            if x2 < x1: x1, x2 = x2, x1
            col = NOTE_COLORS.get(self.current_note_type, QColor("#ffa502"))
            ca = QColor(col); ca.setAlpha(80)
            p.fillRect(QRectF(x1, note_y - 14, x2 - x1, 28), ca)
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x1, note_y), self.NOTE_RADIUS, self.NOTE_RADIUS)
            p.setBrush(QColor("#747d8c"))
            p.drawEllipse(QPointF(x2, note_y), self.NOTE_RADIUS, self.NOTE_RADIUS)

        # Selection Box
        if self._drag_mode == "box":
            p.setPen(QPen(QColor(0, 212, 170), 1, Qt.DashLine))
            p.setBrush(QColor(0, 212, 170, 30))
            p.drawRect(self._selection_rect)

        # Move Ghosts
        if self._drag_mode == "move" and self.selected_notes:
            delta = self._move_delta_ms
            p.setPen(QColor("#fff"))
            cur_x = self.mapFromGlobal(self.cursor().pos()).x()
            p.drawText(cur_x + 15, int(note_y - 25), f"{delta:+.0f} ms")

        # Playhead
        px = self.world_x(self.cursor_ms)
        if -5 <= px <= w + 5:
            grad = QLinearGradient(px - 6, 0, px + 6, 0)
            grad.setColorAt(0, QColor(0, 212, 170, 0))
            grad.setColorAt(0.5, QColor(0, 212, 170, 20))
            grad.setColorAt(1, QColor(0, 212, 170, 0))
            p.fillRect(QRectF(px - 6, 0, 12, h), grad)
            p.setPen(QPen(COL_PLAYHEAD, 2))
            p.drawLine(int(px), 0, int(px), h)
            tri = QPainterPath()
            tri.moveTo(px - 5, 0); tri.lineTo(px + 5, 0); tri.lineTo(px, 7)
            tri.closeSubpath()
            p.setBrush(COL_PLAYHEAD); p.setPen(Qt.NoPen)
            p.drawPath(tri)

        p.end()

    def _draw_waveform(self, p, s_ms, e_ms, mid_y, track_h, w):
        if not self.audio.loaded:
            return

        margin_ms = self.px_to_ms(w)  # cache 1x extra each side = 3x total
        need = (
            self._wc_pix is None
            or s_ms < self._wc_s_ms
            or e_ms > self._wc_e_ms
            or abs(self._wc_zoom - self.zoom) > 0.01
            or self._wc_h != int(track_h)
        )

        if need:
            cs = max(0, s_ms - margin_ms)
            ce = e_ms + margin_ms
            cw = max(1, int(self.ms_to_px(ce - cs)))
            cw = min(cw, 6000)  # cap to prevent huge allocations

            pix = QPixmap(cw, int(track_h))
            pix.fill(Qt.transparent)
            wp = QPainter(pix)
            wp.setRenderHint(QPainter.Antialiasing)

            upper, lower = self.audio.get_waveform_peaks(cs, ce, cw)
            local_mid = track_h / 2
            factor = track_h * 0.4
            step = max(1, cw // 800)  # reduce points for large caches

            path = QPainterPath()
            path.moveTo(0, local_mid)
            for i in range(0, cw, step):
                path.lineTo(i, local_mid - upper[i] * factor)
            path.lineTo(cw - 1, local_mid)
            for i in range(cw - 1, -1, -step):
                path.lineTo(i, local_mid - lower[i] * factor)
            path.closeSubpath()

            wp.setPen(Qt.NoPen)
            wp.setBrush(COL_WAVE_FILL)
            wp.drawPath(path)

            wp.setPen(QPen(COL_WAVE_LINE, 1))
            wp.setBrush(Qt.NoBrush)
            outline = QPainterPath()
            outline.moveTo(0, local_mid)
            for i in range(0, cw, step):
                outline.lineTo(i, local_mid - upper[i] * factor)
            wp.drawPath(outline)
            wp.end()

            self._wc_pix = pix
            self._wc_s_ms = cs
            self._wc_e_ms = ce
            self._wc_zoom = self.zoom
            self._wc_h = int(track_h)

        # Blit the relevant portion
        off = int(self.ms_to_px(s_ms - self._wc_s_ms))
        p.drawPixmap(0, self.TRACK_TOP, self._wc_pix, off, 0, w, int(track_h))

    def _draw_ruler(self, p, s_ms, e_ms):
        w = self.width()
        # Gradient ruler background
        ruler_grad = QLinearGradient(0, 0, 0, self.RULER_H)
        ruler_grad.setColorAt(0, QColor("#1e1e22"))
        ruler_grad.setColorAt(1, QColor("#16161a"))
        p.fillRect(0, 0, w, self.RULER_H, ruler_grad)
        # Bottom edge accent
        p.setPen(QPen(QColor("#2a2a30"), 1))
        p.drawLine(0, self.RULER_H, w, self.RULER_H)
        p.setFont(QFont("Segoe UI", 9))
        ss = max(0, int(s_ms / 1000))
        for s in range(ss, int(e_ms / 1000) + 1):
            x = self.world_x(s * 1000)
            if x < -50 or x > w + 50:
                continue
            # Tick mark
            p.setPen(QColor("#3a3a44"))
            p.drawLine(int(x), self.RULER_H - 8, int(x), self.RULER_H)
            # Time label
            p.setPen(QColor("#606070"))
            p.drawText(int(x) + 4, self.RULER_H - 8, f"{s // 60}:{s % 60:02d}")

    def _draw_grid(self, p, s_ms, e_ms, w, h):
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        p.setFont(QFont("Segoe UI", 8))

        # Build keyframe lookup
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)

        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM:
                            bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE:
                            ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml

            if t + dur > s_ms and t < e_ms:
                x = self.world_x(t)
                p.setPen(QPen(COL_GRID_MEAS, 1))
                p.drawLine(int(x), self.TRACK_TOP, int(x), h - 20)
                p.setPen(QColor("#4a4a4a"))
                p.drawText(int(x) + 3, h - 5, str(i + 1))
                # Beat lines
                for b in range(1, int(ml)):
                    bx = self.world_x(t + b * beat_ms)
                    p.setPen(QPen(COL_GRID_BEAT, 1, Qt.DotLine))
                    p.drawLine(int(bx), self.TRACK_TOP, int(bx), h - 20)
                # Subdivision lines (based on snap_divisor)
                if self.snap_divisor > 4:
                    sub_count = self.snap_divisor
                    sub_ms = dur / sub_count
                    px_step = self.ms_to_px(sub_ms)
                    if px_step > 6:  # Only draw if wide enough to see
                        p.setPen(QPen(COL_GRID_SUB, 1, Qt.DotLine))
                        for si in range(1, sub_count):
                            # Skip if coincides with beat line
                            if ml > 0 and (si * sub_ms) % beat_ms < 0.5:
                                continue
                            sx = self.world_x(t + si * sub_ms)
                            p.drawLine(int(sx), self.TRACK_TOP, int(sx), h - 20)
            t += dur
            if t > e_ms:
                break

    def _draw_notes(self, p, s_ms, e_ms, mid_y):
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        open_long = []

        # Build keyframe lookup
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)

        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM:
                            bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE:
                            ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml

            if t + dur > s_ms - 3000 and t < e_ms:
                ns = m.notes
                if ns:
                    step = dur / len(ns)
                    for j, n in enumerate(ns):
                        nt = n.note_type
                        nt_t = t + j * step
                        x = self.world_x(nt_t)

                        if nt == NoteType.END:
                            if open_long:
                                info = open_long.pop(0)
                                sx = info["x"]
                                col = NOTE_COLORS.get(info["type"], QColor("#ffa502"))
                                cb = QColor(col); cb.setAlpha(90)
                                p.setPen(Qt.NoPen); p.setBrush(cb)
                                p.drawRoundedRect(QRectF(sx, mid_y - 10, x - sx, 20), 4, 4)
                                p.setBrush(QColor("#747d8c"))
                                p.drawEllipse(QPointF(x, mid_y), 8, 8)
                            continue
                        if nt == NoteType.NONE:
                            continue
                        if nt.is_long:
                            open_long.append({"type": nt, "x": x})

                        col = NOTE_COLORS.get(nt, QColor("#fff"))
                        r = self.NOTE_RADIUS
                        if nt in (NoteType.DAI_DON, NoteType.DAI_KA, NoteType.DAI_DRUMROLL):
                            r = int(r * 1.4)

                        # Shadow
                        p.setBrush(QColor(0, 0, 0, 50)); p.setPen(Qt.NoPen)
                        p.drawEllipse(QPointF(x + 1, mid_y + 2), r, r)
                        # Gradient circle
                        grad = QLinearGradient(x - r, mid_y - r, x + r, mid_y + r)
                        grad.setColorAt(0, col.lighter(120))
                        grad.setColorAt(1, col.darker(110))
                        p.setBrush(grad)
                        p.setPen(QPen(col.darker(140), 1.5))
                        p.drawEllipse(QPointF(x, mid_y), r, r)

                        if n in self.selected_notes:
                            p.setPen(QPen(QColor("#00d4aa"), 2.5)); p.setBrush(Qt.NoBrush)
                            p.drawEllipse(QPointF(x, mid_y), r + 4, r + 4)
            t += dur
            if t > e_ms:
                break

    def _draw_kf_lane(self, p, s_ms, e_ms):
        y0 = self.RULER_H
        # Gradient lane background
        lane_grad = QLinearGradient(0, y0, 0, y0 + self.KF_LANE_H)
        lane_grad.setColorAt(0, QColor("#1c1c22"))
        lane_grad.setColorAt(1, QColor("#18181e"))
        p.fillRect(0, y0, self.width(), self.KF_LANE_H, lane_grad)
        p.setPen(QPen(QColor("#2a2a30"), 1))
        p.drawLine(0, y0 + self.KF_LANE_H, self.width(), y0 + self.KF_LANE_H)
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        cy = y0 + self.KF_LANE_H / 2
        for i, m in enumerate(self.course.measures):
            kfs = [k for k in self.course.keyframes if k.measure_index == i]
            for kf in kfs:
                if kf.kf_type == KeyframeType.BPM and kf.sub_position == 0:
                    bpm = kf.value
                if kf.kf_type == KeyframeType.MEASURE and kf.sub_position == 0:
                    ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            for kf in kfs:
                if s_ms <= t <= e_ms:
                    x = self.world_x(t)
                    col = QColor(kf.kf_type.color_hex)
                    # Draw diamond
                    path = QPainterPath()
                    s = 6
                    path.moveTo(x, cy - s); path.lineTo(x + s, cy)
                    path.lineTo(x, cy + s); path.lineTo(x - s, cy)
                    path.closeSubpath()
                    p.setBrush(col); p.setPen(QPen(col.darker(130), 1))
                    p.drawPath(path)
                    # Draw value label for BPM changes
                    if kf.kf_type == KeyframeType.BPM:
                        p.setPen(QColor("#ff8a65"))
                        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
                        label = f"{kf.value:.1f}" if kf.value % 1 else f"{int(kf.value)}"
                        p.drawText(int(x) + 8, int(cy) + 4, f"BPM {label}")
                    elif kf.kf_type == KeyframeType.SCROLL:
                        p.setPen(QColor("#80cbc4"))
                        p.setFont(QFont("Segoe UI", 7))
                        p.drawText(int(x) + 8, int(cy) + 4, f"x{kf.value:.2f}")
            t += dur
            if t > e_ms:
                break

    def _draw_gogo(self, p, s_ms, e_ms, h):
        """Draw green highlighted band during GoGo Time sections."""
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        in_gogo = False
        gogo_start_ms = 0.0

        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
                    elif kf.kf_type == KeyframeType.GOGO_START:
                        if not in_gogo:
                            in_gogo = True
                            gogo_start_ms = t
                    elif kf.kf_type == KeyframeType.GOGO_END:
                        if in_gogo:
                            in_gogo = False
                            x1 = self.world_x(gogo_start_ms)
                            x2 = self.world_x(t)
                            if x2 > 0 and x1 < self.width():
                                p.fillRect(QRectF(x1, self.TRACK_TOP, x2 - x1, h - self.TRACK_TOP - 20), COL_GOGO_BAND)
                                p.setPen(QPen(COL_GOGO_LINE, 2))
                                p.drawLine(int(x1), self.TRACK_TOP, int(x1), h - 20)
                                p.drawLine(int(x2), self.TRACK_TOP, int(x2), h - 20)
                                # Label
                                p.setPen(COL_GOGO_LINE)
                                p.setFont(QFont("Segoe UI", 8, QFont.Bold))
                                p.drawText(int(x1) + 4, self.TRACK_TOP + 14, "GoGo!")
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            t += dur
            if t > e_ms + 5000 and not in_gogo:
                break

        # If still in gogo at the end, draw to the edge
        if in_gogo:
            x1 = self.world_x(gogo_start_ms)
            x2 = self.width()
            if x1 < self.width():
                p.fillRect(QRectF(x1, self.TRACK_TOP, x2 - x1, h - self.TRACK_TOP - 20), COL_GOGO_BAND)
                p.setPen(QPen(COL_GOGO_LINE, 2))
                p.drawLine(int(x1), self.TRACK_TOP, int(x1), h - 20)
                p.setPen(COL_GOGO_LINE)
                p.setFont(QFont("Segoe UI", 8, QFont.Bold))
                p.drawText(int(x1) + 4, self.TRACK_TOP + 14, "GoGo!")

    # ─── Events ───

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Delete and self.selected_notes:
            self.delete_selected()
            ev.accept()
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev: QMouseEvent):
        pos = ev.pos()
        ms = self.screen_to_ms(pos.x())
        
        if ev.button() == Qt.RightButton:
            return # Let context menu handle

        if self.edit_mode == "pen":
            self._drag_mode = "pen"
            self._drag_start_ms = ms
            self._drag_end_ms = ms
            return

        item = self._item_at(pos)
        if item:
            # Clicked Note
            if ev.modifiers() & Qt.ControlModifier:
                if item in self.selected_notes: self.selected_notes.remove(item)
                else: self.selected_notes.append(item)
            else:
                if item not in self.selected_notes:
                    self.selected_notes = [item]
                self._drag_mode = "move"
                self._drag_start_ms = ms
                self._move_delta_ms = 0.0
                self._drag_orig_ms = {n: self._get_note_ms(n) for n in self.selected_notes}
        else:
            # Clicked Empty
            if not (ev.modifiers() & Qt.ControlModifier):
                self.selected_notes = []
            self._drag_mode = "box"
            self._drag_start_pos = pos
            self._selection_rect = QRectF(pos, pos)
        
        if self._drag_mode not in ("move", "pen"):
            self.cursor_ms = max(0, ms)
            if not self.audio.is_playing: self.audio.seek(self.cursor_ms)
        self.update()

    def mouseMoveEvent(self, ev: QMouseEvent):
        ms = self.screen_to_ms(ev.x())

        if self._drag_mode == "pen":
            self._drag_end_ms = ms
            self.update()

        elif self._drag_mode == "box":
            p = ev.pos()
            o = self._drag_start_pos
            self._selection_rect = QRectF(o, p).normalized()
            self._select_in_rect(self._selection_rect)
            self.update()

        elif self._drag_mode == "move":
            raw = ms - self._drag_start_ms
            if self.snap_divisor > 0 and self.selected_notes:
                ref_ms = self._drag_orig_ms.get(self.selected_notes[0], 0)
                bpm = self._get_bpm_at(ref_ms)
                grid = (60000.0 / bpm) * (4.0 / self.snap_divisor)
                self._move_delta_ms = round(raw / grid) * grid
            else:
                self._move_delta_ms = raw
            self.update()

    def mouseReleaseEvent(self, ev: QMouseEvent):
        ms = self.screen_to_ms(ev.x())

        if self._drag_mode == "pen":
            s, e = self._drag_start_ms, self._drag_end_ms
            if s > e: s, e = e, s
            self._ensure_measures(s)
            self._place_note_at_snap(s, self.current_note_type, e if e - s > 30 else None)

        elif self._drag_mode == "move":
            if abs(self._move_delta_ms) > 1:
                self._commit_move()
        
        self._drag_mode = "none"
        self.update()


    def _item_at(self, pos: QPointF) -> Optional[Note]:
        ms = self.screen_to_ms(pos.x())
        y = pos.y()
        if abs(y - self._note_mid_y) > 20: return None
        if not self.course: return None
        
        t = -(self.song.offset * 1000)
        bpm = self.song.bpm
        ml = 4.0
        
        # Optimized scan around viewport
        s_ms = ms - 100; e_ms = ms + 100
        
        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            
            if t + dur > s_ms and t < e_ms:
                if m.notes and len(m.notes) > 0:
                    step = dur / len(m.notes)
                    for j, n in enumerate(m.notes):
                        if n.note_type == NoteType.NONE: continue
                        nx = self.world_x(t + j * step)
                        if abs(nx - pos.x()) < 15:
                            return n
            t += dur
        return None

    def _select_in_rect(self, rect: QRectF):
        self.selected_notes = []
        if not self.course: return
        t = -(self.song.offset * 1000)
        bpm = self.song.bpm
        ml = 4.0
        
        s_ms = self.screen_to_ms(rect.left())
        e_ms = self.screen_to_ms(rect.right())
        
        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            
            if t + dur > s_ms and t < e_ms:
                if m.notes and len(m.notes) > 0:
                    step = dur / len(m.notes)
                    for j, n in enumerate(m.notes):
                         if n.note_type == NoteType.NONE: continue
                         nt_t = t + j * step
                         if s_ms <= nt_t <= e_ms:
                             self.selected_notes.append(n)
            t += dur

    def _get_note_ms(self, target):
        if not self.course: return 0
        t = -(self.song.offset * 1000)
        bpm = self.song.bpm
        ml = 4.0
        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            if target in m.notes:
                step = dur / len(m.notes)
                return t + m.notes.index(target) * step
            t += dur
        return 0

    def _commit_move(self):
        delta = self._move_delta_ms
        if delta == 0: return
        
        to_move = []
        for n in self.selected_notes:
            ms = self._drag_orig_ms.get(n, 0)
            to_move.append((ms, n.note_type, n.balloon_hits))
        
        self.delete_selected()
        
        new_sel = []
        for ms, ntype, bh in to_move:
            self._place_note_at_snap(ms + delta, ntype)
            if self.selected_obj:
               self.selected_obj.balloon_hits = bh
               new_sel.append(self.selected_obj)
        self.selected_notes = new_sel
        self._move_delta_ms = 0

    def _get_bpm_at(self, ms):
        if not self.course: return self.song.bpm
        t = -(self.song.offset * 1000)
        bpm = self.song.bpm
        ml = 4.0
        last = bpm
        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            if t > ms: return last
            last = bpm
            t += dur
        return last

    def _measure_at_ms(self, ms):
        """Return (measure_start_ms, bpm, measure_length_in_beats) for the measure containing ms."""
        if not self.course:
            return 0, self.song.bpm, 4.0
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        # Build keyframe lookup for efficiency
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)
            
        for i, m in enumerate(self.course.measures):
            if i in kf_map:
                for kf in kf_map[i]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM:
                            bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE:
                            ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            if t <= ms < t + dur:
                return t, bpm, ml
            t += dur
        return t, bpm, ml

    def _place_note_at_snap(self, ms, ntype, end_ms=None):
        if self.snap_divisor > 0:
            # Use measure-local grid snapping to handle BPM changes correctly
            meas_start, bpm, ml = self._measure_at_ms(ms)
            grid = (60000.0 / bpm) * (ml / self.snap_divisor)
            offset_in_meas = ms - meas_start
            ms = meas_start + round(offset_in_meas / grid) * grid
            if end_ms:
                es, ebpm, eml = self._measure_at_ms(end_ms)
                egrid = (60000.0 / ebpm) * (eml / self.snap_divisor)
                end_ms = es + round((end_ms - es) / egrid) * egrid
        self._place_note_at(ms, ntype, end_ms)

    def _add_event(self, ms, ktype):
        from PyQt5.QtWidgets import QInputDialog
        if ktype == "bpm":
            title = "添加 BPM 变化"
            label = "新 BPM 值:"
            default = self._get_bpm_at(ms)
        else:
            title = "添加 SCROLL 变化"
            label = "SCROLL 倍率:"
            default = 1.0
        val, ok = QInputDialog.getDouble(self, title, label, default, 1.0, 999.0, 2)
        if ok and self.course:
            # Find meas
            t = -(self.song.offset * 1000)
            bpm = self.song.bpm
            ml = 4.0
            for i, m in enumerate(self.course.measures):
                for kf in self.course.keyframes:
                    if kf.measure_index == i and kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
                beat_ms = 60000.0 / bpm
                dur = beat_ms * ml
                if t <= ms < t + dur:
                   # Add here
                   kf = Keyframe(
                       kf_type=KeyframeType.BPM if ktype=="bpm" else KeyframeType.SCROLL,
                       value=val,
                       measure_index=i,
                       sub_position=0
                   )
                   self.course.keyframes.append(kf)
                   self.course.keyframes.sort(key=lambda k: (k.measure_index, k.sub_position))
                   break
                t += dur
        self.update()

    def _clear_events(self, ms):
        if not self.course: return
        t = -(self.song.offset * 1000)
        bpm = self.song.bpm
        ml = 4.0
        for i, m in enumerate(self.course.measures):
            for kf in self.course.keyframes:
                if kf.measure_index == i and kf.sub_position == 0:
                    if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                    elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            if t <= ms < t + dur:
                self.course.keyframes = [k for k in self.course.keyframes
                                         if not (k.measure_index == i and k.sub_position == 0)]
                break
            t += dur
        self.update()

    # ─── BPM Management API ───

    def add_bpm_at_cursor(self):
        """Add a BPM change at the current cursor position via dialog."""
        self._add_event(self.cursor_ms, "bpm")

    def get_bpm_changes(self):
        """Return list of (measure_index, bpm_value, ms_position) for all BPM keyframes."""
        result = []
        if not self.course:
            return result
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        # Add base BPM as first entry
        result.append((-1, self.song.bpm, t))
        for i, m in enumerate(self.course.measures):
            for kf in self.course.keyframes:
                if kf.measure_index == i and kf.sub_position == 0:
                    if kf.kf_type == KeyframeType.BPM:
                        bpm = kf.value
                        result.append((i, kf.value, t))
                    elif kf.kf_type == KeyframeType.MEASURE:
                        ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            t += dur
        return result

    def edit_bpm_at(self, measure_index, new_value):
        """Edit the BPM keyframe at a given measure index."""
        if not self.course:
            return
        if measure_index == -1:
            # Edit base BPM
            self.song.bpm = new_value
            return
        for kf in self.course.keyframes:
            if kf.measure_index == measure_index and kf.kf_type == KeyframeType.BPM:
                kf.value = new_value
                self.update()
                return

    def delete_bpm_at(self, measure_index):
        """Delete the BPM keyframe at a given measure index."""
        if not self.course or measure_index == -1:
            return  # cannot delete base BPM
        self.course.keyframes = [
            k for k in self.course.keyframes
            if not (k.measure_index == measure_index and k.kf_type == KeyframeType.BPM)
        ]
        self.update()

    def scroll_to_measure(self, measure_index):
        """Scroll timeline to center on the given measure."""
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        target_idx = max(0, measure_index)
        for i, m in enumerate(self.course.measures):
            for kf in self.course.keyframes:
                if kf.measure_index == i and kf.sub_position == 0:
                    if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                    elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            if i == target_idx:
                self.cursor_ms = max(0, t)
                self.scroll_x = max(0, self.ms_to_px(t) - self.width() * 0.3)
                if not self.audio.is_playing:
                    self.audio.seek(self.cursor_ms)
                self.update()
                return
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            t += dur

    def wheelEvent(self, ev: QWheelEvent):
        # Ctrl + Wheel = Zoom
        if ev.modifiers() & Qt.ControlModifier:
            factor = 1.12 if ev.angleDelta().y() > 0 else 1 / 1.12
            mx = ev.pos().x()
            anchor = self.screen_to_ms(mx)
            self.zoom *= factor
            self.zoom = max(50, min(3000, self.zoom))
            self.scroll_x = self.ms_to_px(anchor) - mx
            if self.scroll_x < 0: self.scroll_x = 0
            
        # Shift + Wheel = Horizontal Scroll (for mice without horizontal wheels)
        elif ev.modifiers() & Qt.ShiftModifier:
            self.scroll_x -= ev.angleDelta().y() * 0.8
            if self.scroll_x < 0: self.scroll_x = 0
            
        # Normal Wheel
        else:
            # Handle native horizontal scroll (trackpads, horizontal mice)
            if ev.angleDelta().x() != 0:
                self.scroll_x -= ev.angleDelta().x() * 0.8
            # In timelines, vertical scroll often maps to horizontal panning too
            elif ev.angleDelta().y() != 0:
                self.scroll_x -= ev.angleDelta().y() * 0.8
                
            if self.scroll_x < 0: self.scroll_x = 0

        self._wc_pix = None
        self.update()

    def contextMenuEvent(self, ev):
        menu = QMenu(self)
        ms = self.screen_to_ms(ev.x())
        
        y = ev.y()
        if self.RULER_H <= y <= self.RULER_H + self.KF_LANE_H:
             menu.addAction("➕ 添加BPM变化", lambda: self._add_event(ms, "bpm"))
             menu.addAction("➕ 添加SCROLL变化", lambda: self._add_event(ms, "scroll"))
             menu.addSeparator()
             menu.addAction("🗑 清除此处事件", lambda: self._clear_events(ms))
        
        if self.selected_notes:
             menu.addSeparator()
             menu.addAction("❌ 删除选中音符", self.delete_selected)
        elif not menu.actions():
             menu.addAction("🗑 删除音符", lambda: self._delete_at(ms))
        
        if not menu.actions():
            return
        menu.exec_(ev.globalPos())

    # ─── Helpers ───

    def delete_selected(self):
        if not self.course: return
        changed = False
        for m in self.course.measures:
            for i, n in enumerate(m.notes):
                if n in self.selected_notes:
                    m.notes[i] = Note(NoteType.NONE)
                    changed = True
        if changed:
            self.selected_notes = []
            self.update()


    # ─── Edit ───

    def _place_note_at(self, ms, note_type, end_ms=None):
        """Place a note at exact ms with adaptive subdivision."""
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)

        # Build keyframe lookup
        kf_map = {}
        for kf in self.course.keyframes:
            kf_map.setdefault(kf.measure_index, []).append(kf)

        for idx, m in enumerate(self.course.measures):
            if idx in kf_map:
                for kf in kf_map[idx]:
                    if kf.sub_position == 0:
                        if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                        elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml

            if t <= ms < t + dur:
                # Ensure minimum subdivision
                if not m.notes or (len(m.notes) == 1 and m.notes[0].note_type == NoteType.NONE):
                    m.notes = [Note() for _ in range(DEFAULT_SUBDIV)]
                # Auto-expand if existing measure is too coarse
                self._expand_subdiv(m, DEFAULT_SUBDIV)

                ns = m.notes
                step = dur / len(ns)
                si = int(round((ms - t) / step))
                si = max(0, min(si, len(ns) - 1))

                # Check quantization error — if too large, double subdivision
                quant_ms = abs((si * step + t) - ms)
                if quant_ms > QUANT_THRESHOLD_MS:
                    self._expand_subdiv(m, len(m.notes) * 2)
                    ns = m.notes
                    step = dur / len(ns)
                    si = int(round((ms - t) / step))
                    si = max(0, min(si, len(ns) - 1))

                ns[si].note_type = note_type

                if end_ms is not None and note_type.is_long:
                    ei = int(round((end_ms - t) / step))
                    ei = max(0, min(ei, len(ns) - 1))
                    if ei > si:
                        ns[ei].note_type = NoteType.END

                self.selected_obj = ns[si]
                self.selected_notes = [ns[si]]
                bi = self._balloon_idx(idx, si)
                self.noteSelected.emit(ns[si], self.course, idx, si, bi)
                return
            t += dur

    def _delete_at(self, ms):
        if not self.course:
            return
        bpm = self.song.bpm
        ml = 4.0
        t = -(self.song.offset * 1000)
        for idx, m in enumerate(self.course.measures):
            for kf in self.course.keyframes:
                if kf.measure_index == idx and kf.sub_position == 0:
                    if kf.kf_type == KeyframeType.BPM: bpm = kf.value
                    elif kf.kf_type == KeyframeType.MEASURE: ml = kf.value
            beat_ms = 60000.0 / bpm
            dur = beat_ms * ml
            if t <= ms < t + dur:
                ns = m.notes
                if ns:
                    step = dur / len(ns)
                    ni = int(round((ms - t) / step))
                    if 0 <= ni < len(ns):
                        ns[ni].note_type = NoteType.NONE
                self.update()
                return
            t += dur

    def _balloon_idx(self, tm, tn):
        c = 0
        for i, m in enumerate(self.course.measures):
            lim = len(m.notes) if i < tm else tn
            for j in range(lim):
                if m.notes[j].note_type in (NoteType.BALLOON, NoteType.KUSUDAMA):
                    c += 1
        return c
