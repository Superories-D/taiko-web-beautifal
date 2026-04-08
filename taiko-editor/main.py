"""
Taiko Editor — Entry Point (PyQt5)
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QFile, QTextStream
from editor_window import EditorWindow


def _resource_path(*parts):
    """Resolve resource paths for both dev and PyInstaller onefile mode."""
    if getattr(sys, '_MEIPASS', None):
        return os.path.join(sys._MEIPASS, *parts)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("太鼓谱面编辑器")

    # Load stylesheet
    qss_path = _resource_path("resources", "style.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = EditorWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
