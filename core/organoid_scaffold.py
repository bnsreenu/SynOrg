"""
organoid_scaffold.py
--------------------
Builds a contact-packed organoid using force-directed sphere relaxation.

Strategy
--------
1. Estimate how many cells fit in the organoid volume
2. Place cells randomly inside the organoid
3. Run force-directed relaxation:
   - Repulsion between overlapping cells pushes them apart
   - Weak centripetal force keeps them inside
   - Damped velocity integration → cells settle into contact-packed config
4. Assign per-cell properties (nucleus size, elongation, brightness) by
   radial position — core cells: smaller, rounder, dimmer; periphery: larger

This produces the "balls in a basket" structure: naturally touching, 
smaller cells settling to the interior, a well-defined organoid boundary.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List
from .parameters import OrganoidParams


@dataclass
class Cell:
    """One cell in the organoid."""
    center_um:   np.ndarray   # (3,) z,y,x in µm
    center_vox:  np.ndarray   # (3,) z,y,x in voxels
    cell_radius_um:   float   # cell body radius
    nucleus_radius_um: float  # nucleus radius
    nucleus_axes_um:  np.ndarray  # (3,) semi-axes of nucleus ellipsoid
    orientation:      np.ndarray  # (3,) unit vector — long axis
    radial_pos:  float        # normalised radial distance 0=centre 1=surface
    zone:        str          # 'core' | 'periphery'
    cell_id:     int = 0
    dapi_brightness:  float = 1.0
    actin_brightness: float = 1.0
    # Net radial scale for power-diagram territory:
    #   > 1.0 → cell territory stretches radially (apical-basal elongation)
    #   < 1.0 → cell territory compressed radially (surface flattening)
    #   1.0   → isotropic (sphere-like, default)
    cell_apical_scale: float = 1.0


class OrganoidScaffold:

    def __init__(self, params: OrganoidParams):
        self.p   = params
        self.rng = np.random.default_rng(params.random_seed)

        vp = params.voxel
        op = params.shape
        out = params.output

        # Physical centre of the volume
        self.center_um = np.array([
            out.vol_z * vp.voxel_size_z  / 2.0,
            out.vol_y * vp.voxel_size_xy / 2.0,
            out.vol_x * vp.voxel_size_xy / 2.0,
        ])

        # Organoid radius (with slight per-instance variation)
        base_r = op.diameter_um / 2.0
        self.organoid_radius_um = max(
            15.0,
            base_r + self.rng.normal(0, op.diameter_std_um / 2)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_cells(self) -> List[Cell]:
        """Main entry point — returns contact-packed list of Cell objects."""
        n_cells = self._estimate_cell_count()
        positions = self._initial_placement(n_cells)
        radii     = self._assign_cell_radii(positions)
        positions, radii = self._relax(positions, radii)
        return self._build_cells(positions, radii)

    # ------------------------------------------------------------------
    # Step 1: Estimate cell count
    # ------------------------------------------------------------------

    def _estimate_cell_count(self) -> int:
        """
        How many cells fit?  Use random packing fraction ~0.64 for spheres.
        Average cell radius = midpoint of core/periph values.
        """
        cp = self.p.cells
        avg_r  = (cp.cell_radius_core + cp.cell_radius_periph) / 2.0
        vol_org = (4/3) * np.pi * self.organoid_radius_um ** 3
        vol_cell = (4/3) * np.pi * avg_r ** 3
        packing = 0.62   # random close packing fraction
        n = int(packing * vol_org / vol_cell)
        return max(5, n)

    # ------------------------------------------------------------------
    # Step 2: Initial placement
    # ------------------------------------------------------------------

    def _initial_placement(self, n: int) -> np.ndarray:
        """
        Place n cell centres randomly inside the organoid ellipsoid.
        Returns array (n, 3) in µm.
        """
        sp = self.p.shape.sphericity
        R  = self.organoid_radius_um
        positions = []
        attempts  = 0
        lumen_frac = self.p.cells.lumen_fraction
        while len(positions) < n and attempts < n * 200:
            attempts += 1
            # Uniform in sphere via rejection
            pt = self.rng.uniform(-1, 1, 3) * R
            # Apply sphericity (flatten z)
            pt_scaled = pt.copy()
            pt_scaled[0] *= sp
            r_norm = np.linalg.norm(pt_scaled / R)
            # Reject if outside organoid OR inside lumen exclusion zone
            if r_norm <= 0.92 and r_norm >= lumen_frac:
                positions.append(self.center_um + pt_scaled)
        return np.array(positions[:n])

    # ------------------------------------------------------------------
    # Step 3: Assign initial radii by rough radial position
    # ------------------------------------------------------------------

    def _assign_cell_radii(self, positions: np.ndarray) -> np.ndarray:
        """Initial cell radii — refined again after relaxation."""
        cp  = self.p.cells
        radii = np.zeros(len(positions))
        for i, pos in enumerate(positions):
            r_norm = self._radial_norm(pos)
            t      = np.clip(r_norm / cp.core_fraction, 0, 1)
            mean_r = (1-t) * cp.cell_radius_core + t * cp.cell_radius_periph
            radii[i] = max(4.0,  # hard floor: below 4µm nucleus is unresolvable
                           mean_r * np.exp(self.rng.normal(0, cp.cell_radius_std * 0.3)))
        return radii

    # ------------------------------------------------------------------
    # Step 4: Force-directed relaxation
    # ------------------------------------------------------------------

    def _relax(self, positions: np.ndarray, radii: np.ndarray):
        """
        Force-directed sphere packing — fully vectorized with numpy.
        All pairwise interactions computed as matrix operations: O(N²) 
        memory but no Python loops over cell pairs. Fast for N < 1000.
        """
        pp  = self.p.packing
        sp  = self.p.shape.sphericity
        R   = self.organoid_radius_um
        n   = len(positions)

        pos = positions.copy()
        vel = np.zeros_like(pos)
        r   = radii.copy()

        # Precompute min-distance matrix: min_dist[i,j] = r[i]+r[j]
        min_dist_mat = r[:, None] + r[None, :]   # (N, N)

        for iteration in range(pp.n_iterations):
            # -- Vectorized pairwise repulsion --
            # diff[i,j] = pos[i] - pos[j],  shape (N, N, 3)
            diff = pos[:, None, :] - pos[None, :, :]
            # dist[i,j] = |pos[i] - pos[j]|, shape (N, N)
            dist = np.linalg.norm(diff, axis=-1)
            np.fill_diagonal(dist, np.inf)   # ignore self

            overlap = min_dist_mat - dist    # positive where overlapping
            mask = (overlap > 0) & (dist > 1e-6)

            # Force magnitude per pair
            f_mag = np.where(mask, pp.repulsion_strength * overlap, 0.0)
            # Unit direction (N, N, 3)
            safe_dist = np.where(dist > 1e-6, dist, 1.0)
            f_dir = diff / safe_dist[:, :, None]
            # Net force on each cell = sum of forces from all others
            forces = (f_mag[:, :, None] * f_dir).sum(axis=1)   # (N, 3)

            # -- Boundary confinement --
            delta   = pos - self.center_um                      # (N, 3)
            d_sc    = delta.copy()
            d_sc[:, 0] /= sp
            dist_norm = np.linalg.norm(d_sc, axis=1) / R       # (N,)
            boundary = dist_norm - (1.0 - r / R)
            outside  = boundary > 0
            if outside.any():
                dn = np.linalg.norm(delta, axis=1, keepdims=True) + 1e-8
                f_bound = (-delta / dn) * (boundary * pp.boundary_strength * R)[:, None]
                forces[outside] += f_bound[outside]

            # -- Weak centripetal gravity --
            to_c = self.center_um - pos
            dc   = np.linalg.norm(to_c, axis=1, keepdims=True) + 1e-8
            forces += 0.015 * to_c / dc

            # -- Lumen repulsion: push cells outward if they drift inside --
            lumen_frac = self.p.cells.lumen_fraction
            if lumen_frac > 0.0:
                lumen_r = lumen_frac * R
                delta_c  = pos - self.center_um
                d_sc     = delta_c.copy()
                d_sc[:, 0] /= sp
                dist_c   = np.linalg.norm(d_sc, axis=1)
                inside_lumen = dist_c < lumen_r
                if inside_lumen.any():
                    outward = delta_c / (np.linalg.norm(delta_c, axis=1,
                                                         keepdims=True) + 1e-8)
                    penetration = lumen_r - dist_c
                    forces[inside_lumen] += (outward[inside_lumen] *
                                             (penetration[inside_lumen,None] *
                                              pp.boundary_strength * 1.5))

            # -- Damped velocity integration --
            vel = (vel + forces) * pp.damping
            pos = pos + vel

        final_radii = self._assign_cell_radii(pos)
        return pos, final_radii

    # ------------------------------------------------------------------
    # Step 5: Build Cell objects
    # ------------------------------------------------------------------

    def _build_cells(self, positions: np.ndarray, radii: np.ndarray) -> List[Cell]:
        cp  = self.p.cells
        vp  = self.p.voxel
        tp  = self.p.texture
        cells = []

        for i, (pos, r_cell) in enumerate(zip(positions, radii)):
            r_norm = self._radial_norm(pos)
            t      = np.clip(r_norm / cp.core_fraction, 0, 1)
            zone   = 'core' if r_norm < cp.core_fraction else 'periphery'

            # Nucleus radius as fraction of cell radius
            nc_ratio = (1-t)*cp.nc_ratio_core + t*cp.nc_ratio_periph
            r_nuc    = r_cell * nc_ratio

            # Elongation — mild, max ~20% deviation from sphere
            elong = (1-t)*cp.elongation_core + t*cp.elongation_periph
            elong = float(np.clip(
                elong + self.rng.normal(0, 0.03),
                0.75, 1.0   # hard clamp: never more elongated than 4:5
            ))

            # Nucleus semi-axes: long axis = r_nuc, short = r_nuc * elong
            nuc_axes = np.array([r_nuc, r_nuc * elong, r_nuc * elong])

            # Orientation: periphery cells point radially; core cells random
            if zone == 'periphery':
                direction = pos - self.center_um
                norm = np.linalg.norm(direction)
                orientation = direction / norm if norm > 1e-6 \
                              else self.rng.normal(0, 1, 3)
            else:
                orientation = self.rng.normal(0, 1, 3)
            orientation /= np.linalg.norm(orientation)

            # ── Cell territory shape (apical-basal elongation + surface flattening) ──
            # cell_apical_scale > 1 → territory taller radially than tangentially
            #                         (columnar epithelium, peripheral cells)
            # cell_apical_scale < 1 → territory flatter radially
            #                         (outermost squamous-like layer)
            # Both effects ramp smoothly with radial position so there is no
            # abrupt boundary between zones.

            # Apical elongation: ramps from 0 at core_fraction to full at surface
            t_apical = np.clip((r_norm - cp.core_fraction) /
                                (1.0 - cp.core_fraction + 1e-6), 0.0, 1.0)
            apical_scale = 1.0 + t_apical * cp.apical_elongation

            # Surface flattening: ramps up only in the outermost 15% of radius
            t_flat = np.clip((r_norm - 0.85) / 0.15, 0.0, 1.0)
            flat_scale = 1.0 - t_flat * cp.surface_flattening

            # Combine: elongation and flattening act in opposite directions;
            # at the very surface, flattening wins if surface_flattening is set.
            cell_apical_scale = float(apical_scale * flat_scale)

            # Voxel centre
            center_vox = np.array([
                pos[0] / vp.voxel_size_z,
                pos[1] / vp.voxel_size_xy,
                pos[2] / vp.voxel_size_xy,
            ])

            # Brightness
            base_dapi  = (1-t)*tp.dapi_brightness_core  + t*tp.dapi_brightness_periph
            base_actin = (1-t)*tp.actin_brightness_core + t*tp.actin_brightness_periph
            dapi_b  = float(base_dapi  * np.exp(self.rng.normal(0, tp.dapi_intensity_sigma)))
            actin_b = float(base_actin * np.exp(self.rng.normal(0, tp.actin_intensity_sigma)))

            cells.append(Cell(
                center_um=pos,
                center_vox=center_vox,
                cell_radius_um=float(r_cell),
                nucleus_radius_um=float(r_nuc),
                nucleus_axes_um=nuc_axes,
                orientation=orientation,
                radial_pos=float(r_norm),
                zone=zone,
                cell_id=i,
                dapi_brightness=dapi_b,
                actin_brightness=actin_b,
                cell_apical_scale=cell_apical_scale,
            ))

        return cells

    # ------------------------------------------------------------------
    # Geometry helper
    # ------------------------------------------------------------------

    def _radial_norm(self, pos: np.ndarray) -> float:
        """Normalised radial distance: 0=centre, 1=organoid surface."""
        delta    = pos - self.center_um
        sp       = self.p.shape.sphericity
        d_scaled = delta.copy()
        d_scaled[0] /= sp
        return float(np.linalg.norm(d_scaled) / self.organoid_radius_um)
