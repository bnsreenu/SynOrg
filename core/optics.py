"""
optics.py  v6
-------------
Added: depth-dependent PSF broadening (scatter_increase_rate).

Instead of one global gaussian_filter, we process the volume in Z-slabs,
applying progressively larger sigma_xy as depth increases:

    sigma_xy(z) = psf_sigma_xy * (1 + scatter_increase_rate * z_um)

This makes deep slices genuinely fuzzier (not just dimmer), matching the
physics of light scattering through thick tissue.

Also respects the `cleared` flag which disables both staining gradient
(handled in signal_generator) and depth-dependent broadening.
"""

import numpy as np
from scipy.ndimage import gaussian_filter

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw): return it

from .parameters import OrganoidParams


class OpticsModel:

    def __init__(self, params: OrganoidParams, use_gpu: bool = False):
        self.p = params

    def apply(self, volume: np.ndarray,
              channel: str = 'fluorescence') -> np.ndarray:
        if channel == 'label':
            return volume.astype(np.float32)

        stages = [
            ("Z-attenuation",  self._apply_z_attenuation),
            ("Haze",           self._apply_haze),
            ("Background",     self._apply_background),
            ("Shot noise",     self._apply_shot_noise),
            ("Read noise",     self._apply_read_noise),
        ]
        vol = volume.astype(np.float32)

        # PSF — depth-dependent or uniform
        vol = self._apply_psf_depth(vol)

        for name, fn in tqdm(stages, desc="  Optics pipeline",
                             unit="stage", ncols=72):
            vol = fn(vol)

        return np.clip(vol, 0.0, 1.0)

    def apply_crosstalk(self, ch_a, ch_b):
        frac  = self.p.optics.crosstalk_fraction
        a_out = np.clip(ch_a + frac * ch_b, 0, 1)
        b_out = np.clip(ch_b + frac * ch_a, 0, 1)
        return a_out, b_out

    # ------------------------------------------------------------------
    # PSF — depth-dependent
    # ------------------------------------------------------------------

    def _apply_psf_depth(self, vol: np.ndarray) -> np.ndarray:
        """
        Apply anisotropic PSF with optional depth-dependent broadening.

        If scatter_increase_rate == 0 or cleared: single global gaussian.
        Otherwise: process in Z-slabs with linearly increasing sigma_xy.
        """
        op = self.p.optics
        vp = self.p.voxel

        sigma_xy0 = op.psf_sigma_xy_um / vp.voxel_size_xy
        sigma_z   = op.psf_sigma_z_um  / vp.voxel_size_z
        rate      = 0.0 if op.cleared else op.scatter_increase_rate

        if rate <= 0.0:
            # Fast path: single global blur
            return gaussian_filter(vol, sigma=[sigma_z, sigma_xy0, sigma_xy0])

        # Depth-dependent path: blur each Z-slab independently
        # We use overlapping slabs and blend to avoid seam artifacts
        out    = np.zeros_like(vol)
        Z      = vol.shape[0]
        slab_h = max(4, Z // 16)   # ~16 slabs

        for z0 in range(0, Z, slab_h):
            z1   = min(Z, z0 + slab_h)
            z_um = float(self._zc_centre(z0, z1, vp.voxel_size_z))

            sigma_xy = sigma_xy0 * (1.0 + rate * z_um)
            # Blur the slab (with a small margin for edge effects)
            margin = max(2, int(sigma_z * 3))
            zs = max(0, z0 - margin)
            ze = min(Z, z1 + margin)

            slab_blurred = gaussian_filter(
                vol[zs:ze],
                sigma=[sigma_z, sigma_xy, sigma_xy]
            )
            # Write only the central region (no margin)
            out[z0:z1] = slab_blurred[z0-zs : z1-zs]

        return out

    @staticmethod
    def _zc_centre(z0, z1, voxel_z):
        return ((z0 + z1) / 2.0) * voxel_z

    # ------------------------------------------------------------------
    # Other stages (unchanged)
    # ------------------------------------------------------------------

    def _apply_z_attenuation(self, vol):
        op = self.p.optics; vp = self.p.voxel
        d  = np.arange(vol.shape[0], dtype=np.float32) * vp.voxel_size_z
        coeff = 0.0001 if op.cleared else op.z_attenuation_coeff
        return vol * np.exp(-d * coeff).reshape(-1,1,1)

    def _apply_haze(self, vol):
        op = self.p.optics; vp = self.p.voxel
        amp = 0.01 if op.cleared else op.haze_amplitude
        if amp <= 0: return vol
        s   = op.haze_sigma_um / vp.voxel_size_xy
        return vol + gaussian_filter(vol, [s*0.4, s, s]) * amp

    def _apply_background(self, vol):
        return vol + self.p.optics.background_level

    def _apply_shot_noise(self, vol):
        op  = self.p.optics
        rng = np.random.default_rng(self.p.random_seed + 99)
        sc  = 1.0 / (op.shot_noise_scale**2)
        return rng.poisson(np.maximum(vol*sc, 0)).astype(np.float32) / sc

    def _apply_read_noise(self, vol):
        op  = self.p.optics
        rng = np.random.default_rng(self.p.random_seed + 100)
        return vol + rng.normal(0, op.read_noise_std, vol.shape).astype(np.float32)
