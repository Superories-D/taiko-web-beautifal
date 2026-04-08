"""
Metdata editor panel.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, 
    QDoubleSpinBox, QGroupBox, QLabel
)
from PySide6.QtCore import Signal
from models import Song


class MetadataPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.song: Song = None
        
        layout = QVBoxLayout(self)
        
        # Song Info
        grp_info = QGroupBox("Song Info")
        form_info = QFormLayout(grp_info)
        
        self.inp_title = QLineEdit()
        self.inp_subtitle = QLineEdit()
        self.inp_wave = QLineEdit()
        self.inp_wave.setReadOnly(True)
        
        form_info.addRow("Title:", self.inp_title)
        form_info.addRow("Subtitle:", self.inp_subtitle)
        form_info.addRow("Audio File:", self.inp_wave)
        
        layout.addWidget(grp_info)
        
        # Timing
        grp_timing = QGroupBox("Timing")
        form_timing = QFormLayout(grp_timing)
        
        self.inp_bpm = QDoubleSpinBox()
        self.inp_bpm.setRange(1, 999)
        self.inp_bpm.setValue(120)
        
        self.inp_offset = QDoubleSpinBox()
        self.inp_offset.setRange(-10, 10)
        self.inp_offset.setSingleStep(0.01)
        
        self.inp_demo = QDoubleSpinBox()
        self.inp_demo.setRange(0, 300)
        
        form_timing.addRow("Base BPM:", self.inp_bpm)
        form_timing.addRow("Offset (s):", self.inp_offset)
        form_timing.addRow("Demo Start:", self.inp_demo)
        
        layout.addWidget(grp_timing)
        layout.addStretch()
        
        # Connect changes
        self.inp_title.textChanged.connect(self._update_model)
        self.inp_subtitle.textChanged.connect(self._update_model)
        self.inp_bpm.valueChanged.connect(self._update_model)
        self.inp_offset.valueChanged.connect(self._update_model)
        self.inp_demo.valueChanged.connect(self._update_model)

    def set_song(self, song: Song):
        self.song = song
        # Block signals to prevent feedback
        self.blockSignals(True)
        self.inp_title.setText(song.title)
        self.inp_subtitle.setText(song.subtitle)
        self.inp_wave.setText(song.wave)
        self.inp_bpm.setValue(song.bpm)
        self.inp_offset.setValue(song.offset)
        self.inp_demo.setValue(song.demostart)
        self.blockSignals(False)

    def _update_model(self):
        if not self.song: return
        self.song.title = self.inp_title.text()
        self.song.subtitle = self.inp_subtitle.text()
        self.song.bpm = self.inp_bpm.value()
        self.song.offset = self.inp_offset.value()
        self.song.demostart = self.inp_demo.value()
