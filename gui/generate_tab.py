"""
generate_tab.py — Tab 1: Design and Generate

Three-panel layout:
  Left   — ModelLibrary (preset management)
  Centre — ParamEditor  (sliders for all parameters)
  Right  — Live preview + generation controls
"""

import json
import math
import time
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QSlider, QSpinBox, QComboBox,
    QProgressBar, QGroupBox, QFileDialog, QInputDialog,
    QMessageBox, QSizePolicy, QFrame, QRadioButton, QButtonGroup,
    QLineEdit,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QFont

from .model_library import ModelLibrary
from .param_editor import ParamEditor
from .image_canvas import ImageCanvas
from .workers import PreviewWorker, GenerationWorker
from .theme import ACCENT, TEXT_DIM, BG_PANEL, WARNING, SUCCESS, DANGER

PRESETS_DIR = Path(__file__).parent.parent / "presets"


class GenerateTab(QWidget):
    """Tab 1 — design and generate organoids."""

    # Signal emitted when a file has been generated (so viewer tab can load it)
    fileGenerated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview_worker    = None
        self._generation_worker = None
        self._current_preset    = None
        self._unsaved_changes   = False
        self._build_ui()

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)
        root.addWidget(splitter)

        # ── Left: model library ──
        self.library = ModelLibrary()
        self.library.setFixedWidth(220)
        self.library.modelLoaded.connect(self._on_model_loaded)
        splitter.addWidget(self.library)

        # ── Centre: parameter editor + save bar ──
        centre = QWidget()
        centre_lay = QVBoxLayout(centre)
        centre_lay.setContentsMargins(6, 6, 6, 6)
        centre_lay.setSpacing(6)

        # Current model header
        hdr = QHBoxLayout()
        self.model_lbl = QLabel("No preset loaded  — using defaults")
        self.model_lbl.setStyleSheet(f"color:{ACCENT}; font-weight:bold; font-size:13px;")
        hdr.addWidget(self.model_lbl)
        hdr.addStretch()
        self.changed_lbl = QLabel("● unsaved")
        self.changed_lbl.setStyleSheet(f"color:{WARNING};")
        self.changed_lbl.hide()
        hdr.addWidget(self.changed_lbl)
        centre_lay.addLayout(hdr)

        # Editor
        self.editor = ParamEditor()
        self.editor.paramsChanged.connect(self._on_params_changed)
        centre_lay.addWidget(self.editor)

        # Save/reset bar
        save_bar = QHBoxLayout()
        self.save_btn = QPushButton("💾  Save to preset")
        self.save_btn.clicked.connect(self._save_preset)
        save_bar.addWidget(self.save_btn)

        self.saveas_btn = QPushButton("💾  Save as new...")
        self.saveas_btn.clicked.connect(self._save_as_new)
        save_bar.addWidget(self.saveas_btn)

        self.reset_btn = QPushButton("↺  Reset to defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        save_bar.addWidget(self.reset_btn)
        centre_lay.addLayout(save_bar)

        splitter.addWidget(centre)

        # ── Right: preview + generate ──
        right = QWidget()
        right.setMinimumWidth(300)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(6, 6, 6, 6)
        right_lay.setSpacing(8)

        # Preview canvas
        preview_grp = QGroupBox("Live Preview  (mid-Z slice)")
        preview_lay = QVBoxLayout(preview_grp)
        preview_lay.setContentsMargins(4, 4, 4, 4)
        self.preview_canvas = ImageCanvas()
        self.preview_canvas.setMinimumHeight(280)
        preview_lay.addWidget(self.preview_canvas)

        # Preview controls
        prev_ctrl = QHBoxLayout()
        self.preview_btn = QPushButton("🔄  Update Preview")
        self.preview_btn.setObjectName("primary")
        self.preview_btn.clicked.connect(self._run_preview)
        prev_ctrl.addWidget(self.preview_btn)

        self.preview_status = QLabel("Click to generate preview")
        self.preview_status.setObjectName("dim")
        prev_ctrl.addWidget(self.preview_status)
        preview_lay.addLayout(prev_ctrl)
        right_lay.addWidget(preview_grp)

        # Generation controls
        gen_grp = QGroupBox("Generate Full Organoid")
        gen_lay = QVBoxLayout(gen_grp)
        gen_lay.setSpacing(6)

        # ── N cells ────────────────────────────────────────────────
        ncells_grp = QGroupBox("Cell count target")
        ncells_grp.setToolTip(
            "Automatically sets organoid diameter to produce approximately "
            "this many cells.  Bidirectional: editing diameter also updates "
            "this estimate.")
        ncells_lay = QVBoxLayout(ncells_grp)
        ncells_lay.setSpacing(4)

        ncells_row = QHBoxLayout()
        ncells_row.addWidget(QLabel("Target N cells:"))
        self.ncells_spin = QSpinBox()
        self.ncells_spin.setRange(5, 10000)
        self.ncells_spin.setValue(200)
        self.ncells_spin.setSingleStep(10)
        self.ncells_spin.setFixedWidth(90)
        self.ncells_spin.setToolTip("Approximate number of cells in the organoid.")
        ncells_row.addWidget(self.ncells_spin)
        ncells_lay.addLayout(ncells_row)

        self.ncells_info = QLabel("≈ 200 cells  |  diameter ~115 µm")
        self.ncells_info.setObjectName("dim")
        ncells_lay.addWidget(self.ncells_info)

        apply_ncells_btn = QPushButton("Apply → set diameter")
        apply_ncells_btn.setToolTip(
            "Calculate and set the diameter slider to produce the target cell count.")
        apply_ncells_btn.clicked.connect(self._apply_ncells)
        ncells_lay.addWidget(apply_ncells_btn)
        gen_lay.addWidget(ncells_grp)

        # Seed
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Seed:"))
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 99999)
        self.seed_spin.setValue(42)
        self.seed_spin.setFixedWidth(80)
        seed_row.addWidget(self.seed_spin)
        rand_btn = QPushButton("🎲")
        rand_btn.setFixedWidth(36)
        rand_btn.setToolTip("Random seed")
        rand_btn.clicked.connect(
            lambda: self.seed_spin.setValue(
                __import__("random").randint(0, 99999)))
        seed_row.addWidget(rand_btn)
        seed_row.addStretch()
        gen_lay.addLayout(seed_row)

        # Output directory
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.out_edit = QLineEdit("output")
        out_row.addWidget(self.out_edit)
        browse_btn = QPushButton("📁")
        browse_btn.setFixedWidth(36)
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)
        gen_lay.addLayout(out_row)

        # Generate button
        self.gen_btn = QPushButton("▶  Generate Organoid!")
        self.gen_btn.setObjectName("primary")
        self.gen_btn.setMinimumHeight(40)
        self.gen_btn.clicked.connect(self._run_generation)
        gen_lay.addWidget(self.gen_btn)

        # Progress
        self.gen_progress = QProgressBar()
        self.gen_progress.setRange(0, 100)
        self.gen_progress.setValue(0)
        gen_lay.addWidget(self.gen_progress)

        self.gen_status = QLabel("")
        self.gen_status.setObjectName("dim")
        self.gen_status.setWordWrap(True)
        gen_lay.addWidget(self.gen_status)

        right_lay.addWidget(gen_grp)
        right_lay.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([220, 520, 340])

        # Load defaults on startup
        self.editor.load_defaults()

    # ── Model library signals ────────────────────────────────────────

    @pyqtSlot(dict, str)
    def _on_model_loaded(self, params: dict, name: str):
        self._current_preset = name
        self.model_lbl.setText(f"Preset: {name}")
        self.editor.load_params_dict(params)
        self._unsaved_changes = False
        self.changed_lbl.hide()

    # ── Parameter changes ────────────────────────────────────────────

    @pyqtSlot(dict)
    def _on_params_changed(self, params: dict):
        if self._current_preset:
            self._unsaved_changes = True
            self.changed_lbl.show()
        self._refresh_ncells_estimate(params)

    def _apply_ncells(self):
        """
        Compute diameter that gives ~N cells, update the diameter slider,
        and refresh the info label.
        """
        n      = self.ncells_spin.value()
        params = self.editor.get_params_dict()
        r_core  = params.get("cells", {}).get("cell_radius_core",  6.5)
        r_periph= params.get("cells", {}).get("cell_radius_periph", 10.0)
        sp      = params.get("shape", {}).get("sphericity", 0.92)

        r_mean   = (r_core + r_periph) / 2.0
        vol_cell = (4/3) * math.pi * r_mean**3
        vol_org  = n * vol_cell / 0.64
        r_org    = (vol_org / ((4/3) * math.pi * sp)) ** (1/3)
        d_um     = round(r_org * 2)

        # Push diameter back into param editor
        row = self.editor._rows.get(("shape", "diameter_um"))
        if row:
            row.set_value(float(d_um))

        self.ncells_info.setText(
            f"≈ {n} cells  |  diameter set to {d_um} µm")

    def _refresh_ncells_estimate(self, params: dict):
        """
        When diameter or cell radius changes, update the N cells estimate
        shown in the info label (does NOT change the spin value).
        """
        try:
            d       = params.get("shape", {}).get("diameter_um", 150.0)
            r_core  = params.get("cells", {}).get("cell_radius_core",  6.5)
            r_periph= params.get("cells", {}).get("cell_radius_periph", 10.0)
            sp      = params.get("shape", {}).get("sphericity", 0.92)
            r_mean  = (r_core + r_periph) / 2.0
            vol_cell= (4/3) * math.pi * r_mean**3
            r_org   = d / 2.0
            vol_org = (4/3) * math.pi * r_org**2 * (r_org * sp)
            n_est   = max(1, int(vol_org * 0.64 / vol_cell))
            self.ncells_info.setText(
                f"≈ {n_est} cells at current diameter ({d:.0f} µm)")
        except Exception:
            pass

    def _get_params_with_seed(self) -> dict:
        d = self.editor.get_params_dict()
        d.setdefault("output", {})
        # Seed is a top-level parameter
        return d

    # ── Save / load ──────────────────────────────────────────────────

    def _save_preset(self):
        if not self._current_preset:
            self._save_as_new()
            return
        params = self.editor.get_params_dict()
        self.library.save_preset(self._current_preset, params)
        self._unsaved_changes = False
        self.changed_lbl.hide()
        self.gen_status.setText(f"Saved preset: {self._current_preset}")

    def _save_as_new(self):
        name, ok = QInputDialog.getText(
            self, "Save as new preset", "Preset name:",
            text=self._current_preset + "_v2" if self._current_preset else "my_organoid")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_").lower()

        desc, ok2 = QInputDialog.getText(
            self, "Description",
            "Brief description (optional):", text="")

        params = self.editor.get_params_dict()
        self.library.save_preset(name, params, description=desc)
        self._current_preset = name
        self.model_lbl.setText(f"Preset: {name}")
        self._unsaved_changes = False
        self.changed_lbl.hide()

    def _reset_defaults(self):
        self.editor.load_defaults()
        self._unsaved_changes = True
        if self._current_preset:
            self.changed_lbl.show()

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory",
                                              self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    # ── Preview ──────────────────────────────────────────────────────

    def _run_preview(self):
        if self._preview_worker and self._preview_worker.isRunning():
            return

        self.preview_btn.setEnabled(False)
        self.preview_status.setText("Generating preview...")
        self.preview_canvas.clear()

        params = self.editor.get_params_dict()

        self._preview_worker = PreviewWorker(params)
        self._preview_worker.finished.connect(self._on_preview_done)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.progress.connect(
            lambda s: self.preview_status.setText(s))
        self._preview_worker.start()

    @pyqtSlot(object, object, object)
    def _on_preview_done(self, dapi, actin, labels):
        self.preview_canvas.set_slices(dapi, actin, labels)
        self.preview_canvas.set_mode("merge")
        self.preview_btn.setEnabled(True)
        self.preview_status.setText("Preview ready")

    @pyqtSlot(str)
    def _on_preview_error(self, msg):
        self.preview_btn.setEnabled(True)
        self.preview_status.setText("Preview failed — see console")
        print(msg)

    # ── Full generation ──────────────────────────────────────────────

    def _run_generation(self):
        if self._generation_worker and self._generation_worker.isRunning():
            return

        params = self.editor.get_params_dict()
        seed   = self.seed_spin.value()
        params.setdefault("random_seed", seed)
        # Set seed as top-level (OrganoidParams.random_seed)
        params["random_seed"] = seed

        # Build auto output path
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        pname   = self._current_preset or "custom"
        outdir  = Path(self.out_edit.text())
        outdir.mkdir(parents=True, exist_ok=True)
        outpath = outdir / f"{pname}_seed{seed}_{ts}.ome.tif"

        self.gen_btn.setEnabled(False)
        self.gen_progress.setValue(0)
        self.gen_status.setText(f"Saving to: {outpath.name}")

        self._generation_worker = GenerationWorker(params, str(outpath))
        self._generation_worker.progress.connect(self._on_gen_progress)
        self._generation_worker.finished.connect(self._on_gen_done)
        self._generation_worker.error.connect(self._on_gen_error)
        self._generation_worker.start()

    @pyqtSlot(int, str)
    def _on_gen_progress(self, pct: int, msg: str):
        self.gen_progress.setValue(pct)
        self.gen_status.setText(msg)

    @pyqtSlot(str)
    def _on_gen_done(self, path: str):
        self.gen_btn.setEnabled(True)
        self.gen_progress.setValue(100)
        self.gen_status.setStyleSheet(f"color:{SUCCESS};")
        self.gen_status.setText(f"✓ Done — {Path(path).name}")
        QTimer.singleShot(3000, lambda: (
            self.gen_status.setStyleSheet(""),
            self.gen_status.setText(f"Last: {Path(path).name}")
        ))
        # Tell viewer tab to load the result
        self.fileGenerated.emit(path)

    @pyqtSlot(str)
    def _on_gen_error(self, msg: str):
        self.gen_btn.setEnabled(True)
        self.gen_progress.setValue(0)
        self.gen_status.setStyleSheet(f"color:{DANGER};")
        self.gen_status.setText("Generation failed — see console")
        print(msg)
