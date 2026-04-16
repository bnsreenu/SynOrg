"""
param_editor.py — Centre panel: scrollable parameter editor.

Each parameter group (Shape, Cells, Optics, Output) is a collapsible
section. Every parameter has a slider + spinbox pair that stay in sync.
Tooltips describe biological meaning.
"""

import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QSlider, QDoubleSpinBox, QSpinBox,
    QGroupBox, QPushButton, QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from .theme import ACCENT, TEXT_DIM, BG_PANEL, WARNING


# ── Parameter definitions ────────────────────────────────────────────

PARAMS = [
    # (section, key, label, min, max, step, decimals, tooltip, unit)
    ("shape", "diameter_um",       "Diameter",         30,  300, 5,    0, "Overall organoid size. Sets approximate cell count (see N Cells control in Generate panel).", "µm"),
    ("shape", "diameter_std_um",   "Size variation",    0,   40, 1,    0, "Run-to-run size variation. 0 = exact size every time.", "µm"),
    ("shape", "sphericity",        "Sphericity",       0.7,  1.0, 0.01, 2, "1.0=perfect sphere. Lower=flattened along Z axis.", ""),

    ("cells", "cell_radius_core",  "Cell radius (core)",  4, 16, 0.5, 1, "Radius of inner core cells (min 4µm — below this nuclei become unresolvable at 0.414µm/px).", "µm"),
    ("cells", "cell_radius_periph","Cell radius (periph)",5, 20, 0.5, 1, "Radius of peripheral cells. Must be ≥ cell_radius_core.", "µm"),
    ("cells", "cell_radius_std",   "Cell size variation", 0,  3, 0.1, 1, "Cell-to-cell size variation (lognormal). Higher = more heterogeneous.", "µm"),
    ("cells", "nc_ratio_core",     "NC ratio (core)",   0.45, 0.85, 0.01, 2, "Nucleus/cell radius ratio in core. Cancer cells ~0.65–0.75.", ""),
    ("cells", "nc_ratio_periph",   "NC ratio (periph)", 0.45, 0.85, 0.01, 2, "Nucleus/cell radius ratio at periphery.", ""),
    ("cells", "pressure_core",     "Pressure (core)",   0.0,  0.40, 0.01, 2, "Cell compression in core. 0=touching, 0.35=heavily compressed.", ""),
    ("cells", "pressure_periph",   "Pressure (periph)", 0.0,  0.20, 0.01, 2, "Cell compression at periphery. Usually 3-4x lower than core.", ""),
    ("cells", "radial_compression","Radial compression", 0.0,  0.35, 0.01, 2, "Oblate flattening of core cells along radial axis. 0=sphere.", ""),
    ("cells", "elongation_core",   "Nucleus elong. (core)",   0.65, 1.0, 0.01, 2, "Nucleus short/long axis in core. 1=sphere, 0.7=elongated.", ""),
    ("cells", "elongation_periph", "Nucleus elong. (periph)", 0.55, 1.0, 0.01, 2, "Nucleus elongation at periphery. Lower=more columnar.", ""),
    ("cells", "nucleus_irregularity","Nucleus irregularity",  0.0, 0.45, 0.01, 2, "Surface deformation. 0=ellipsoid, 0.35=kidney/bean shape.", ""),
    ("cells", "nucleus_ecc_periph","Nucleus eccentricity",    0.0,  0.40, 0.01, 2, "How far peripheral nuclei are pushed toward outer surface.", ""),
    ("cells", "core_fraction",     "Core fraction",     0.3,  0.75, 0.01, 2, "Fraction of organoid radius considered 'core'.", ""),
    ("cells", "lumen_fraction",    "Lumen fraction",    0.0,  0.80, 0.01, 2, "Hollow lumen radius as fraction of organoid radius. 0=solid spheroid, 0.5=thin shell (cyst). Cells are excluded from inside this radius.", ""),
    ("cells", "apical_elongation", "Apical elongation", 0.0,  0.60, 0.01, 2, "Radial stretch of peripheral cell territories. 0=sphere-like (default), 0.25=mild columnar epithelium, 0.50=clearly columnar (intestinal crypt). Ramps from core_fraction to organoid surface.", ""),
    ("cells", "surface_flattening","Surface flattening",0.0,  0.60, 0.01, 2, "Radial compression of the outermost cell layer (~15% of radius). 0=no effect, 0.30=visible squamous outer layer, 0.55=strongly flattened. Mimics cells pressed against ECM/air interface.", ""),

    ("optics","psf_sigma_xy_um",   "PSF XY",            0.10, 0.60, 0.01, 2, "Lateral PSF blur. Match to objective NA. 0.20=high NA confocal.", "µm"),
    ("optics","psf_sigma_z_um",    "PSF Z",             0.40, 3.0,  0.05, 2, "Axial PSF blur. Always larger than XY. 0.65=lightsheet, 1.2=confocal.", "µm"),
    ("optics","z_attenuation_coeff","Z attenuation",     0.001,0.015,0.001,3, "Light intensity falloff with depth. Higher=darker bottom half.", ""),
    ("optics","staining_depth_um", "Staining depth",    5.0, 9999.0, 5.0, 0, "Half-penetration depth of dye/antibody from organoid surface. 9999=uniform.", "µm"),
    ("optics","scatter_increase_rate","Scatter rate",    0.0,  0.012, 0.001,3, "PSF broadening per µm depth. 0=cleared, 0.003=confocal, 0.008=widefield.", ""),
    ("optics","haze_amplitude",    "Haze",              0.0,  0.25, 0.01, 2, "Out-of-focus glow from adjacent planes.", ""),
    ("optics","shot_noise_scale",  "Shot noise",        0.01, 0.12, 0.005,3, "Poisson photon noise level.", ""),
    ("optics","background_level",  "Background",        0.01, 0.12, 0.005,3, "Constant background offset.", ""),
    ("optics","crosstalk_fraction","Channel crosstalk",  0.0,  0.15, 0.005,3, "Bleed-through between DAPI and Actin channels.", ""),

    ("cells","necrotic_fraction",  "Necrotic zone",    0.05, 0.50, 0.01, 2, "Inner radius fraction that becomes necrotic (if necrotic core enabled). Cells here are a bimodal mix: pyknotic (bright/condensed), ghost (dim/dissolved), and karyorrhectic (intermediate).", ""),
    ("cells","necrotic_dapi_boost","Pyknotic boost",   1.0,  3.0,  0.1,  1, "Brightness multiplier for condensed pyknotic nuclei in necrotic zone. Ghost cells (~20%) are always dim regardless of this value.", "x"),

    ("packing","n_iterations",     "Packing iterations",40,  300,  10,  0, "Relaxation steps. More=tighter packing, slower generation.", ""),
    ("packing","repulsion_strength","Repulsion",         0.2,  0.8, 0.05, 2, "Force pushing overlapping cells apart.", ""),
    ("packing","boundary_strength","Boundary force",     0.5,  2.0, 0.1,  1, "Force keeping cells inside organoid.", ""),
]

SECTION_LABELS = {
    "shape":   "🔷  Organoid Shape",
    "cells":   "🔬  Cell & Nucleus",
    "optics":  "🔭  Microscope Optics",
    "packing": "⚙️  Packing (advanced)",
}

SECTION_ORDER = ["shape", "cells", "optics", "packing"]


class ParamRow(QWidget):
    """One parameter: label + slider + spinbox."""
    valueChanged = pyqtSignal(str, str, object)  # section, key, value

    def __init__(self, section, key, label, vmin, vmax, step, decimals,
                 tooltip, unit, parent=None):
        super().__init__(parent)
        self.section  = section
        self.key      = key
        self.decimals = decimals
        self.step     = step
        self._updating = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)

        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setToolTip(tooltip)
        lay.addWidget(lbl)

        self.slider = QSlider(Qt.Horizontal)
        if decimals == 0:
            self.slider.setRange(int(vmin), int(vmax))
        else:
            scale = 10 ** decimals
            self.slider.setRange(int(vmin * scale), int(vmax * scale))
        self.slider.setFixedWidth(120)
        self.slider.setToolTip(tooltip)
        lay.addWidget(self.slider)

        if decimals == 0:
            self.spin = QSpinBox()
            self.spin.setRange(int(vmin), int(vmax))
            self.spin.setSingleStep(max(1, int(step)))
        else:
            self.spin = QDoubleSpinBox()
            self.spin.setRange(vmin, vmax)
            self.spin.setDecimals(decimals)
            self.spin.setSingleStep(step)
        self.spin.setFixedWidth(80)
        self.spin.setToolTip(tooltip)
        if unit:
            self.spin.setSuffix(f" {unit}")
        lay.addWidget(self.spin)

        self.slider.valueChanged.connect(self._slider_changed)
        if decimals == 0:
            self.spin.valueChanged.connect(self._spin_changed_int)
        else:
            self.spin.valueChanged.connect(self._spin_changed_float)

    def get_value(self):
        return self.spin.value()

    def set_value(self, v):
        self._updating = True
        if self.decimals == 0:
            self.spin.setValue(int(round(v)))
            self.slider.setValue(int(round(v)))
        else:
            self.spin.setValue(float(v))
            scale = 10 ** self.decimals
            self.slider.setValue(int(round(float(v) * scale)))
        self._updating = False

    def _slider_changed(self, sv):
        if self._updating: return
        self._updating = True
        if self.decimals > 0:
            v = sv / (10 ** self.decimals)
            self.spin.setValue(v)
        else:
            self.spin.setValue(sv)
        self._updating = False
        self.valueChanged.emit(self.section, self.key, self.spin.value())

    def _spin_changed_int(self, v):
        if self._updating: return
        self._updating = True
        self.slider.setValue(int(v))
        self._updating = False
        self.valueChanged.emit(self.section, self.key, v)

    def _spin_changed_float(self, v):
        if self._updating: return
        self._updating = True
        scale = 10 ** self.decimals
        self.slider.setValue(int(round(v * scale)))
        self._updating = False
        self.valueChanged.emit(self.section, self.key, v)


class ParamEditor(QWidget):
    """
    Scrollable panel of parameter sliders grouped by section.
    Emits paramsChanged whenever any value is modified.
    """
    paramsChanged = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows   = {}   # (section, key) -> ParamRow
        self._values = {}   # section -> {key: value}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet(f"background:{BG_PANEL};")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        # Group params by section
        by_section = {s: [] for s in SECTION_ORDER}
        for p in PARAMS:
            by_section[p[0]].append(p)

        for section in SECTION_ORDER:
            grp = QGroupBox(SECTION_LABELS[section])
            grp_lay = QVBoxLayout(grp)
            grp_lay.setSpacing(2)
            grp_lay.setContentsMargins(6, 4, 6, 4)

            for p in by_section[section]:
                sec, key, label, vmin, vmax, step, dec, tip, unit = p
                row = ParamRow(sec, key, label, vmin, vmax, step, dec, tip, unit)
                row.valueChanged.connect(self._on_value_changed)
                self._rows[(sec, key)] = row
                grp_lay.addWidget(row)

            lay.addWidget(grp)

        lay.addStretch()
        scroll.setWidget(container)

    def _on_value_changed(self, section, key, value):
        if section not in self._values:
            self._values[section] = {}
        self._values[section][key] = value
        self.paramsChanged.emit(self.get_params_dict())

    def get_params_dict(self) -> dict:
        """Return current values as a nested dict matching preset JSON format."""
        result = {}
        for (section, key), row in self._rows.items():
            if section not in result:
                result[section] = {}
            result[section][key] = row.get_value()
        return result

    def load_params_dict(self, d: dict):
        """Load values from a nested dict (preset JSON format)."""
        for section, values in d.items():
            if isinstance(values, dict):
                for key, value in values.items():
                    row = self._rows.get((section, key))
                    if row is not None:
                        row.set_value(value)

    def load_defaults(self):
        """Reset all parameters to their default values from OrganoidParams."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.parameters import OrganoidParams
        p = OrganoidParams()
        d = {}
        for section in SECTION_ORDER:
            obj = getattr(p, section, None)
            if obj:
                d[section] = {}
                for (sec, key), row in self._rows.items():
                    if sec == section and hasattr(obj, key):
                        d[section][key] = getattr(obj, key)
        self.load_params_dict(d)
