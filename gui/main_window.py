"""
main_window.py — QMainWindow: tab container + menu bar + status bar.
"""

from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QMenuBar, QAction,
    QLabel, QWidget, QVBoxLayout,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QIcon, QFont

from .generate_tab import GenerateTab
from .viewer_tab   import ViewerTab
from .theme import ACCENT, BG_DEEP, TEXT_DIM


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Synthetic Organoid Generator")
        self.resize(1400, 860)
        self.setMinimumSize(900, 600)

        self._build_menu()
        self._build_tabs()
        self._build_status_bar()

    # ── Menu bar ─────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("File")
        open_act = QAction("Open OME-TIFF...", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_file)
        file_menu.addAction(open_act)
        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # View
        view_menu = mb.addMenu("View")
        gen_act = QAction("Generate Tab", self)
        gen_act.setShortcut("Ctrl+1")
        gen_act.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        view_menu.addAction(gen_act)
        view_act = QAction("Viewer Tab", self)
        view_act.setShortcut("Ctrl+2")
        view_act.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        view_menu.addAction(view_act)

        # Help
        help_menu = mb.addMenu("Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    # ── Tab container ────────────────────────────────────────────────

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.gen_tab    = GenerateTab()
        self.viewer_tab = ViewerTab()

        self.tabs.addTab(self.gen_tab,    "🔬  Generate")
        self.tabs.addTab(self.viewer_tab, "📂  View Results")
        self.tabs.addTab(self._about_widget(), "ℹ️  About")

        # When generation finishes, switch to viewer and load result
        self.gen_tab.fileGenerated.connect(self._on_file_generated)

        self.setCentralWidget(self.tabs)

    # ── Status bar ───────────────────────────────────────────────────

    def _build_status_bar(self):
        sb = QStatusBar()
        sb.setStyleSheet(f"color:{TEXT_DIM}; font-size:11px;")
        self.status_lbl = QLabel("Ready")
        sb.addPermanentWidget(self.status_lbl)
        self.setStatusBar(sb)

    # ── Slots ────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_file_generated(self, path: str):
        """Auto-load generated file into viewer and switch tab."""
        self.status_lbl.setText(f"Generated: {Path(path).name}")
        self.viewer_tab.load_file(path)
        self.tabs.setCurrentIndex(1)

    def _open_file(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open OME-TIFF", "",
            "OME-TIFF (*.ome.tif *.tif *.tiff);;All files (*)")
        if path:
            self.viewer_tab.load_file(path)
            self.tabs.setCurrentIndex(1)

    def _show_about(self):
        self.tabs.setCurrentIndex(2)

    # ── About widget ─────────────────────────────────────────────────

    def _about_widget(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(14)

        title = QLabel("Synthetic Organoid Generator")
        title.setStyleSheet(
            f"color:{ACCENT}; font-size:22px; font-weight:bold;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        sub = QLabel("3D fluorescence organoid simulation for pipeline development")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color:#aaa; font-size:13px;")
        lay.addWidget(sub)

        for line in [
            ("Output format",  "OME-TIFF (2-channel fluorescence + 2 label masks)"),
            ("Compatible with","arivis Pro · FIJI · napari · 3DCellScope"),
            ("Modalities",     "Confocal LSM · Lightsheet · Widefield · Lightfield"),
            ("Author",         "DigitalSreeni / ZEISS Microscopy"),
            ("Reference",      "Ong et al., Nature Methods 2025 (3DCellScope)"),
        ]:
            row = QLabel(f"<b>{line[0]}:</b>  {line[1]}")
            row.setAlignment(Qt.AlignCenter)
            row.setStyleSheet("color:#ccc; font-size:12px;")
            lay.addWidget(row)

        lay.addStretch()
        return w
