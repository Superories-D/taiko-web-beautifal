"""
Toolbar for selecting note types.
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QButtonGroup
from PySide6.QtGui import QIcon, QPainter, QColor
from PySide6.QtCore import Qt, QSize, Signal
from models import NoteType


class NotePalette(QWidget):
    noteTypeChanged = Signal(NoteType)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.idClicked.connect(self._on_click)

        # Note types to show
        types = [
            (NoteType.DON, "Don"),
            (NoteType.KA, "Ka"),
            (NoteType.DAI_DON, "Dai Don"),
            (NoteType.DAI_KA, "Dai Ka"),
            (NoteType.DRUMROLL, "Drumroll"),
            (NoteType.DAI_DRUMROLL, "Dai Drumroll"),
            (NoteType.BALLOON, "Balloon"),
            (NoteType.END, "End"),
        ]

        for nt, label in types:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            # Placeholder icon drawing
            icon = self._create_icon(nt)
            btn.setIcon(icon)
            btn.setIconSize(QSize(32, 32))
            
            layout.addWidget(btn)
            self.group.addButton(btn, int(nt))

        # Default selection
        self.group.button(int(NoteType.DON)).setChecked(True)

    def _on_click(self, id: int):
        self.noteTypeChanged.emit(NoteType(id))

    def _create_icon(self, nt: NoteType) -> QIcon:
        # Draw simple colored circle on pixmap
        from PySide6.QtGui import QPixmap
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        
        color = Qt.lightGray
        if nt in (NoteType.DON, NoteType.DAI_DON): color = QColor("#f23c3c")
        elif nt in (NoteType.KA, NoteType.DAI_KA): color = QColor("#3c7df2")
        elif nt in (NoteType.DRUMROLL, NoteType.DAI_DRUMROLL): color = QColor("#f2c93c")
        elif nt == NoteType.BALLOON: color = QColor("#f28e3c")
        
        margin = 4
        if nt in (NoteType.DAI_DON, NoteType.DAI_KA, NoteType.DAI_DRUMROLL):
            margin = 2
            
        rect = pix.rect().adjusted(margin, margin, -margin, -margin)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(rect)
        painter.end()
        
        return QIcon(pix)
