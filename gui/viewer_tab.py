"""
viewer_tab.py — Tab 2: View Results

Full-featured 2D slice navigator for OME-TIFF organoid images.
Loads fluorescence channels + label masks, supports Z navigation,
channel modes, label overlay with opacity, display range, scale bar.
"""

import numpy as np
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QSlider, QComboBox, QCheckBox,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFileDialog,
    QSizePolicy, QFrame, QToolButton, QProgressBar,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QIcon

from .image_canvas import ImageCanvas
from .workers import LoadWorker
from .theme import ACCENT, TEXT_DIM, BG_PANEL, WARNING


class ViewerTab(QWidget):
    """Tab 2 — slice-by-slice viewer for generated OME-TIFF files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data       = None   # (C, Z, Y, X) float32 [0,1]
        self._labels     = None   # (Z, Y, X) uint16
        self._nuc_labels = None   # (Z, Y, X) uint16
        self._voxel_xy   = 0.414
        self._voxel_z    = 1.0
        self._z_index    = 0
        self._view_axis  = "XY"   # "XY" | "XZ" | "YZ"
        self._playing    = False
        self._load_worker = None

        self._play_timer = QTimer()
        self._play_timer.timeout.connect(self._advance_z)

        self._build_ui()

    # ── UI construction ─────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        root.addWidget(splitter)

        # ── Left: controls ──
        ctrl_panel = QWidget()
        ctrl_panel.setFixedWidth(240)
        ctrl_panel.setStyleSheet(f"background:{BG_PANEL};border-radius:6px;")
        ctrl_layout = QVBoxLayout(ctrl_panel)
        ctrl_layout.setContentsMargins(10, 10, 10, 10)
        ctrl_layout.setSpacing(10)

        # File open
        file_grp = QGroupBox("File")
        file_lay = QVBoxLayout(file_grp)
        file_lay.setSpacing(6)
        self.file_label = QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("dim")
        self.open_btn = QPushButton("📂  Open OME-TIFF...")
        self.open_btn.clicked.connect(self._open_file)
        self.load_bar = QProgressBar()
        self.load_bar.setTextVisible(False)
        self.load_bar.setFixedHeight(4)
        self.load_bar.setRange(0, 0)
        self.load_bar.hide()
        file_lay.addWidget(self.file_label)
        file_lay.addWidget(self.open_btn)
        file_lay.addWidget(self.load_bar)
        ctrl_layout.addWidget(file_grp)

        # Channel
        ch_grp = QGroupBox("Channel")
        ch_lay = QVBoxLayout(ch_grp)
        ch_lay.setSpacing(6)
        self.ch_combo = QComboBox()
        self.ch_combo.addItems(["Merge (DAPI + Actin)", "DAPI only", "Actin only"])
        self.ch_combo.currentIndexChanged.connect(self._update_mode)
        ch_lay.addWidget(self.ch_combo)
        ctrl_layout.addWidget(ch_grp)

        # Display range
        rng_grp = QGroupBox("Display Range")
        rng_lay = QVBoxLayout(rng_grp)
        rng_lay.setSpacing(4)
        for label, attr, val in [("Min %", "_lo_spin", 1.0),
                                  ("Max %", "_hi_spin", 99.5)]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(0, 100); spin.setSingleStep(0.5); spin.setValue(val)
            spin.valueChanged.connect(self._update_range)
            setattr(self, attr, spin)
            row.addWidget(spin)
            rng_lay.addLayout(row)
        ctrl_layout.addWidget(rng_grp)

        # Labels overlay
        lbl_grp = QGroupBox("Label Overlay")
        lbl_lay = QVBoxLayout(lbl_grp)
        lbl_lay.setSpacing(6)
        self.cells_chk = QCheckBox("Show cell bodies")
        self.cells_chk.stateChanged.connect(self._update_labels)
        self.nuc_chk = QCheckBox("Show nuclei")
        self.nuc_chk.stateChanged.connect(self._update_labels)
        lbl_lay.addWidget(self.cells_chk)
        lbl_lay.addWidget(self.nuc_chk)
        row = QHBoxLayout()
        row.addWidget(QLabel("Opacity"))
        self.alpha_sl = QSlider(Qt.Horizontal)
        self.alpha_sl.setRange(5, 80); self.alpha_sl.setValue(35)
        self.alpha_sl.valueChanged.connect(self._update_labels)
        row.addWidget(self.alpha_sl)
        lbl_lay.addLayout(row)
        self.hover_lbl = QLabel("Hover over cell to inspect")
        self.hover_lbl.setObjectName("dim")
        self.hover_lbl.setWordWrap(True)
        lbl_lay.addWidget(self.hover_lbl)
        ctrl_layout.addWidget(lbl_grp)

        # View axis
        axis_grp = QGroupBox("View Plane")
        axis_lay = QHBoxLayout(axis_grp)
        for ax in ["XY", "XZ", "YZ"]:
            btn = QPushButton(ax)
            btn.setCheckable(True)
            btn.setChecked(ax == "XY")
            btn.clicked.connect(lambda checked, a=ax: self._set_axis(a))
            setattr(self, f"_btn_{ax}", btn)
            axis_lay.addWidget(btn)
        ctrl_layout.addWidget(axis_grp)

        # Info
        self.info_lbl = QLabel("")
        self.info_lbl.setObjectName("dim")
        self.info_lbl.setWordWrap(True)
        ctrl_layout.addWidget(self.info_lbl)

        ctrl_layout.addStretch()

        # Export
        self.export_btn = QPushButton("💾  Save current view...")
        self.export_btn.clicked.connect(self._export_view)
        self.export_btn.setEnabled(False)
        ctrl_layout.addWidget(self.export_btn)

        splitter.addWidget(ctrl_panel)

        # ── Right: canvas + Z navigator ──
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        self.canvas = ImageCanvas()
        self.canvas.hoveredLabel.connect(self._on_hover)
        right_lay.addWidget(self.canvas)

        # Z navigation bar
        nav = QFrame()
        nav.setFixedHeight(52)
        nav.setStyleSheet(f"background:{BG_PANEL};border-radius:5px;")
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(10, 4, 10, 4)
        nav_lay.setSpacing(8)

        self.z_label = QLabel("Z: --/--")
        self.z_label.setFixedWidth(70)
        nav_lay.addWidget(self.z_label)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(32)
        self.prev_btn.clicked.connect(lambda: self._step_z(-1))
        nav_lay.addWidget(self.prev_btn)

        self.z_slider = QSlider(Qt.Horizontal)
        self.z_slider.valueChanged.connect(self._on_z_slider)
        nav_lay.addWidget(self.z_slider)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(32)
        self.next_btn.clicked.connect(lambda: self._step_z(1))
        nav_lay.addWidget(self.next_btn)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setFixedWidth(72)
        self.play_btn.clicked.connect(self._toggle_play)
        nav_lay.addWidget(self.play_btn)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 20)
        self.fps_spin.setValue(5)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setFixedWidth(72)
        self.fps_spin.valueChanged.connect(
            lambda v: self._play_timer.setInterval(1000 // v))
        nav_lay.addWidget(self.fps_spin)

        right_lay.addWidget(nav)
        splitter.addWidget(right)
        splitter.setSizes([240, 700])

        self._set_controls_enabled(False)

    # ── File loading ─────────────────────────────────────────────────

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open OME-TIFF", "",
            "OME-TIFF files (*.ome.tif *.tif *.tiff);;All files (*)")
        if not path:
            return
        self._load_file(path)

    def load_file(self, path: str):
        """Called externally (e.g. after generation completes)."""
        self._load_file(path)

    def _load_file(self, path: str):
        self.file_label.setText(Path(path).name)
        self.load_bar.show()
        self.open_btn.setEnabled(False)

        self._load_worker = LoadWorker(path)
        self._load_worker.finished.connect(self._on_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.progress.connect(
            lambda s: self.file_label.setText(s))
        self._load_worker.start()

    @pyqtSlot(object)
    def _on_loaded(self, result: dict):
        self.load_bar.hide()
        self.open_btn.setEnabled(True)

        data = result["data"]
        # Normalise to float32 [0,1]
        if data.ndim == 4:
            self._data = data.astype(np.float32) / 65535.0
        else:
            self._data = data.astype(np.float32) / 65535.0

        self._labels     = result["labels"]
        self._nuc_labels = result["nuc_labels"]
        self._voxel_xy   = result["voxel_xy"]
        self._voxel_z    = result["voxel_z"]
        self.canvas.set_voxel_xy(self._voxel_xy)

        Z = self._data.shape[1] if self._data.ndim == 3 else self._data.shape[1]
        self._z_index = Z // 2
        self.z_slider.setRange(0, Z - 1)
        self.z_slider.setValue(self._z_index)

        n_cells = int(self._labels.max()) if self._labels is not None else 0
        self.info_lbl.setText(
            f"Shape: {self._data.shape}\n"
            f"Voxel: {self._voxel_xy:.3f}×{self._voxel_xy:.3f}×{self._voxel_z:.3f} µm\n"
            f"Cells: {n_cells}"
        )

        self._set_controls_enabled(True)
        self.export_btn.setEnabled(True)
        self.file_label.setText(Path(result["filepath"]).name)
        self._refresh()

    @pyqtSlot(str)
    def _on_load_error(self, msg: str):
        self.load_bar.hide()
        self.open_btn.setEnabled(True)
        self.file_label.setText(f"⚠ Load error — see console")
        print(msg)

    # ── Display refresh ──────────────────────────────────────────────

    def _refresh(self):
        if self._data is None:
            return

        z = self._z_index

        # Extract slices based on view axis
        if self._view_axis == "XY":
            dapi  = self._data[0, z] if self._data.shape[0] > 0 else None
            actin = self._data[1, z] if self._data.shape[0] > 1 else None
            lbl   = self._labels[z]     if self._labels     is not None else None
            nlbl  = self._nuc_labels[z] if self._nuc_labels is not None else None
            Z     = self._data.shape[1]
        elif self._view_axis == "XZ":
            mid_y = self._data.shape[2] // 2
            dapi  = self._data[0, :, mid_y, :] if self._data.shape[0] > 0 else None
            actin = self._data[1, :, mid_y, :] if self._data.shape[0] > 1 else None
            lbl   = (self._labels[:, mid_y, :]     if self._labels     is not None else None)
            nlbl  = (self._nuc_labels[:, mid_y, :] if self._nuc_labels is not None else None)
            Z     = self._data.shape[2]
        else:  # YZ
            mid_x = self._data.shape[3] // 2
            dapi  = self._data[0, :, :, mid_x] if self._data.shape[0] > 0 else None
            actin = self._data[1, :, :, mid_x] if self._data.shape[0] > 1 else None
            lbl   = (self._labels[:, :, mid_x]     if self._labels     is not None else None)
            nlbl  = (self._nuc_labels[:, :, mid_x] if self._nuc_labels is not None else None)
            Z     = self._data.shape[2]

        # Choose which label to show
        show_lbl = None
        if self.nuc_chk.isChecked() and nlbl is not None:
            show_lbl = nlbl
        elif self.cells_chk.isChecked() and lbl is not None:
            show_lbl = lbl
        # Both checked: nucleus on top
        if self.cells_chk.isChecked() and self.nuc_chk.isChecked() \
                and lbl is not None and nlbl is not None:
            # Composite: cell colour + nucleus overlay handled below
            show_lbl = lbl  # show cell bodies; nuclei drawn second

        self.canvas.set_slices(dapi, actin, show_lbl)
        if self._view_axis == "XY":
            self.z_label.setText(f"Z: {z+1}/{Z}")
        else:
            self.z_label.setText(f"{self._view_axis} view")

    # ── Controls ─────────────────────────────────────────────────────

    def _update_mode(self, idx):
        modes = ["merge", "dapi", "actin"]
        self.canvas.set_mode(modes[idx])

    def _update_range(self):
        self.canvas.set_display_range(self._lo_spin.value(),
                                       self._hi_spin.value())

    def _update_labels(self):
        self.canvas.set_label_alpha(self.alpha_sl.value() / 100.0)
        show = self.cells_chk.isChecked() or self.nuc_chk.isChecked()
        self.canvas.set_labels_visible(show)
        self._refresh()

    def _set_axis(self, axis: str):
        self._view_axis = axis
        for ax in ["XY", "XZ", "YZ"]:
            getattr(self, f"_btn_{ax}").setChecked(ax == axis)
        self._refresh()

    def _on_z_slider(self, value: int):
        self._z_index = value
        self._refresh()

    def _step_z(self, delta: int):
        if self._data is None: return
        Z = self._data.shape[1]
        self._z_index = (self._z_index + delta) % Z
        self.z_slider.setValue(self._z_index)

    def _toggle_play(self):
        if self._playing:
            self._play_timer.stop()
            self._playing = False
            self.play_btn.setText("▶ Play")
        else:
            self._play_timer.start(1000 // self.fps_spin.value())
            self._playing = True
            self.play_btn.setText("⏹ Stop")

    def _advance_z(self):
        self._step_z(1)

    @pyqtSlot(int)
    def _on_hover(self, label_id: int):
        if label_id > 0:
            self.hover_lbl.setText(f"Cell ID: {label_id}")
        else:
            self.hover_lbl.setText("Background")

    def _export_view(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save view as PNG", "organoid_view.png",
            "PNG images (*.png)")
        if path:
            self.canvas.fig.savefig(path, dpi=200, bbox_inches="tight",
                                    facecolor=self.canvas.fig.get_facecolor())

    def _set_controls_enabled(self, enabled: bool):
        for w in [self.z_slider, self.prev_btn, self.next_btn,
                  self.play_btn, self.fps_spin, self.ch_combo,
                  self._lo_spin, self._hi_spin, self.cells_chk,
                  self.nuc_chk, self.alpha_sl,
                  self._btn_XY, self._btn_XZ, self._btn_YZ]:
            w.setEnabled(enabled)
