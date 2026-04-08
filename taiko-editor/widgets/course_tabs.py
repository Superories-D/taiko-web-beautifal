"""
Tab bar for switching difficulties (Courses).
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QLabel, QTextEdit
from PySide6.QtCore import Signal
from models import Song, Course, COURSE_NAMES


class CourseTabs(QWidget):
    courseChanged = Signal(Course)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.song: Song = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_change)
        
        # Add tabs for fixed courses
        for name in COURSE_NAMES:
            # Simple placeholder content
            page = QWidget()
            layout_page = QVBoxLayout(page)
            layout_page.addWidget(QLabel(f"{name.capitalize()} Course Settings"))
            layout_page.addStretch()
            
            self.tabs.addTab(page, name.capitalize())
            
        layout.addWidget(self.tabs)

    def set_song(self, song: Song):
        self.song = song
        # Default to Oni
        self.tabs.setCurrentIndex(3)
        self._on_tab_change(3)

    def _on_tab_change(self, index: int):
        if not self.song: return
        course_name = COURSE_NAMES[index]
        course = self.song.get_or_create_course(course_name)
        self.courseChanged.emit(course)
