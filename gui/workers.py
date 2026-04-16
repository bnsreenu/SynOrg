"""
workers.py — QThread workers so the GUI never freezes.

PreviewWorker   — generates a tiny organoid (fast) for the live preview.
GenerationWorker — runs the full pipeline with progress signals.
LoadWorker      — loads an OME-TIFF from disk in the background.
"""

import sys
import json
import traceback
import numpy as np
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

# Add parent directory to path so we can import core
sys.path.insert(0, str(Path(__file__).parent.parent))


class PreviewWorker(QThread):
    """
    Generates a fast preview organoid (small volume) and emits the
    mid-z DAPI and Actin slices as numpy arrays.
    """
    finished  = pyqtSignal(object, object, object)  # dapi_slice, actin_slice, label_slice
    error     = pyqtSignal(str)
    progress  = pyqtSignal(str)

    def __init__(self, params_dict: dict, parent=None):
        super().__init__(parent)
        self.params_dict = params_dict

    def run(self):
        try:
            from core.parameters import OrganoidParams
            from core.generator import SyntheticOrganoidGenerator

            self.progress.emit("Building preview organoid...")
            p = self._build_params()

            # Force small volume for speed
            p.shape.diameter_um     = min(p.shape.diameter_um, 70.0)
            p.packing.n_iterations  = 60
            p.auto_size_volume()

            import tempfile, os
            tmp = tempfile.mktemp(suffix=".ome.tif")
            gen = SyntheticOrganoidGenerator(p, use_gpu=False)

            self.progress.emit("Rendering preview...")
            gen.generate(tmp, save_labels=True, verbose=False)

            self.progress.emit("Loading preview slices...")
            import tifffile
            data   = tifffile.imread(tmp)
            labels = tifffile.imread(tmp.replace(".ome.tif", "_labels.ome.tif"))

            if data.ndim == 5:   data   = data[0]
            if labels.ndim == 5: labels = labels[0]
            if labels.ndim == 4: labels = labels[0]

            dapi  = data[0].astype(np.float32) / 65535.0
            actin = data[1].astype(np.float32) / 65535.0
            mid_z = dapi.shape[0] // 2

            # Clean up temp files
            for f in [tmp,
                      tmp.replace(".ome.tif","_labels.ome.tif"),
                      tmp.replace(".ome.tif","_nucleus_labels.ome.tif")]:
                try: os.remove(f)
                except: pass

            self.finished.emit(dapi[mid_z], actin[mid_z], labels[mid_z])

        except Exception as e:
            self.error.emit(f"Preview error:\n{traceback.format_exc()}")

    def _build_params(self):
        from core.parameters import OrganoidParams
        p = OrganoidParams()
        d = self.params_dict
        for section, values in d.items():
            obj = getattr(p, section, None)
            if obj and isinstance(values, dict):
                for k, v in values.items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)
        return p


class GenerationWorker(QThread):
    """
    Runs the full organoid generation pipeline.
    Emits step-level progress and the output file path on completion.
    """
    progress  = pyqtSignal(int, str)   # (percent 0-100, message)
    finished  = pyqtSignal(str)         # output path
    error     = pyqtSignal(str)

    def __init__(self, params_dict: dict, output_path: str,
                 save_labels: bool = True, parent=None):
        super().__init__(parent)
        self.params_dict  = params_dict
        self.output_path  = output_path
        self.save_labels  = save_labels

    def run(self):
        try:
            from core.parameters import OrganoidParams
            from core.generator import SyntheticOrganoidGenerator

            self.progress.emit(5, "Building scaffold...")
            p = self._build_params()
            p.auto_size_volume()

            gen = SyntheticOrganoidGenerator(p, use_gpu=False)

            # Monkey-patch generator to emit progress signals
            original_generate = gen.generate

            import time

            def patched_generate(output_path, save_labels=True, verbose=True):
                from core.organoid_scaffold import OrganoidScaffold
                from core.signal_generator import SignalGenerator
                from core.optics import OpticsModel
                from core.io import save_ome_tiff
                from pathlib import Path

                self.progress.emit(5,  "Step 1/4  Placing cells...")
                scaffold = OrganoidScaffold(p)
                gen.cells = scaffold.generate_cells()
                n = len(gen.cells)

                self.progress.emit(20, f"Step 2/4  Rendering signal ({n} cells)...")
                sig = SignalGenerator(p, gen.cells, use_gpu=False)
                dapi_raw  = gen._norm(sig.render_dapi())
                actin_raw = gen._norm(sig.render_actin())
                labels    = sig.render_label_mask()      if save_labels else None
                nuc_labels= sig.render_nucleus_label_mask() if save_labels else None

                self.progress.emit(60, "Step 3/4  Applying optics...")
                optics    = OpticsModel(p)
                dapi_out  = gen._norm(optics.apply(dapi_raw))
                actin_out = gen._norm(optics.apply(actin_raw))
                dapi_out, actin_out = optics.apply_crosstalk(dapi_out, actin_out)
                dapi_out  = gen._norm(dapi_out)
                actin_out = gen._norm(actin_out)

                self.progress.emit(85, "Step 4/4  Writing OME-TIFF...")
                path = save_ome_tiff(
                    channels=[dapi_out, actin_out],
                    params=p,
                    output_path=output_path,
                    label_mask=labels,
                    nucleus_label_mask=nuc_labels,
                    image_name=Path(output_path).stem,
                )
                return path

            path = patched_generate(self.output_path, save_labels=self.save_labels)
            self.progress.emit(100, "Done!")
            self.finished.emit(str(path))

        except Exception as e:
            self.error.emit(traceback.format_exc())

    def _build_params(self):
        from core.parameters import OrganoidParams
        p = OrganoidParams()
        d = self.params_dict
        for section, values in d.items():
            obj = getattr(p, section, None)
            if obj and isinstance(values, dict):
                for k, v in values.items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)
        return p


class LoadWorker(QThread):
    """
    Loads an OME-TIFF file in the background, returning all channels
    and both label masks if present.
    """
    finished = pyqtSignal(object)  # dict with loaded data
    error    = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self.filepath = filepath

    def run(self):
        try:
            import tifffile
            self.progress.emit(f"Loading {Path(self.filepath).name}...")

            data = tifffile.imread(self.filepath)
            if data.ndim == 5: data = data[0]

            # Parse voxel sizes from OME-XML
            voxel_xy, voxel_z = 1.0, 1.0
            try:
                tf = tifffile.TiffFile(self.filepath)
                desc = tf.pages[0].description or ""
                import xml.etree.ElementTree as ET
                ns = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}
                root = ET.fromstring(desc)
                pix = root.find(".//ome:Pixels", ns)
                if pix is not None:
                    voxel_xy = float(pix.get("PhysicalSizeX", 1.0))
                    voxel_z  = float(pix.get("PhysicalSizeZ", 1.0))
            except:
                pass

            # Look for companion label files
            p      = Path(self.filepath)
            stem   = p.stem.replace(".ome", "")
            labels_path = p.parent / f"{stem}_labels.ome.tif"
            nuc_path    = p.parent / f"{stem}_nucleus_labels.ome.tif"

            labels     = None
            nuc_labels = None

            if labels_path.exists():
                self.progress.emit("Loading cell labels...")
                lb = tifffile.imread(str(labels_path))
                if lb.ndim == 5: lb = lb[0]
                if lb.ndim == 4: lb = lb[0]
                labels = lb.astype(np.uint16)

            if nuc_path.exists():
                self.progress.emit("Loading nucleus labels...")
                nb = tifffile.imread(str(nuc_path))
                if nb.ndim == 5: nb = nb[0]
                if nb.ndim == 4: nb = nb[0]
                nuc_labels = nb.astype(np.uint16)

            self.finished.emit({
                "data":       data,
                "labels":     labels,
                "nuc_labels": nuc_labels,
                "voxel_xy":   voxel_xy,
                "voxel_z":    voxel_z,
                "filepath":   self.filepath,
            })

        except Exception as e:
            self.error.emit(traceback.format_exc())
