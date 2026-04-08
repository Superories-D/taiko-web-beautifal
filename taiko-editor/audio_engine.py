"""
Audio engine for OGG playback, waveform data extraction, and SFX.
Uses pygame.mixer for playback and soundfile+numpy for waveform rendering.
"""
from __future__ import annotations
import os
import numpy as np
import soundfile as sf
import pygame


class AudioEngine:
    """Handles audio playback and waveform data."""

    def __init__(self):
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=1024)
        pygame.mixer.init()
        # Reserve channels for SFX so music doesn't interrupt them
        pygame.mixer.set_reserved(8)
        
        self._loaded = False
        self._filepath: str = ""
        self._pcm_data: np.ndarray | None = None
        self._sample_rate: int = 44100
        self._duration_ms: float = 0.0
        self._playing = False
        self._paused = False
        self._start_offset_ms: float = 0.0
        self._speed: float = 1.0

        # SFX
        self._sfx_sounds = {}
        self._load_sfx()

    def set_speed(self, speed: float):
        """Set playback speed (0.25 - 2.0). Restarts playback at current position."""
        self._speed = max(0.25, min(2.0, speed))
        if self._playing and not self._paused:
            cur = self.get_position_ms()
            self.stop()
            self.play(cur)

    def _load_sfx(self):
        """Load standard TJA sound effects."""
        import sys
        if getattr(sys, '_MEIPASS', None):
            base_path = os.path.join(sys._MEIPASS, "resources", "sfx")
        else:
            base_path = os.path.join(os.path.dirname(__file__), "resources", "sfx")
        sfx_map = {
            "don": "don.ogg",
            "ka": "ka.ogg",
            "balloon": "balloon.ogg"
        }
        for name, filename in sfx_map.items():
            path = os.path.join(base_path, filename)
            if os.path.exists(path):
                try:
                    self._sfx_sounds[name] = pygame.mixer.Sound(path)
                except Exception as e:
                    print(f"Failed to load SFX {name}: {e}")

    def play_sfx(self, name: str):
        """Play a sound effect by name (don, ka, balloon)."""
        if name in self._sfx_sounds:
            self._sfx_sounds[name].play()

    def load(self, filepath: str) -> bool:
        """Load an OGG file. Returns True on success."""
        if not os.path.isfile(filepath):
            return False
            
        # Reset current state before loading new
        self._loaded = False
        self._pcm_data = None
        self._filepath = ""
        self._playing = False
        self.stop()
        
        try:
            # Load PCM data for waveform
            data, sr = sf.read(filepath, dtype="float32")
            if len(data.shape) > 1:
                # Mix to mono for waveform
                self._pcm_data = data.mean(axis=1)
            else:
                self._pcm_data = data
            self._sample_rate = sr
            self._duration_ms = len(self._pcm_data) / sr * 1000.0

            # Load for playback
            pygame.mixer.music.load(filepath)
            self._filepath = filepath
            self._loaded = True
            self._paused = False
            return True
        except Exception as e:
            print(f"AudioEngine.load error: {e}")
            self._pcm_data = None
            self._duration_ms = 0.0
            return False

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def duration_ms(self) -> float:
        return self._duration_ms

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def play(self, start_ms: float = 0.0):
        """Start playback from the given position."""
        if not self._loaded:
            return
        self._start_offset_ms = start_ms
        pygame.mixer.music.play(start=start_ms / 1000.0)
        self._playing = True
        self._paused = False

    def pause(self):
        """Pause playback."""
        if self._playing and not self._paused:
            pygame.mixer.music.pause()
            self._paused = True

    def unpause(self):
        """Resume paused playback."""
        if self._paused:
            pygame.mixer.music.unpause()
            self._paused = False

    def stop(self):
        """Stop playback."""
        pygame.mixer.music.stop()
        self._playing = False
        self._paused = False

    def seek(self, ms: float):
        """Seek to position. Restarts playback at new position."""
        if not self._loaded:
            return
        was_playing = self._playing and not self._paused
        self.stop()
        if was_playing:
            self.play(ms)
        else:
            self._start_offset_ms = ms

    def get_position_ms(self) -> float:
        """Get current playback position in milliseconds."""
        if not self._playing:
            return self._start_offset_ms
        # Detect end of track
        if not pygame.mixer.music.get_busy() and not self._paused:
            self._playing = False
            return self._start_offset_ms
        try:
            pos = pygame.mixer.music.get_pos()
        except pygame.error:
            return self._start_offset_ms
        if pos < 0:
            return self._start_offset_ms
        return self._start_offset_ms + pos

    @property
    def is_playing(self) -> bool:
        return self._playing and not self._paused

    def get_waveform_peaks(self, start_ms: float, end_ms: float,
                           num_points: int = 1000) -> tuple[np.ndarray, np.ndarray]:
        """
        Get positive and negative peaks for waveform rendering.
        Returns (upper_peaks, lower_peaks) arrays.
        """
        if self._pcm_data is None:
            return np.zeros(num_points), np.zeros(num_points)

        start_sample = max(0, int(start_ms / 1000.0 * self._sample_rate))
        end_sample = min(len(self._pcm_data),
                         int(end_ms / 1000.0 * self._sample_rate))

        if end_sample <= start_sample:
            return np.zeros(num_points), np.zeros(num_points)

        segment = self._pcm_data[start_sample:end_sample]

        if len(segment) <= num_points:
            result = np.zeros(num_points)
            result[:len(segment)] = segment
            return np.maximum(result, 0), np.minimum(result, 0)

        chunk_size = len(segment) // num_points
        trimmed = segment[:chunk_size * num_points]
        chunks = trimmed.reshape(num_points, chunk_size)

        upper = np.max(chunks, axis=1)
        lower = np.min(chunks, axis=1)
        return upper, lower

    def cleanup(self):
        """Clean up resources."""
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
