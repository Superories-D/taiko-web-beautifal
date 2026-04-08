"""
Properties inspector panel.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout, 
    QSpinBox
)
from models import Note, Keyframe, NoteType

class PropertiesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        self.grp = QGroupBox("Properties")
        self.layout_form = QFormLayout(self.grp)
        self.lbl_type = QLabel("-")
        self.lbl_pos = QLabel("-")
        
        # Balloon specific
        self.spin_hits = QSpinBox()
        self.spin_hits.setRange(1, 999)
        self.spin_hits.valueChanged.connect(self._on_hits_changed)
        self.spin_hits.setVisible(False)
        self.lbl_hits = QLabel("Hits:")
        self.lbl_hits.setVisible(False)
        
        self.layout_form.addRow("Type:", self.lbl_type)
        self.layout_form.addRow("Position:", self.lbl_pos)
        self.layout_form.addRow(self.lbl_hits, self.spin_hits)
        
        layout.addWidget(self.grp)
        layout.addStretch()
        
        # Cache for updates
        self._current_course = None
        self._current_balloon_idx = None
        self._current_note = None

    def set_selection(self, obj, course=None, measure_idx=None, note_idx=None, balloon_idx=None):
        """
        Update properties for selected object.
        balloon_idx is required if obj is a Balloon/Kusudama note.
        """
        self._current_course = course
        self._current_balloon_idx = balloon_idx
        self._current_note = obj
        
        # Reset visibility
        self.spin_hits.setVisible(False)
        self.lbl_hits.setVisible(False)
        self.blockSignals(True)

        if isinstance(obj, Note):
            self.lbl_type.setText(obj.note_type.name)
            self.lbl_pos.setText(f"M:{measure_idx+1} N:{note_idx+1}" if measure_idx is not None else "-")
            
            if obj.note_type in (NoteType.BALLOON, NoteType.KUSUDAMA):
                self.spin_hits.setVisible(True)
                self.lbl_hits.setVisible(True)
                if course and balloon_idx is not None:
                    # Ensure list is long enough
                    while len(course.balloon) <= balloon_idx:
                        course.balloon.append(5)
                    self.spin_hits.setValue(course.balloon[balloon_idx])
                    
        elif isinstance(obj, Keyframe):
            self.lbl_type.setText(obj.kf_type.name)
            self.lbl_pos.setText(f"M:{obj.measure_index+1}")
        else:
            self.lbl_type.setText("None")
            self.lbl_pos.setText("-")
            self._current_course = None
            
        self.blockSignals(False)

    def _on_hits_changed(self, val):
        if self._current_course and self._current_balloon_idx is not None:
            # Ensure list length again just in case
            while len(self._current_course.balloon) <= self._current_balloon_idx:
                self._current_course.balloon.append(5)
            self._current_course.balloon[self._current_balloon_idx] = val
