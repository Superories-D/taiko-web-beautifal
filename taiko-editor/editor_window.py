"""
主编辑器窗口 (PyQt5) — 剪映风格布局
功能：撤销、删除、中文界面、上传到服务器
"""
import os
import sys
import copy
import threading
import tempfile
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QDockWidget, QFileDialog, QMessageBox, QToolBar,
    QAction, QLabel, QGroupBox, QFormLayout, QLineEdit,
    QDoubleSpinBox, QSpinBox, QTabBar, QStatusBar, QSplitter,
    QShortcut, QApplication, QProgressDialog, QInputDialog,
    QComboBox
)
from PyQt5.QtGui import QKeySequence, QFont, QDragEnterEvent, QDropEvent
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QObject, QTimer, QSettings

from models import Song, Course, Note, NoteType, Measure, Keyframe, KeyframeType, COURSE_NAMES
from audio_engine import AudioEngine
from tja_parser import parse_tja, serialize_tja
from widgets.timeline import TimelineWidget


# ─── Undo/Redo System ───

class UndoStack:
    """Undo/redo stack storing deep copies of course measures + keyframes."""
    MAX = 100

    def __init__(self):
        self._undo = []
        self._redo = []

    def push(self, course: Course):
        snapshot = (copy.deepcopy(course.measures), copy.deepcopy(course.keyframes))
        self._undo.append(snapshot)
        if len(self._undo) > self.MAX:
            self._undo.pop(0)
        self._redo.clear()  # new edit invalidates redo

    def undo(self, course: Course) -> bool:
        if not self._undo:
            return False
        # Save current state for redo
        current = (copy.deepcopy(course.measures), copy.deepcopy(course.keyframes))
        self._redo.append(current)
        measures, keyframes = self._undo.pop()
        course.measures = measures
        course.keyframes = keyframes
        return True

    def redo(self, course: Course) -> bool:
        if not self._redo:
            return False
        current = (copy.deepcopy(course.measures), copy.deepcopy(course.keyframes))
        self._undo.append(current)
        measures, keyframes = self._redo.pop()
        course.measures = measures
        course.keyframes = keyframes
        return True

    def clear(self):
        self._undo.clear()
        self._redo.clear()


# ─── Upload Worker ───

class UploadSignals(QObject):
    finished = pyqtSignal(bool, str)


# ─── Metadata Panel ───

class MetadataPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.song = None
        self.course = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        g1 = QGroupBox("歌曲信息")
        f1 = QFormLayout(g1)
        f1.setSpacing(8)
        self.inp_title = QLineEdit()
        self.inp_subtitle = QLineEdit()
        self.inp_wave = QLineEdit()
        self.inp_wave.setReadOnly(True)
        f1.addRow("标题", self.inp_title)
        f1.addRow("副标题", self.inp_subtitle)
        f1.addRow("音频", self.inp_wave)
        layout.addWidget(g1)

        g2 = QGroupBox("节奏与难度")
        f2 = QFormLayout(g2)
        f2.setSpacing(8)
        self.inp_bpm = QDoubleSpinBox()
        self.inp_bpm.setRange(1, 999)
        self.inp_bpm.setDecimals(2)
        self.inp_bpm.setValue(120)
        self.inp_offset = QDoubleSpinBox()
        self.inp_offset.setRange(-30, 30)
        self.inp_offset.setSingleStep(0.01)
        self.inp_offset.setDecimals(3)
        self.inp_demo = QDoubleSpinBox()
        self.inp_demo.setRange(0, 600)
        self.inp_demo.setDecimals(2)
        
        self.inp_level = QSpinBox()
        self.inp_level.setRange(1, 10)
        self.inp_level.setValue(1)

        f2.addRow("BPM", self.inp_bpm)
        f2.addRow("偏移 (秒)", self.inp_offset)
        f2.addRow("试听起点", self.inp_demo)
        f2.addRow("难度星数", self.inp_level)
        layout.addWidget(g2)
        layout.addStretch()

        self.inp_title.textChanged.connect(self._sync)
        self.inp_subtitle.textChanged.connect(self._sync)
        self.inp_bpm.valueChanged.connect(self._sync)
        self.inp_offset.valueChanged.connect(self._sync)
        self.inp_demo.valueChanged.connect(self._sync)
        self.inp_level.valueChanged.connect(self._sync)

    def set_song_and_course(self, song, course):
        self.song = song
        self.course = course
        if not song or not course:
            return
            
        self.inp_title.blockSignals(True)
        self.inp_subtitle.blockSignals(True)
        self.inp_bpm.blockSignals(True)
        self.inp_offset.blockSignals(True)
        self.inp_demo.blockSignals(True)
        self.inp_level.blockSignals(True)
        
        self.inp_title.setText(song.title)
        self.inp_subtitle.setText(song.subtitle)
        self.inp_wave.setText(song.wave)
        self.inp_bpm.setValue(song.bpm)
        self.inp_offset.setValue(song.offset)
        self.inp_demo.setValue(song.demostart)
        self.inp_level.setValue(course.level)
        
        self.inp_title.blockSignals(False)
        self.inp_subtitle.blockSignals(False)
        self.inp_bpm.blockSignals(False)
        self.inp_offset.blockSignals(False)
        self.inp_demo.blockSignals(False)
        self.inp_level.blockSignals(False)

    def _sync(self):
        if self.song:
            self.song.title = self.inp_title.text()
            self.song.subtitle = self.inp_subtitle.text()
            self.song.bpm = self.inp_bpm.value()
            self.song.offset = self.inp_offset.value()
            self.song.demostart = self.inp_demo.value()
        if self.course:
            self.course.level = self.inp_level.value()


# ─── Properties Panel ───

class PropertiesPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        g = QGroupBox("选中项")
        f = QFormLayout(g)
        f.setSpacing(8)
        self.lbl_type = QLabel("-")
        self.lbl_pos = QLabel("-")
        self.spin_hits = QSpinBox()
        self.spin_hits.setRange(1, 999)
        self.spin_hits.setValue(5)
        self.spin_hits.setVisible(False)
        self.lbl_hits = QLabel("打击数")
        self.lbl_hits.setVisible(False)

        f.addRow("类型", self.lbl_type)
        f.addRow("位置", self.lbl_pos)
        f.addRow(self.lbl_hits, self.spin_hits)
        layout.addWidget(g)

        # Shortcuts hint
        hint = QGroupBox("快捷键")
        hl = QVBoxLayout(hint)
        hl.setSpacing(3)
        shortcuts = [
            "F / J       咚 (Don)",
            "D / K       咔 (Ka)",
            "← →        移动光标",
            "Ctrl+Z      撤销",
            "Ctrl+Y      重做",
            "Ctrl+C      复制",
            "Ctrl+V      粘贴",
            "Ctrl+A      全选",
            "Delete      删除",
            "B           添加BPM变化",
            "Space       播放/暂停",
            "滚轮         滚动时间轴",
            "Ctrl+滚轮    缩放",
        ]
        for s in shortcuts:
            lbl = QLabel(s)
            lbl.setStyleSheet("font-size: 10px; color: #555; font-family: 'Consolas', 'Segoe UI';")
            hl.addWidget(lbl)
        layout.addWidget(hint)
        layout.addStretch()

        self._course = None
        self._bi = None
        self.spin_hits.valueChanged.connect(self._on_hits)

    def set_selection(self, note, course, midx, nidx, bidx):
        self._course = course
        self._bi = bidx
        NOTE_NAMES = {
            NoteType.DON: "咚", NoteType.KA: "咔",
            NoteType.DAI_DON: "大咚", NoteType.DAI_KA: "大咔",
            NoteType.DRUMROLL: "连打", NoteType.DAI_DRUMROLL: "大连打",
            NoteType.BALLOON: "气球", NoteType.KUSUDAMA: "彩球",
            NoteType.END: "结束", NoteType.NONE: "-",
        }
        self.lbl_type.setText(NOTE_NAMES.get(note.note_type, "-") if isinstance(note, Note) else "-")
        self.lbl_pos.setText(f"第 {midx+1} 小节，第 {nidx+1} 拍")

        is_balloon = isinstance(note, Note) and note.note_type in (NoteType.BALLOON, NoteType.KUSUDAMA)
        self.spin_hits.setVisible(is_balloon)
        self.lbl_hits.setVisible(is_balloon)
        if is_balloon and course:
            while len(course.balloon) <= bidx:
                course.balloon.append(5)
            self.spin_hits.blockSignals(True)
            self.spin_hits.setValue(course.balloon[bidx])
            self.spin_hits.blockSignals(False)

    def _on_hits(self, v):
        if self._course and self._bi is not None:
            while len(self._course.balloon) <= self._bi:
                self._course.balloon.append(5)
            self._course.balloon[self._bi] = v


# ─── BPM Change Panel ───

class BpmPanel(QWidget):
    """Panel showing all BPM change points with add/edit/delete/jump controls."""
    bpmChanged = pyqtSignal()   # emitted when BPM list changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeline = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header label
        header = QLabel("🎵 BPM 变化点")
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #ff8a65;")
        layout.addWidget(header)

        # List
        from PyQt5.QtWidgets import QListWidget
        self.list = QListWidget()
        self.list.setStyleSheet("""
            QListWidget {
                background: #1a1a22;
                border: 1px solid #2a2a35;
                border-radius: 4px;
                color: #ddd;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #222;
            }
            QListWidget::item:selected {
                background: #2a3a50;
                color: #fff;
            }
            QListWidget::item:hover {
                background: #252535;
            }
        """)
        self.list.itemDoubleClicked.connect(self._on_jump)
        layout.addWidget(self.list)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        from PyQt5.QtWidgets import QPushButton
        self.btn_add = QPushButton("➕ 添加")
        self.btn_edit = QPushButton("✏️ 编辑")
        self.btn_del = QPushButton("➖ 删除")
        self.btn_jump = QPushButton("➡ 跳转")
        for btn in (self.btn_add, self.btn_edit, self.btn_del, self.btn_jump):
            btn.setFixedHeight(28)
            btn.setStyleSheet("""
                QPushButton {
                    background: #252535;
                    border: 1px solid #3a3a4a;
                    border-radius: 3px;
                    color: #ccc;
                    font-size: 11px;
                    padding: 2px 6px;
                }
                QPushButton:hover {
                    background: #303045;
                    border-color: #ff8a65;
                    color: #fff;
                }
            """)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_jump.clicked.connect(self._on_jump)

        self._bpm_data = []  # [(measure_index, bpm, ms), ...]

    def set_timeline(self, timeline):
        self.timeline = timeline

    def refresh(self):
        """Refresh the BPM change list from timeline data."""
        self.list.clear()
        self._bpm_data = []
        if not self.timeline:
            return
        changes = self.timeline.get_bpm_changes()
        self._bpm_data = changes
        for measure_idx, bpm_val, ms_pos in changes:
            t_sec = max(0, ms_pos / 1000.0)
            m = int(t_sec) // 60
            s = t_sec - m * 60
            bpm_str = f"{bpm_val:.1f}" if bpm_val % 1 else f"{int(bpm_val)}"
            if measure_idx == -1:
                label = f"⭐ 基准 BPM {bpm_str}    ({m}:{s:05.2f})"
            else:
                label = f"◆  小节 {measure_idx + 1:>3d}   BPM {bpm_str}    ({m}:{s:05.2f})"
            self.list.addItem(label)

    def _on_add(self):
        if not self.timeline:
            return
        self.timeline.add_bpm_at_cursor()
        self.refresh()
        self.bpmChanged.emit()

    def _on_edit(self):
        idx = self.list.currentRow()
        if idx < 0 or idx >= len(self._bpm_data) or not self.timeline:
            return
        measure_idx, old_bpm, _ = self._bpm_data[idx]
        from PyQt5.QtWidgets import QInputDialog
        val, ok = QInputDialog.getDouble(
            self, "编辑 BPM", "新 BPM 值:", old_bpm, 1.0, 999.0, 2
        )
        if ok:
            self.timeline.edit_bpm_at(measure_idx, val)
            self.refresh()
            self.bpmChanged.emit()

    def _on_delete(self):
        idx = self.list.currentRow()
        if idx < 0 or idx >= len(self._bpm_data) or not self.timeline:
            return
        measure_idx = self._bpm_data[idx][0]
        if measure_idx == -1:
            QMessageBox.information(self, "BPM", "基准 BPM 不可删除，请在元数据中修改。")
            return
        self.timeline.delete_bpm_at(measure_idx)
        self.refresh()
        self.bpmChanged.emit()

    def _on_jump(self):
        idx = self.list.currentRow()
        if idx < 0 or idx >= len(self._bpm_data) or not self.timeline:
            return
        measure_idx = self._bpm_data[idx][0]
        self.timeline.scroll_to_measure(measure_idx)

# ─── Main Window ───

class EditorWindow(QMainWindow):
    """主编辑器窗口"""

    UPLOAD_URL = "https://taiko.asia/api/upload"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("太鼓谱面编辑器")
        self.resize(1400, 820)
        self.setAcceptDrops(True)

        self.audio = AudioEngine()
        self.song = Song()
        self.current_course = None
        self.undo = UndoStack()
        self._tja_path = None       # last opened TJA path
        self._audio_path = None     # last opened audio path
        self._dirty = False         # unsaved changes flag
        self._clipboard = None      # copy/paste buffer
        
        # Load settings
        self.settings = QSettings("TaikoEditorGroup", "TaikoEditor")

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self.new_song()
        
        # Restore window state
        self._restore_state()

        # Auto-save timer (every 60 seconds)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

        # Check for crash recovery
        self._check_autosave_recovery()

    def _restore_state(self):
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)

    def _update_recent_files_menu(self):
        self.menu_recent.clear()
        recent = self.settings.value("recentFiles", [])
        if not recent:
            self.menu_recent.setEnabled(False)
            return
        self.menu_recent.setEnabled(True)
        for path in recent:
            action = QAction(os.path.basename(path), self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self._load_tja(p))
            self.menu_recent.addAction(action)
        self.menu_recent.addSeparator()
        clear_action = QAction("清空最近列表", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.menu_recent.addAction(clear_action)

    def _add_recent_file(self, path):
        recent = self.settings.value("recentFiles", [])
        if not isinstance(recent, list):
            recent = []
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        recent = recent[:10]  # Keep max 10
        self.settings.setValue("recentFiles", recent)
        self._update_recent_files_menu()

    def _clear_recent_files(self):
        self.settings.setValue("recentFiles", [])
        self._update_recent_files_menu()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Create Timeline early (so toolbar can access it)
        self.timeline = TimelineWidget(self.audio)
        self.timeline.positionChanged.connect(self._on_pos)
        self.timeline.noteSelected.connect(self._on_note_sel)

        # ─── Toolbar ───
        tb = QToolBar("工具")
        tb.setIconSize(QSize(18, 18))
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)

        tb.addAction("打开谱面", self.open_tja)
        tb.addAction("打开音频", self.open_audio)
        tb.addAction("保存", self.save_tja)
        tb.addAction("另存为", self.save_tja_as)
        tb.addSeparator()

        self.act_play = QAction("▶ 播放", self)
        self.act_play.setShortcut(Qt.Key_Space)
        self.act_play.triggered.connect(self.toggle_play)
        tb.addAction(self.act_play)
        tb.addAction("■ 停止", self.stop_play)
        tb.addSeparator()

        self.act_select = QAction("选择", self)
        self.act_select.setCheckable(True)
        self.act_select.setChecked(True)
        self.act_select.triggered.connect(lambda: self._set_mode("select"))
        tb.addAction(self.act_select)

        self.act_pen = QAction("画笔", self)
        self.act_pen.setCheckable(True)
        self.act_pen.triggered.connect(lambda: self._set_mode("pen"))
        tb.addAction(self.act_pen)
        tb.addSeparator()

        note_defs = [
            (NoteType.DON, "● 咚", "#ff5252"),
            (NoteType.KA, "● 喀", "#448aff"),
            (NoteType.DAI_DON, "● 大咚", "#ff8a80"),
            (NoteType.DAI_KA, "● 大喀", "#82b1ff"),
            (NoteType.DRUMROLL, "● 连打", "#ffab40"),
            (NoteType.BALLOON, "● 气球", "#ff6e40"),
        ]
        for nt, label, color in note_defs:
            a = QAction(label, self)
            a.setCheckable(True)
            a.triggered.connect(lambda checked, n=nt: self._set_note(n))
            tb.addAction(a)
        tb.addSeparator()

        # Snap Selector
        lbl_snap = QLabel("吸附:")
        lbl_snap.setStyleSheet("margin-left: 8px; color: #aaa;")
        tb.addWidget(lbl_snap)
        
        self.combo_snap = QComboBox()
        self.combo_snap.addItems(["1/4", "1/8", "1/12", "1/16", "1/24", "1/32", "1/48", "1/64", "Free"])
        self.combo_snap.setCurrentIndex(3) # 1/16 default
        self.combo_snap.currentIndexChanged.connect(self._on_snap_changed)
        self.combo_snap.setFocusPolicy(Qt.NoFocus)
        tb.addWidget(self.combo_snap)

        tb.addSeparator()

        self.act_preview = QAction("预览", self)
        self.act_preview.setCheckable(True)
        self.act_preview.setChecked(True)
        self.act_preview.triggered.connect(self._toggle_preview)
        tb.addAction(self.act_preview)

        tb.addSeparator()

        # Speed Selector
        lbl_speed = QLabel("速度:")
        lbl_speed.setStyleSheet("margin-left: 8px; color: #aaa;")
        tb.addWidget(lbl_speed)

        self.combo_speed = QComboBox()
        self.combo_speed.addItems(["0.25×", "0.5×", "0.75×", "1×", "1.25×", "1.5×", "2×"])
        self.combo_speed.setCurrentIndex(3)  # 1x default
        self.combo_speed.currentIndexChanged.connect(self._on_speed_changed)
        self.combo_speed.setFocusPolicy(Qt.NoFocus)
        tb.addWidget(self.combo_speed)

        tb.addSeparator()
        tb.addAction("上传服务器", self.upload_to_server)

        # ─── Course tabs ───
        self.course_bar = QTabBar()
        self.course_bar.setExpanding(False)
        COURSE_LABELS = {
            "easy": "简单", "normal": "普通", "hard": "困难",
            "oni": "魔王", "ura": "里谱",
        }
        for name in COURSE_NAMES:
            self.course_bar.addTab(COURSE_LABELS.get(name, name))
        self.course_bar.setCurrentIndex(3)
        self.course_bar.currentChanged.connect(self._on_course_tab)
        root.addWidget(self.course_bar)

        # ─── Timeline ───
        root.addWidget(self.timeline, stretch=1)

        # ─── Dock: Metadata ───
        self.dock_meta = QDockWidget("元数据", self)
        self.dock_meta.setFeatures(QDockWidget.DockWidgetMovable)
        self.meta_panel = MetadataPanel()
        self.dock_meta.setWidget(self.meta_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_meta)

        # ─── Dock: Properties ───
        self.dock_props = QDockWidget("属性", self)
        self.dock_props.setFeatures(QDockWidget.DockWidgetMovable)
        self.props_panel = PropertiesPanel()
        self.dock_props.setWidget(self.props_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_props)

        # ─── Dock: BPM Changes ───
        self.dock_bpm = QDockWidget("BPM 变化", self)
        self.dock_bpm.setFeatures(QDockWidget.DockWidgetMovable)
        self.bpm_panel = BpmPanel()
        self.bpm_panel.set_timeline(self.timeline)
        self.bpm_panel.bpmChanged.connect(self._on_bpm_panel_changed)
        self.dock_bpm.setWidget(self.bpm_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_bpm)
        self.tabifyDockWidget(self.dock_props, self.dock_bpm)

        # ─── Status ───
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("文件(&F)")
        fm.addAction("新建", self.new_song, QKeySequence.New)
        fm.addAction("打开谱面...", self.open_tja, QKeySequence.Open)
        
        self.menu_recent = fm.addMenu("最近打开...")
        self._update_recent_files_menu()
        
        fm.addAction("打开音频...", self.open_audio)
        fm.addSeparator()
        fm.addAction("保存", self.save_tja, QKeySequence.Save)
        fm.addAction("另存为...", self.save_tja_as)
        fm.addSeparator()
        fm.addAction("上传到服务器", self.upload_to_server)

        em = mb.addMenu("编辑(&E)")
        em.addAction("撤销", self.undo_action, QKeySequence.Undo)
        em.addAction("重做", self.redo_action, QKeySequence("Ctrl+Y"))
        em.addSeparator()
        em.addAction("复制", self.copy_notes, QKeySequence.Copy)
        em.addAction("粘贴", self.paste_notes, QKeySequence.Paste)
        em.addSeparator()
        em.addAction("全选", self.select_all, QKeySequence.SelectAll)
        em.addAction("删除选中音符", self.delete_selected, QKeySequence.Delete)

        vm = mb.addMenu("视图(&V)")
        vm.addAction("元数据面板", lambda: self.dock_meta.setVisible(not self.dock_meta.isVisible()))
        vm.addAction("属性面板", lambda: self.dock_props.setVisible(not self.dock_props.isVisible()))
        vm.addAction("BPM 变化面板", lambda: self._show_bpm_panel())

    def _build_shortcuts(self):
        # Quick add: F/J = Don, D/K = Ka
        QShortcut(QKeySequence(Qt.Key_F), self, lambda: self._quick("don"))
        QShortcut(QKeySequence(Qt.Key_J), self, lambda: self._quick("don"))
        QShortcut(QKeySequence(Qt.Key_D), self, lambda: self._quick("ka"))
        QShortcut(QKeySequence(Qt.Key_K), self, lambda: self._quick("ka"))
        # Arrow keys
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self._arrow(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self._arrow(1))
        # Delete / Backspace
        QShortcut(QKeySequence(Qt.Key_Backspace), self, self.delete_selected)
        # BPM change at cursor
        QShortcut(QKeySequence(Qt.Key_B), self, self._add_bpm_at_cursor)
        # Play/Pause
        QShortcut(QKeySequence(Qt.Key_Space), self, self._safe_toggle_play)

    def _safe_toggle_play(self):
        if self._is_typing():
            return
        self.toggle_play()

    def _is_typing(self):
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QSpinBox, QDoubleSpinBox))

    def _quick(self, kind):
        if self._is_typing():
            return
        # Throttle undo: only push if last push was > 500ms ago
        import time
        now = time.time()
        if not hasattr(self, '_last_undo_t') or now - self._last_undo_t > 0.5:
            self._push_undo()
            self._last_undo_t = now
        nt = NoteType.DON if kind == "don" else NoteType.KA
        self.timeline.quick_add(nt)
        self._mark_dirty()

    def _arrow(self, direction):
        if self._is_typing():
            return
        self.timeline.move_cursor(direction)

    def _push_undo(self):
        if self.current_course:
            self.undo.push(self.current_course)

    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self._tja_path) if self._tja_path else "新谱面"
        dirty = " *" if self._dirty else ""
        self.setWindowTitle(f"{name}{dirty} — 太鼓谱面编辑器")

    def _add_bpm_at_cursor(self):
        if self._is_typing():
            return
        self._push_undo()
        self.timeline.add_bpm_at_cursor()
        self.bpm_panel.refresh()
        self._mark_dirty()

    def _on_bpm_panel_changed(self):
        self._push_undo()
        self._mark_dirty()
        self.timeline.update()

    def _show_bpm_panel(self):
        self.dock_bpm.setVisible(True)
        self.dock_bpm.raise_()
        self.bpm_panel.refresh()

    # ─── Actions ───

    def undo_action(self):
        if self._is_typing():
            return
        if self.current_course and self.undo.undo(self.current_course):
            self.timeline.selected_notes = []
            self.timeline.selected_obj = None
            self.timeline.update()
            self.status.showMessage("已撤销")
        else:
            self.status.showMessage("无可撤销操作")

    def redo_action(self):
        if self._is_typing():
            return
        if self.current_course and self.undo.redo(self.current_course):
            self.timeline.selected_notes = []
            self.timeline.selected_obj = None
            self.timeline.update()
            self.status.showMessage("已重做")
        else:
            self.status.showMessage("无可重做操作")

    def delete_selected(self):
        if self._is_typing():
            return
        if self.timeline.selected_notes:
            self._push_undo()
            self.timeline.delete_selected()
            self._update_stats()
            self._mark_dirty()
            self.status.showMessage("已删除音符")
        elif isinstance(getattr(self.timeline, 'selected_obj', None), Note):
            n = self.timeline.selected_obj
            if n.note_type != NoteType.NONE:
                self._push_undo()
                n.note_type = NoteType.NONE
                self.timeline.selected_obj = None
                self.timeline.selected_notes = []
                self.timeline.update()
                self._update_stats()
                self._mark_dirty()
                self.status.showMessage("已删除音符")

    def copy_notes(self):
        """Copy selected notes to clipboard (relative offsets)."""
        if self._is_typing() or not self.timeline.selected_notes:
            return
        self._clipboard = self.timeline.get_copy_data()
        if self._clipboard:
            self.status.showMessage(f"已复制 {len(self._clipboard)} 个音符")

    def paste_notes(self):
        """Paste copied notes at cursor position."""
        if self._is_typing() or not getattr(self, '_clipboard', None):
            return
        self._push_undo()
        self.timeline.paste_copy_data(self._clipboard, self.timeline.cursor_ms)
        self._update_stats()
        self._mark_dirty()
        self.status.showMessage(f"已粘贴 {len(self._clipboard)} 个音符")

    def select_all(self):
        """Select all non-NONE notes in current course."""
        if self._is_typing():
            return
        self.timeline.select_all()
        count = len(self.timeline.selected_notes)
        self.status.showMessage(f"已选中 {count} 个音符")

    def new_song(self):
        self.song = Song()
        self.undo.clear()
        self._tja_path = None
        self._dirty = False
        self._on_course_tab(self.course_bar.currentIndex())
        self._update_title()

    def open_tja(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开谱面", "", "TJA 文件 (*.tja)")
        if path:
            self._load_tja(path)

    def _load_tja(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.song = parse_tja(f.read())
            self._tja_path = path
            self._add_recent_file(path)
            self.undo.clear()
            self._dirty = False
            self._on_course_tab(self.course_bar.currentIndex())
            self._update_title()
            if self.song.wave:
                ap = os.path.join(os.path.dirname(path), self.song.wave)
                if os.path.exists(ap):
                    self.audio.load(ap)
                    self._audio_path = ap
            self.status.showMessage(f"已加载: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def open_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开音频", "", "音频文件 (*.ogg *.wav *.mp3)")
        if path:
            self._load_audio(path)

    def _load_audio(self, path):
        if self.audio.load(path):
            self._audio_path = path
            self.song.wave = os.path.basename(path)
            self.meta_panel.set_song_and_course(self.song, self.current_course)
            self.timeline.update()
            self.status.showMessage(f"音频: {os.path.basename(path)}")

    def save_tja(self):
        if self._tja_path:
            self._do_save(self._tja_path)
        else:
            self.save_tja_as()

    def save_tja_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存谱面", "", "TJA 文件 (*.tja)")
        if path:
            self._tja_path = path
            self._do_save(path)

    def _do_save(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(serialize_tja(self.song))
            self.status.showMessage(f"已保存: {os.path.basename(path)}")
            self._dirty = False
            self._update_title()
            self._remove_autosave()  # clean up autosave after successful save
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    # ─── Auto-save ───

    def _autosave_path(self):
        """Get autosave file path. Next to TJA file or in temp dir."""
        if self._tja_path:
            d = os.path.dirname(self._tja_path)
            base = os.path.splitext(os.path.basename(self._tja_path))[0]
            return os.path.join(d, f".{base}.autosave.tja")
        else:
            return os.path.join(tempfile.gettempdir(), ".taiko_editor_autosave.tja")

    def _autosave(self):
        """Periodic auto-save to prevent data loss on crash."""
        if not self._dirty:
            return
        try:
            path = self._autosave_path()
            with open(path, "w", encoding="utf-8") as f:
                f.write(serialize_tja(self.song))
            self.status.showMessage("✓ 已自动保存", 3000)
        except Exception:
            pass  # auto-save failure is silent

    def _remove_autosave(self):
        """Remove autosave file after successful manual save."""
        try:
            path = self._autosave_path()
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _check_autosave_recovery(self):
        """On startup, check for autosave files and offer recovery."""
        # Check temp dir for unnamed autosave
        tmp_path = os.path.join(tempfile.gettempdir(), ".taiko_editor_autosave.tja")
        if os.path.exists(tmp_path):
            reply = QMessageBox.question(
                self, "恢复自动保存",
                "检测到上次未保存的自动备份文件，是否恢复？\n"
                "选择“是”恢复谱面，选择“否”删除备份。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self._load_tja(tmp_path)
                self._tja_path = None  # don't overwrite the autosave
                self._dirty = True
                self._update_title()
                self.status.showMessage("已恢复自动保存的谱面，请另存为新文件")
            else:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def toggle_play(self):
        if self.audio.is_playing:
            self.audio.pause()
            self.act_play.setText("▶ 播放")
        else:
            if self.audio.loaded:
                if self.timeline.cursor_ms >= self.audio.duration_ms:
                    self.timeline.cursor_ms = 0
                self.audio.play(self.timeline.cursor_ms)
                self.act_play.setText("⏸ 暂停")

    def stop_play(self):
        self.audio.stop()
        self.timeline.cursor_ms = 0
        self.act_play.setText("▶ 播放")
        self.timeline.update()

    def _set_mode(self, mode):
        self.timeline.edit_mode = mode
        self.act_select.setChecked(mode == "select")
        self.act_pen.setChecked(mode == "pen")

    def _set_note(self, nt):
        self.timeline.current_note_type = nt
        self._set_mode("pen")

    def _toggle_preview(self):
        self.timeline.preview_enabled = self.act_preview.isChecked()

    def _on_speed_changed(self, idx):
        speeds = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
        if 0 <= idx < len(speeds):
            self.audio.set_speed(speeds[idx])
        self.timeline.setFocus()

    def _on_course_tab(self, idx):
        name = COURSE_NAMES[idx]
        self.current_course = self.song.get_or_create_course(name)
        self.timeline.set_song_and_course(self.song, self.current_course)
        self.meta_panel.set_song_and_course(self.song, self.current_course)
        self.undo.clear()
        self._update_stats()
        self.bpm_panel.refresh()

    def _on_snap_changed(self, idx):
        txt = self.combo_snap.itemText(idx)
        if txt == "Free":
            self.timeline.snap_divisor = 0
        else:
            try:
                denom = int(txt.split("/")[1])
                self.timeline.snap_divisor = denom
            except (ValueError, IndexError):
                self.timeline.snap_divisor = 16
        self.timeline.setFocus()

    def _on_pos(self, ms):
        if ms < 0:
            ms = 0
        secs = ms / 1000
        m = int(secs) // 60
        s = secs - m * 60
        bpm_str = ""
        if self.current_course:
            bpm = self.timeline._get_bpm_at(ms)
            bpm_str = f"  |  BPM: {bpm:.1f}"
        stats = getattr(self, '_stats_text', '')
        self.status.showMessage(f"位置: {m}:{s:05.2f}{bpm_str}{stats}")

    def _update_stats(self):
        """Update note count statistics."""
        if not self.current_course:
            self._stats_text = ""
            return
        total = 0
        don = 0
        ka = 0
        for m in self.current_course.measures:
            for n in m.notes:
                if n.note_type != NoteType.NONE:
                    total += 1
                    if n.note_type in (NoteType.DON, NoteType.DAI_DON):
                        don += 1
                    elif n.note_type in (NoteType.KA, NoteType.DAI_KA):
                        ka += 1
        self._stats_text = f"  |  音符: {total} (咚{don} / 喀{ka})"

    def _on_note_sel(self, note, course, midx, nidx, bidx):
        self.props_panel.set_selection(note, course, midx, nidx, bidx)

    # ─── Upload ───

    def upload_to_server(self):
        """Upload current TJA + audio to taiko.asia."""
        if not self._audio_path or not os.path.exists(self._audio_path):
            QMessageBox.warning(self, "上传", "请先加载音频文件（OGG）。")
            return

        tja_text = serialize_tja(self.song)
        if not tja_text.strip():
            QMessageBox.warning(self, "上传", "谱面内容为空，请先编辑。")
            return

        # Ask for song type
        types = [
            "01 Pop", "02 Anime", "03 Vocaloid",
            "04 Children and Folk", "05 Variety", "06 Classical",
            "07 Game Music", "08 Live Festival Mode",
            "09 Namco Original", "10 Taiko Towers", "11 Dan Dojo",
        ]
        song_type, ok = QInputDialog.getItem(
            self, "上传到服务器", "选择歌曲分类:", types, 0, False
        )
        if not ok:
            return

        self.status.showMessage("正在上传...")
        self._upload_signals = UploadSignals()
        self._upload_signals.finished.connect(self._on_upload_done)

        t = threading.Thread(
            target=self._do_upload,
            args=(tja_text, self._audio_path, song_type),
            daemon=True,
        )
        t.start()

    def _do_upload(self, tja_text, music_path, song_type):
        try:
            import requests
            with open(music_path, 'rb') as fm:
                files = {
                    'file_tja': ('main.tja', tja_text.encode('utf-8'), 'text/plain'),
                    'file_music': ('music.ogg', fm.read(), 'audio/ogg'),
                }
                data = {'song_type': song_type}
                resp = requests.post(self.UPLOAD_URL, files=files, data=data, timeout=60)
            if resp.status_code != 200:
                self._upload_signals.finished.emit(False, f'HTTP {resp.status_code}')
                return
            try:
                j = resp.json()
            except Exception:
                self._upload_signals.finished.emit(False, '服务器返回无效数据')
                return
            if j.get('success') is True:
                self._upload_signals.finished.emit(True, '上传成功！')
            else:
                self._upload_signals.finished.emit(False, j.get('error', '未知错误'))
        except Exception as e:
            self._upload_signals.finished.emit(False, str(e))

    def _on_upload_done(self, success, msg):
        if success:
            self.status.showMessage(msg)
            QMessageBox.information(self, "上传", msg)
        else:
            self.status.showMessage(f"上传失败: {msg}")
            QMessageBox.warning(self, "上传失败", msg)

    # ─── Drag & Drop ───

    def dragEnterEvent(self, ev: QDragEnterEvent):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev: QDropEvent):
        for url in ev.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".tja"):
                self._load_tja(path)
            elif path.lower().endswith((".ogg", ".wav", ".mp3")):
                self._load_audio(path)

    def closeEvent(self, ev):
        if self._dirty:
            reply = QMessageBox.question(
                self, "未保存的更改",
                "当前谱面有未保存的更改，确定要退出吗？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )
            if reply == QMessageBox.Save:
                self.save_tja()
            elif reply == QMessageBox.Cancel:
                ev.ignore()
                return

        # Save window state
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())

        self._remove_autosave()
        self.audio.cleanup()
        ev.accept()
