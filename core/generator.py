"""
generator.py  v5
----------------
Orchestrates scaffold → signal → optics (with cross-talk) → IO.
"""

import time
import numpy as np
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw): return it

from .parameters import OrganoidParams
from .organoid_scaffold import OrganoidScaffold
from .signal_generator import SignalGenerator
from .optics import OpticsModel
from .io import save_ome_tiff


class SyntheticOrganoidGenerator:

    def __init__(self, params: OrganoidParams, use_gpu: bool = False):
        self.params  = params
        self.use_gpu = use_gpu
        self.cells   = None

    def generate(self, output_path, save_labels=True, verbose=True) -> Path:
        t0 = time.time()

        if verbose: print("▸ Step 1/4  Building scaffold and packing cells...")
        t1 = time.time()
        scaffold   = OrganoidScaffold(self.params)
        self.cells = scaffold.generate_cells()
        if verbose:
            print(f"  {len(self.cells)} cells placed "
                  f"(r_organoid={scaffold.organoid_radius_um:.1f}µm) "
                  f"[{time.time()-t1:.1f}s]")

        if verbose: print("▸ Step 2/4  Rendering fluorescence signal...")
        t2 = time.time()
        sig       = SignalGenerator(self.params, self.cells, self.use_gpu)
        dapi_raw  = self._norm(sig.render_dapi())
        actin_raw = self._norm(sig.render_actin())
        if save_labels:
            labels         = sig.render_label_mask()
            nucleus_labels = sig.render_nucleus_label_mask()
        else:
            labels = nucleus_labels = None
        if verbose: print(f"  Signal rendered [{time.time()-t2:.1f}s]")

        if verbose: print("▸ Step 3/4  Applying optics...")
        t3 = time.time()
        optics     = OpticsModel(self.params, self.use_gpu)
        dapi_out   = self._norm(optics.apply(dapi_raw))
        actin_out  = self._norm(optics.apply(actin_raw))
        # Channel cross-talk
        dapi_out, actin_out = optics.apply_crosstalk(dapi_out, actin_out)
        dapi_out  = self._norm(dapi_out)
        actin_out = self._norm(actin_out)
        if verbose: print(f"  Optics applied  [{time.time()-t3:.1f}s]")

        if verbose: print("▸ Step 4/4  Writing OME-TIFF...")
        t4 = time.time()
        path = save_ome_tiff(
            channels=[dapi_out, actin_out],
            params=self.params,
            output_path=output_path,
            label_mask=labels,
            nucleus_label_mask=nucleus_labels,
            image_name=Path(output_path).stem,
        )
        if verbose: print(f"  File written    [{time.time()-t4:.1f}s]")

        if verbose:
            print(f"\n✓ Done in {time.time()-t0:.1f}s")
            self._print_stats()
        return path

    def get_cell_stats(self):
        if not self.cells: return {}
        radii = [c.cell_radius_um  for c in self.cells]
        zones = [c.zone            for c in self.cells]
        elong = [c.nucleus_axes_um[2]/c.nucleus_axes_um[0] for c in self.cells]
        return dict(
            n_cells=len(self.cells),
            n_core=zones.count('core'),
            n_periphery=zones.count('periphery'),
            mean_radius_um=float(np.mean(radii)),
            std_radius_um=float(np.std(radii)),
            mean_elongation=float(np.mean(elong)),
        )

    @staticmethod
    def _norm(a):
        mn, mx = a.min(), a.max()
        return (a-mn)/(mx-mn+1e-8) if mx-mn > 1e-8 else np.zeros_like(a)

    def _print_stats(self):
        s = self.get_cell_stats()
        print(f"\n  Cell statistics:")
        print(f"    Total      : {s['n_cells']}")
        print(f"    Core       : {s['n_core']}")
        print(f"    Periphery  : {s['n_periphery']}")
        print(f"    Mean radius: {s['mean_radius_um']:.2f} µm")
        print(f"    Mean elong : {s['mean_elongation']:.3f}")
