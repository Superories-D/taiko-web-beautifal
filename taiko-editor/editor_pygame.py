"""
Main Editor Application (Pygame Version).
Replaces the PySide6 implementation.
"""
import sys
import os
import math
import pygame
from typing import Optional, List

# Ensure we can import modules from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models import Song, Course, Note, NoteType, Keyframe, KeyframeType, COURSE_NAMES
from audio_engine import AudioEngine
from tja_parser import parse_tja, serialize_tja
from ui import Button, Label, TextInput

# Constants
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

# Colors
COLOR_BG = (26, 26, 46)
COLOR_TIMELINE_BG = (22, 33, 62)
COLOR_GRID_MEASURE = (78, 78, 110)
COLOR_GRID_BEAT = (42, 42, 78)
COLOR_PLAYHEAD = (233, 69, 96)
COLOR_TEXT = (255, 255, 255)

class PygameEditor:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Taiko Editor (Pygame)")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 14)
        
        self.audio = AudioEngine()
        self.song = Song()
        self.current_course_name = "oni"
        self.current_course = self.song.get_or_create_course(self.current_course_name)
        
        # Timeline State
        self.scroll_x = 0
        self.zoom = 200.0 # px/sec
        self.cursor_ms = 0.0
        self.is_playing = False
        self.last_cursor_ms = 0.0
        self.dragging = False
        self.drag_start = None # (x, y)
        self.drag_start_ms = 0
        
        # Tools
        self.current_note_type = NoteType.DON
        self.selected_note = None
        self.preview_enabled = True
        
        # UI Elements
        self._init_ui()
        
    def _init_ui(self):
        self.ui_elements = []
        
        # Toolbar (Top)
        y = 10
        x = 10
        self.btn_load = Button(x, y, 80, 30, "Load TJA", self.action_load_tja)
        self.ui_elements.append(self.btn_load)
        x += 90
        self.btn_save = Button(x, y, 80, 30, "Save TJA", self.action_save_tja)
        self.ui_elements.append(self.btn_save)
        x += 100
        self.btn_play = Button(x, y, 60, 30, "Play", self.action_toggle_play)
        self.ui_elements.append(self.btn_play)
        x += 70
        self.btn_stop = Button(x, y, 60, 30, "Stop", self.action_stop)
        self.ui_elements.append(self.btn_stop)
        x += 80
        self.lbl_sfx = Label(x, y+5, "Preview:")
        self.ui_elements.append(self.lbl_sfx)
        self.btn_toggle_sfx = Button(x+60, y, 40, 30, "ON", self.action_toggle_sfx)
        self.ui_elements.append(self.btn_toggle_sfx)

        # Note Palette (Top Row 2)
        y = 50
        x = 10
        note_types = [
            (NoteType.DON, "Don", (242, 60, 60)),
            (NoteType.KA, "Ka", (60, 125, 242)),
            (NoteType.DAI_DON, "DaiDon", (242, 60, 60)),
            (NoteType.DAI_KA, "DaiKa", (60, 125, 242)),
            (NoteType.DRUMROLL, "Roll", (242, 201, 60)),
            (NoteType.DAI_DRUMROLL, "DaiRoll", (242, 201, 60)),
            (NoteType.BALLOON, "Balloon", (242, 142, 60)),
        ]
        
        self.note_buttons = []
        for nt, label, col in note_types:
            btn = Button(x, y, 60, 30, label, lambda n=nt: self.set_tool(n), color=col)
            self.ui_elements.append(btn)
            self.note_buttons.append(btn)
            x += 65
            
        # Course Tabs (Bottom)
        y = SCREEN_HEIGHT - 40
        x = 10
        for name in COURSE_NAMES:
            btn = Button(x, y, 60, 30, name.capitalize(), lambda n=name: self.set_course(n))
            self.ui_elements.append(btn)
            x += 70
            
    def set_tool(self, nt):
        self.current_note_type = nt
        # highlight button logic could be added
        
    def set_course(self, name):
        self.current_course_name = name
        self.current_course = self.song.get_or_create_course(name)
        
    def action_load_tja(self):
        # Pygame doesn't have native file dialogs easily. 
        # For now, just try to load 'test.tja' or print console instruction
        print("To load files in Pygame mode without Tkinter, drag and drop support is best.")
        # We Implement Drag & Drop in event loop

    def action_save_tja(self):
        try:
            with open("output.tja", "w", encoding="utf-8") as f:
                f.write(serialize_tja(self.song))
            print("Saved to output.tja")
        except Exception as e:
            print(f"Save failed: {e}")
            
    def action_toggle_play(self):
        if self.audio.is_playing:
            self.audio.pause()
            self.btn_play.text = "Play"
        else:
            if self.cursor_ms >= self.audio.duration_ms: self.cursor_ms = 0
            self.audio.play(self.cursor_ms)
            self.btn_play.text = "Pause"
            
    def action_stop(self):
        self.audio.stop()
        self.cursor_ms = 0
        self.btn_play.text = "Play"
        
    def action_toggle_sfx(self):
        self.preview_enabled = not self.preview_enabled
        self.btn_toggle_sfx.text = "ON" if self.preview_enabled else "OFF"

    def run(self):
        running = True
        while running:
            # Event Loop
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.DROPFILE:
                    self.load_file(event.file)
                elif event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                    # Update UI positions if needed (simple responsive)
                elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.KEYDOWN):
                    # UI handling
                    handled = False
                    for el in self.ui_elements:
                        if el.handle_event(event):
                            handled = True
                    
                    if not handled:
                        self.handle_timeline_event(event)

            # Update
            self.update()
            
            # Draw
            self.draw()
            
            pygame.display.flip()
            self.clock.tick(FPS)
            
        pygame.quit()
        sys.exit()

    def update(self):
        if self.audio.is_playing:
            current_ms = self.audio.get_position_ms()
            if self.preview_enabled and self.current_course:
                self._check_preview_sfx(self.last_cursor_ms, current_ms)
            self.cursor_ms = current_ms
            self.last_cursor_ms = current_ms
            
            # Autoscroll
            t_center = self.px_to_ms(self.scroll_x + SCREEN_WIDTH/2)
            if self.cursor_ms > t_center + 1000:
                self.scroll_x += (self.cursor_ms - t_center) / 1000 * self.zoom * 0.1
        else:
            self.last_cursor_ms = self.cursor_ms

    def load_file(self, filepath):
        if filepath.lower().endswith(".tja"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self.song = parse_tja(f.read())
                self.set_course("oni")
                # Try load wave
                if self.song.wave:
                    base = os.path.dirname(filepath)
                    audio_path = os.path.join(base, self.song.wave)
                    if os.path.exists(audio_path):
                        self.audio.load(audio_path)
            except Exception as e:
                print(f"Error loading TJA: {e}")
        elif filepath.lower().endswith((".ogg", ".wav", ".mp3")):
            self.audio.load(filepath)
            self.song.wave = os.path.basename(filepath)

    # ─── Timeline Logic ───
    
    def handle_timeline_event(self, event):
        # Defines timeline area
        timeline_rect = pygame.Rect(0, 100, self.screen.get_width(), 300)
        
        if event.type == pygame.MOUSEWHEEL:
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                 self.zoom *= 1.1 if event.y > 0 else 0.9
                 self.zoom = max(50, min(2000, self.zoom))
            else:
                self.scroll_x -= event.y * 50
                if self.scroll_x < 0: self.scroll_x = 0
                
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if timeline_rect.collidepoint(event.pos):
                if event.button == 1: # Left click
                    ms = self.px_to_ms(event.pos[0] + self.scroll_x)
                    self.drag_start = event.pos
                    self.drag_start_ms = ms
                    self.dragging = True
                    self.cursor_ms = ms # seek
                    if not self.audio.is_playing:
                        self.audio.seek(self.cursor_ms)
                elif event.button == 3: # Right click
                    # Delete note? 
                    pass

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and self.dragging:
                self.dragging = False
                end_ms = self.px_to_ms(event.pos[0] + self.scroll_x)
                if abs(end_ms - self.drag_start_ms) < 50: # Click
                    self.place_note(self.drag_start_ms, self.drag_start_ms)
                else: # Drag
                    self.place_note(min(self.drag_start_ms, end_ms), max(self.drag_start_ms, end_ms))

        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                # Preview drag
                pass

    def place_note(self, start_ms, end_ms):
        if not self.current_course: return
        # Logic similar to widget: find measure, quantize, insert
        # Simplified:
        # 1. Find measure via time
        bpm = self.song.bpm
        meas_len = 4.0
        t = -(self.song.offset * 1000)
        
        for m in self.current_course.measures:
            # Check KFs (omitted for brevity, assume constant BPM for MVP)
            ms_beat = 60000.0 / bpm
            dur = ms_beat * meas_len
            
            if t <= start_ms < t + dur:
                # Found measure
                notes = m.notes
                # check size, default 16
                if not notes or (len(notes)==1 and notes[0].note_type==NoteType.NONE):
                    m.notes = [Note() for _ in range(16)]
                    notes = m.notes
                
                step = dur / len(notes)
                idx_start = int((start_ms - t) / step)
                if 0 <= idx_start < len(notes):
                    notes[idx_start].note_type = self.current_note_type
                    self._play_sfx_for_note(self.current_note_type)
                    
                    if self.current_note_type.is_long and end_ms > start_ms + step:
                         idx_end = int((end_ms - t) / step)
                         if idx_end >= len(notes): idx_end = len(notes)-1
                         if idx_end > idx_start:
                             notes[idx_end].note_type = NoteType.END
                return
            t += dur

    def _check_preview_sfx(self, start_ms, end_ms):
        # Same logic as widget
        if start_ms >= end_ms: return
        bpm = self.song.bpm
        meas_len = 4.0
        t = -(self.song.offset * 1000)
        
        for m in self.current_course.measures:
            ms_beat = 60000.0 / bpm
            dur = ms_beat * meas_len
            
            if t + dur > start_ms:
                if m.notes:
                    step = dur / len(m.notes)
                    for i, n in enumerate(m.notes):
                        if n.note_type == NoteType.NONE: continue
                        nt = t + i*step
                        if start_ms <= nt < end_ms:
                            self._play_sfx_for_note(n.note_type)
            t += dur
            if t > end_ms: break

    def _play_sfx_for_note(self, nt):
        if nt in (NoteType.DON, NoteType.DAI_DON): self.audio.play_sfx("don")
        elif nt in (NoteType.KA, NoteType.DAI_KA): self.audio.play_sfx("ka")
        elif nt in (NoteType.BALLOON, NoteType.KUSUDAMA): self.audio.play_sfx("balloon")
        elif nt in (NoteType.DRUMROLL, NoteType.DAI_DRUMROLL): self.audio.play_sfx("don")

    # ─── Drawing ───

    def draw(self):
        self.screen.fill(COLOR_BG)
        
        # Draw Timeline Area
        timeline_y = 100
        pygame.draw.rect(self.screen, COLOR_TIMELINE_BG, (0, timeline_y, SCREEN_WIDTH, 300))
        mid_y = timeline_y + 150
        
        # Grid & Notes
        if self.current_course:
            self._draw_grid_and_notes(mid_y)
            
        # UI Overlays
        for el in self.ui_elements:
            el.draw(self.screen)
            
        # Playhead
        px = self.ms_to_px(self.cursor_ms) - self.scroll_x
        if 0 <= px <= SCREEN_WIDTH:
            pygame.draw.line(self.screen, COLOR_PLAYHEAD, (px, timeline_y), (px, timeline_y+300), 2)
            
    def _draw_grid_and_notes(self, mid_y):
        bpm = self.song.bpm
        meas_len = 4.0
        t = -(self.song.offset * 1000)
        
        # Screen range
        start_ms = self.px_to_ms(self.scroll_x)
        end_ms = self.px_to_ms(self.scroll_x + SCREEN_WIDTH)
        
        # Draw Waveform
        if self.audio.loaded:
            peaks_upper, peaks_lower = self.audio.get_waveform_peaks(start_ms, end_ms, SCREEN_WIDTH)
            # Pygame point list
            points = []
            for x, (u, l) in enumerate(zip(peaks_upper, peaks_lower)):
                # u, l are amplitude 0-1
                h = 100 # height scale
                points.append((x, mid_y - u*h))
                points.append((x, mid_y - l*h))
                # optimize: just draw vertical lines
                pygame.draw.line(self.screen, (40, 50, 80), (x, mid_y - u*h), (x, mid_y - l*h))
        
        open_long = []
        
        for i, m in enumerate(self.current_course.measures):
            # assume default bpm/meas for now
            ms_beat = 60000.0 / bpm
            dur = ms_beat * meas_len
            
            if t + dur > start_ms - 1000 and t < end_ms + 1000:
                # Measure line
                lx = self.ms_to_px(t) - self.scroll_x
                if -10 < lx < SCREEN_WIDTH + 10:
                    pygame.draw.line(self.screen, COLOR_GRID_MEASURE, (lx, mid_y-150), (lx, mid_y+150), 2)
                    label = self.font.render(str(i+1), True, (150, 150, 150))
                    self.screen.blit(label, (lx+5, mid_y+130))
                
                # Notes
                if m.notes:
                    step = dur / len(m.notes)
                    for j, n in enumerate(m.notes):
                        nt = n.note_type
                        nt_time = t + j*step
                        nx = self.ms_to_px(nt_time) - self.scroll_x
                        
                        if nt == NoteType.END:
                            if open_long:
                                start = open_long.pop(0)
                                sx = start['x']
                                sy = mid_y
                                col = (242, 201, 60) # yellow
                                if start['type'] == NoteType.BALLOON: col = (242, 142, 60) # orange
                                
                                rect = pygame.Rect(sx, sy-15, nx-sx, 30)
                                pygame.draw.rect(self.screen, col, rect)
                                pygame.draw.circle(self.screen, (150,150,150), (int(nx), int(sy)), 15)
                        elif nt.is_long:
                             open_long.append({'type': nt, 'x': nx, 't': nt_time})
                             self._draw_note(nx, mid_y, nt)
                        elif nt != NoteType.NONE:
                             self._draw_note(nx, mid_y, nt)
            
            t += dur
            if t > end_ms: break

    def _draw_note(self, x, y, nt):
        if not (-20 < x < SCREEN_WIDTH + 20): return
        col = (255, 255, 255)
        radius = 15
        if nt in (NoteType.DON, NoteType.DAI_DON): col = (242, 60, 60)
        elif nt in (NoteType.KA, NoteType.DAI_KA): col = (60, 125, 242)
        elif nt in (NoteType.DRUMROLL, NoteType.DAI_DRUMROLL): col = (242, 201, 60)
        elif nt in (NoteType.BALLOON, NoteType.KUSUDAMA): col = (242, 142, 60)
        
        if nt in (NoteType.DAI_DON, NoteType.DAI_KA, NoteType.DAI_DRUMROLL):
            radius = 22
            
        pygame.draw.circle(self.screen, col, (int(x), int(y)), radius)
        pygame.draw.circle(self.screen, (255,255,255), (int(x), int(y)), radius, 2) # outline

    def ms_to_px(self, ms):
        return ms / 1000.0 * self.zoom

    def px_to_ms(self, px):
        return px / self.zoom * 1000.0

if __name__ == "__main__":
    app = PygameEditor()
    app.run()
