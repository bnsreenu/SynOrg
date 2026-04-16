"""
image_canvas.py — Reusable matplotlib-in-Qt image display widget.

Used in:
  - Tab 1 (Generate): live preview panel
  - Tab 2 (View Results): full slice navigator

Features:
  - DAPI / Actin / Merge display modes
  - Label overlay with per-cell colouring and adjustable opacity
  - Display range (min/max percentile clipping)
  - Scale bar drawn from voxel size metadata
  - Hover to read label ID
"""

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import ListedColormap
import matplotlib.colors as mcolors
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import pyqtSignal, Qt

from .theme import BG_DEEP, BG_PANEL


def _percentile_clip(arr: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Clip array to [lo, hi] percentile of non-zero values."""
    nz = arr[arr > 0.001]
    if len(nz) == 0:
        return arr
    vmin = np.percentile(nz, lo)
    vmax = np.percentile(nz, hi)
    if vmax <= vmin:
        vmax = vmin + 1e-6
    return np.clip((arr - vmin) / (vmax - vmin), 0, 1)


def _label_rgba(label_slice: np.ndarray, alpha: float = 0.35) -> np.ndarray:
    """Convert integer label array to RGBA image with random-but-stable colours."""
    h, w   = label_slice.shape
    rgba   = np.zeros((h, w, 4), dtype=np.float32)
    unique = np.unique(label_slice)
    unique = unique[unique > 0]

    # Generate stable colours from cell ID (reproducible)
    rng = np.random.default_rng(42)
    n_colours = max(20, int(unique.max()) + 1) if len(unique) else 20
    colours = rng.uniform(0.3, 1.0, (n_colours, 3)).astype(np.float32)

    for uid in unique:
        mask = label_slice == uid
        c    = colours[int(uid) % n_colours]
        rgba[mask, :3] = c
        rgba[mask, 3]  = alpha

    return rgba


class ImageCanvas(FigureCanvas):
    """
    A matplotlib canvas that displays one 2D image slice with optional
    label overlay. Designed to be embedded in any Qt layout.
    """
    hoveredLabel = pyqtSignal(int)   # emits label ID under cursor (0=background)

    def __init__(self, parent=None, toolbar=False):
        self.fig = Figure(figsize=(5, 5), dpi=100,
                          facecolor=BG_DEEP, edgecolor="none")
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(300, 300)

        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_facecolor(BG_DEEP)
        self.ax.axis("off")
        # State
        self._dapi   = None
        self._actin  = None
        self._labels = None
        self._mode   = "merge"        # "dapi" | "actin" | "merge"
        self._lo     = 1.0            # display percentile min
        self._hi     = 99.5           # display percentile max
        self._show_labels = False
        self._label_alpha = 0.35
        self._voxel_xy    = 0.414     # µm per pixel for scale bar
        self._show_scalebar = True

        # Hover
        self.mpl_connect("motion_notify_event", self._on_hover)

    # ── Public API ──────────────────────────────────────────────────

    def set_slices(self, dapi: np.ndarray, actin: np.ndarray,
                   labels: np.ndarray = None):
        """Set the image data and redraw."""
        self._dapi   = dapi.astype(np.float32)  if dapi   is not None else None
        self._actin  = actin.astype(np.float32) if actin  is not None else None
        self._labels = labels
        self.redraw()

    def set_mode(self, mode: str):
        """'dapi' | 'actin' | 'merge'"""
        self._mode = mode
        self.redraw()

    def set_display_range(self, lo: float, hi: float):
        self._lo = lo
        self._hi = hi
        self.redraw()

    def set_labels_visible(self, visible: bool):
        self._show_labels = visible
        self.redraw()

    def set_label_alpha(self, alpha: float):
        self._label_alpha = alpha
        self.redraw()

    def set_voxel_xy(self, um: float):
        self._voxel_xy = um
        self.redraw()

    def clear(self):
        self._dapi = self._actin = self._labels = None
        self.ax.clear()
        self.ax.set_facecolor(BG_DEEP)
        self.ax.axis("off")
        self.draw()

    # ── Rendering ───────────────────────────────────────────────────

    def redraw(self):
        self.ax.clear()
        self.ax.set_facecolor(BG_DEEP)
        self.ax.axis("off")

        img = self._build_image()
        if img is None:
            self.draw()
            return

        self.ax.imshow(img, interpolation="bilinear", aspect="equal",
                       origin="upper")

        # Label overlay
        if self._show_labels and self._labels is not None:
            rgba = _label_rgba(self._labels, self._label_alpha)
            self.ax.imshow(rgba, interpolation="nearest", aspect="equal",
                           origin="upper")

        # Scale bar
        if self._show_scalebar and self._voxel_xy > 0:
            self._draw_scalebar()

        self.draw()

    def _build_image(self) -> np.ndarray | None:
        """Build RGB display image according to current mode."""
        if self._mode == "dapi" and self._dapi is not None:
            d = _percentile_clip(self._dapi, self._lo, self._hi)
            return np.stack([d * 0.3, d * 0.4, d], axis=-1)   # blue tint

        if self._mode == "actin" and self._actin is not None:
            a = _percentile_clip(self._actin, self._lo, self._hi)
            return np.stack([a * 0.2, a, a * 0.4], axis=-1)   # green tint

        if self._mode == "merge":
            if self._dapi is None and self._actin is None:
                return None
            d = _percentile_clip(self._dapi,  self._lo, self._hi) \
                if self._dapi  is not None else np.zeros_like(self._actin)
            a = _percentile_clip(self._actin, self._lo, self._hi) \
                if self._actin is not None else np.zeros_like(self._dapi)
            # Red=DAPI, Green=Actin, Blue=faint DAPI (matches reference images)
            return np.stack([
                np.clip(d * 1.4, 0, 1),
                np.clip(a * 1.2, 0, 1),
                np.clip(d * 0.15, 0, 1),
            ], axis=-1)

        return None

    def _draw_scalebar(self):
        """Draw a 25µm scale bar in the bottom-left corner."""
        h, w = (self._dapi if self._dapi is not None else self._actin).shape
        bar_um  = 25.0
        bar_px  = bar_um / self._voxel_xy
        margin  = w * 0.04
        y_bar   = h * 0.94
        x_start = margin
        x_end   = margin + bar_px

        self.ax.plot([x_start, x_end], [y_bar, y_bar],
                     color="white", linewidth=2.5, solid_capstyle="butt")
        self.ax.text((x_start + x_end) / 2, y_bar - h * 0.02,
                     f"{bar_um:.0f} µm",
                     color="white", fontsize=8, ha="center", va="bottom",
                     fontfamily="monospace")

    # ── Hover ────────────────────────────────────────────────────────

    def _on_hover(self, event):
        if event.inaxes != self.ax or self._labels is None:
            return
        x, y = int(event.xdata or 0), int(event.ydata or 0)
        h, w = self._labels.shape
        if 0 <= x < w and 0 <= y < h:
            self.hoveredLabel.emit(int(self._labels[y, x]))
