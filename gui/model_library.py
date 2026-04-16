"""
model_library.py — Left panel: preset model library.

Lists all JSON files in presets/, lets users load, create, duplicate,
rename and delete presets. Emits modelLoaded signal when a preset is selected.
"""

import json
import shutil
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QInputDialog, QMessageBox, QMenu,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from .theme import ACCENT, TEXT_DIM, WARNING, DANGER


PRESETS_DIR = Path(__file__).parent.parent / "presets"


class ModelLibrary(QWidget):
    """
    Left panel: shows all presets as a clickable list.
    Signals:
        modelLoaded(dict, str) — emits (params_dict, preset_name) when selected
    """
    modelLoaded = pyqtSignal(dict, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_name = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Header
        hdr = QLabel("Model Library")
        hdr.setObjectName("heading")
        hdr.setStyleSheet(f"color:{ACCENT}; font-size:13px; font-weight:bold;")
        lay.addWidget(hdr)

        sub = QLabel("Click to load · Right-click for options")
        sub.setObjectName("dim")
        sub.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")
        lay.addWidget(sub)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_clicked)
        lay.addWidget(self.list_widget)

        # Buttons
        btn_row1 = QHBoxLayout()
        self.new_btn = QPushButton("＋ New")
        self.new_btn.setToolTip("Create a new preset from current parameters")
        self.new_btn.clicked.connect(self._new_preset)
        btn_row1.addWidget(self.new_btn)

        self.dup_btn = QPushButton("⧉ Duplicate")
        self.dup_btn.setToolTip("Duplicate selected preset")
        self.dup_btn.clicked.connect(self._duplicate_preset)
        btn_row1.addWidget(self.dup_btn)
        lay.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.del_btn = QPushButton("🗑 Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.setToolTip("Delete selected preset (cannot be undone)")
        self.del_btn.clicked.connect(self._delete_preset)
        btn_row2.addWidget(self.del_btn)

        self.reload_btn = QPushButton("↻ Refresh")
        self.reload_btn.clicked.connect(self.refresh)
        btn_row2.addWidget(self.reload_btn)
        lay.addLayout(btn_row2)

        # Status
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("dim")
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)

    # ── Preset file management ───────────────────────────────────────

    def refresh(self):
        """Reload the list from disk."""
        self.list_widget.clear()
        PRESETS_DIR.mkdir(exist_ok=True)

        # Always show defaults first, then user presets
        known_order = [
            "tiny_test", "tumor_spheroid", "pdac_organoid",
            "intestinal_crypt", "breast_cancer", "brain_organoid",
            "prostate_cancer", "hepatic_organoid", "kidney_organoid",
        ]

        all_presets = sorted(
            [p.stem for p in PRESETS_DIR.glob("*.json")],
            key=lambda n: (known_order.index(n) if n in known_order else 999, n)
        )

        for name in all_presets:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            # Read description
            try:
                with open(PRESETS_DIR / f"{name}.json") as f:
                    data = json.load(f)
                desc = data.get("_description", "")
                item.setText(f"  {name}")
                item.setToolTip(desc)
            except:
                item.setText(f"  {name}")
            self.list_widget.addItem(item)

            # Bold the currently selected one
            if name == self._current_name:
                font = item.font()
                font.setBold(True)
                item.setFont(font)

        self.status_lbl.setText(f"{len(all_presets)} presets")

    def get_current_name(self) -> str | None:
        return self._current_name

    def save_preset(self, name: str, params_dict: dict,
                    description: str = ""):
        """Write a preset JSON to disk."""
        data = {}
        if description:
            data["_description"] = description
        data.update(params_dict)
        path = PRESETS_DIR / f"{name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.refresh()
        self.status_lbl.setText(f"Saved: {name}")
        self._select(name)

    def _load_preset(self, name: str) -> dict | None:
        path = PRESETS_DIR / f"{name}.json"
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}

    # ── List interactions ────────────────────────────────────────────

    def _on_item_clicked(self, item):
        name = item.data(Qt.UserRole)
        params = self._load_preset(name)
        if params is not None:
            self._current_name = name
            self.refresh()
            self.modelLoaded.emit(params, name)
            self.status_lbl.setText(f"Loaded: {name}")

    def _select(self, name: str):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == name:
                self.list_widget.setCurrentItem(item)
                break

    # ── Buttons ──────────────────────────────────────────────────────

    def _new_preset(self):
        name, ok = QInputDialog.getText(self, "New Preset",
                                        "Enter preset name:")
        if not ok or not name.strip():
            return
        name = name.strip().replace(" ", "_").lower()
        path = PRESETS_DIR / f"{name}.json"
        if path.exists():
            QMessageBox.warning(self, "Exists",
                f"A preset named '{name}' already exists.")
            return
        # Save with empty params (will use defaults)
        with open(path, "w") as f:
            json.dump({"_description": f"Custom preset: {name}"}, f, indent=2)
        self.refresh()
        self._select(name)
        params = self._load_preset(name) or {}
        self._current_name = name
        self.modelLoaded.emit(params, name)
        self.status_lbl.setText(f"Created: {name} (defaults loaded)")

    def _duplicate_preset(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        src_name = item.data(Qt.UserRole)
        new_name, ok = QInputDialog.getText(
            self, "Duplicate Preset",
            "New preset name:",
            text=f"{src_name}_copy")
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip().replace(" ", "_").lower()
        src  = PRESETS_DIR / f"{src_name}.json"
        dest = PRESETS_DIR / f"{new_name}.json"
        if dest.exists():
            QMessageBox.warning(self, "Exists",
                f"A preset named '{new_name}' already exists.")
            return
        shutil.copy(src, dest)
        self.refresh()
        self._select(new_name)

    def _delete_preset(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        reply = QMessageBox.question(
            self, "Delete preset",
            f"Delete '{name}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            (PRESETS_DIR / f"{name}.json").unlink(missing_ok=True)
            if self._current_name == name:
                self._current_name = None
            self.refresh()

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        name = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("Load", lambda: self._on_item_clicked(item))
        menu.addAction("Duplicate", self._duplicate_preset)
        menu.addSeparator()
        menu.addAction("Delete", self._delete_preset)
        menu.exec_(self.list_widget.mapToGlobal(pos))
