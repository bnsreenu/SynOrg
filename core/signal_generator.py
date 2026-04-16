"""
signal_generator.py  v8
-----------------------
Improvements over v7:

1. CURVED MEMBRANES (not wiggly)
   Each cell's power-diagram region is slightly deformed by a low-frequency
   3D noise field before boundary detection. This causes the cell boundary
   to follow a gently curved, biological path rather than a flat geometric
   face. The noise has large spatial scale (same order as cell size) so it
   bends rather than wiggles.

2. STAINING DIFFUSION GRADIENT (radial from surface)
   After rendering, both DAPI and Actin channels are multiplied by a
   radial staining attenuation map: exp(-d_surface / staining_depth_um).
   This means outer cells stain brilliantly, inner cells progressively
   dimmer — exactly matching antibody/dye penetration physics.

3. NECROTIC CORE
   When enabled, cells in the innermost zone (r < necrotic_fraction) get:
   - Condensed, brighter nuclei (pyknosis: nucleus_radius *= 0.65, brightness *= boost)
   - Zero actin signal (membrane has broken down)
   - 30% of cells in the zone are completely absent (random cell dropout)

These are implemented in signal_generator. Depth-dependent PSF broadening
is in optics.py.
"""

import numpy as np
from scipy.ndimage import zoom, gaussian_filter, distance_transform_edt
from scipy.spatial import KDTree
from typing import List

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw): return it

from .parameters import OrganoidParams
from .organoid_scaffold import Cell


class SignalGenerator:

    def __init__(self, params: OrganoidParams, cells: List[Cell],
                 use_gpu: bool = False):
        self.p     = params
        self.cells = cells
        self.rng   = np.random.default_rng(params.random_seed + 1)

        out = params.output
        vp  = params.voxel
        self.shape = (out.vol_z, out.vol_y, out.vol_x)

        self._zc = np.arange(out.vol_z, dtype=np.float32) * vp.voxel_size_z
        self._yc = np.arange(out.vol_y, dtype=np.float32) * vp.voxel_size_xy
        self._xc = np.arange(out.vol_x, dtype=np.float32) * vp.voxel_size_xy
        self.ZZ, self.YY, self.XX = np.meshgrid(
            self._zc, self._yc, self._xc, indexing='ij')

        self._centre_um = np.array([
            out.vol_z * vp.voxel_size_z  / 2.0,
            out.vol_y * vp.voxel_size_xy / 2.0,
            out.vol_x * vp.voxel_size_xy / 2.0,
        ], dtype=np.float32)

        # Determine necrotic cells (excluded from rendering)
        self._necrotic_ids = self._compute_necrotic_cells()

        # Eccentric nucleus centres
        self._nucleus_centres = self._compute_nucleus_centres()

        print("  Building power-diagram cell map...")
        self.cell_map, self.organoid_mask = self._build_power_diagram()
        n_cell = int((self.cell_map > 0).sum())
        print(f"  Cell map built — {n_cell} voxels in cell bodies")

        # Precompute staining attenuation map (radial from organoid surface)
        print("  Computing staining diffusion map...", end=" ", flush=True)
        self._staining_map = self._compute_staining_map()
        print("done")

    # ------------------------------------------------------------------
    # Necrotic core
    # ------------------------------------------------------------------

    def _compute_necrotic_cells(self):
        """
        Identify cells in the necrotic zone.
        Returns set of cell_ids that are necrotic.
        30% of necrotic-zone cells are randomly dropped entirely (cell dropout).
        """
        cp  = self.p.cells
        ids = set()
        if not cp.necrotic_core:
            return ids

        rng = np.random.default_rng(self.p.random_seed + 999)
        for cell in self.cells:
            if cell.radial_pos < cp.necrotic_fraction:
                # 30% random dropout — cell simply absent
                if rng.random() < 0.30:
                    ids.add(cell.cell_id)
        return ids

    # ------------------------------------------------------------------
    # Nucleus eccentricity
    # ------------------------------------------------------------------

    def _compute_nucleus_centres(self):
        cp = self.p.cells
        centres = {}
        for cell in self.cells:
            t = np.clip(cell.radial_pos / cp.core_fraction, 0, 1)
            ecc = (1-t)*cp.nucleus_ecc_core + t*cp.nucleus_ecc_periph
            offset = ecc * cell.cell_radius_um

            # Direction: blend smoothly from random (core) to outward (periphery).
            # t=0 (centre) → purely random; t=1 (surface) → purely radial outward.
            # This avoids the abrupt switch at core_fraction and gives realistic
            # intermediate-zone nuclei a weak but consistent outward bias.
            outward = cell.center_um - self._centre_um
            norm_out = np.linalg.norm(outward)
            outward_dir = outward / norm_out if norm_out > 1e-6 \
                          else self.rng.normal(0, 1, 3)
            random_dir = self.rng.normal(0, 1, 3)
            random_dir = random_dir / (np.linalg.norm(random_dir) + 1e-8)
            # Smooth blend weight: t² gives a gentler ramp into the periphery
            w = t ** 2
            d = (1.0 - w) * random_dir + w * outward_dir
            d = d / (np.linalg.norm(d) + 1e-8)
            centres[cell.cell_id] = cell.center_um + d * offset
        return centres

    # ------------------------------------------------------------------
    # Staining diffusion map
    # ------------------------------------------------------------------

    def _compute_staining_map(self) -> np.ndarray:
        """
        Radial staining attenuation: exp(-d_surface / depth_um).
        d_surface = 3D distance from nearest organoid surface voxel.
        Computed using distance_transform_edt on the organoid mask.
        Returns float32 array (Z,Y,X) in [0,1].
        """
        op = self.p.optics
        depth = op.staining_depth_um

        # Clearing: no staining gradient
        if op.cleared or depth >= 9000:
            return np.ones(self.shape, dtype=np.float32)

        vp = self.p.voxel
        # Distance transform gives distance in voxels to nearest background
        # Scale to µm (use average voxel size)
        avg_vox = (vp.voxel_size_xy + vp.voxel_size_xy + vp.voxel_size_z) / 3.0
        dist_vox = distance_transform_edt(self.organoid_mask)
        dist_um  = dist_vox.astype(np.float32) * avg_vox

        # 85% exponential decay + 15% residual plateau — matches real
        # uncleared organoid staining: bright outer shell, dim but non-zero interior
        stain = 0.85 * np.exp(-dist_um / depth) + 0.15
        # Only apply inside organoid; outside = 0 anyway
        stain[~self.organoid_mask] = 0.0
        return stain.astype(np.float32)

    # ------------------------------------------------------------------
    # Power-diagram map with CURVED MEMBRANES
    # ------------------------------------------------------------------

    def _build_power_diagram(self):
        """
        Power diagram with membrane-bend deformation.

        Before computing which cell wins each voxel, we add a low-frequency
        3D noise perturbation to the coordinates. This shifts the effective
        Voronoi boundary so it follows a gently curved path rather than the
        flat mathematical face. The noise has spatial scale ~= cell radius,
        so it produces broad curves (bent) not fine wiggles.

        The amplitude is controlled by texture.membrane_bend_amplitude:
          0.0  → perfectly geometric
          0.15 → gently biological (default)
          0.30 → strongly irregular
        """
        cp  = self.p.cells
        op  = self.p.shape
        vp  = self.p.voxel
        out = self.p.output
        tp  = self.p.texture

        n       = len(self.cells)
        centres = np.array([c.center_um      for c in self.cells], dtype=np.float32)
        r_phys  = np.array([c.cell_radius_um for c in self.cells], dtype=np.float32)
        r_norm  = np.array([c.radial_pos     for c in self.cells], dtype=np.float32)

        t_pres   = np.clip(r_norm / cp.core_fraction, 0.0, 1.0)
        pres_fac = (1.0-t_pres)*cp.pressure_core + t_pres*cp.pressure_periph
        r_inf    = r_phys * (1.0 + pres_fac)
        r_clip   = r_phys * (1.0 + pres_fac * 0.6)

        t_comp   = np.clip(1.0 - r_norm/cp.core_fraction, 0.0, 1.0)
        comp_fac = t_comp * cp.radial_compression

        radial_dirs = centres - self._centre_um
        rad_norms   = np.linalg.norm(radial_dirs, axis=1, keepdims=True) + 1e-8
        radial_dirs = (radial_dirs / rad_norms).astype(np.float32)

        # Per-cell apical scale: encodes radial territory stretch/compression.
        # > 1 → cell taller radially than tangentially (columnar/apical-basal)
        # < 1 → cell compressed radially (surface flattening)
        # Combined with radial_compression in the distance metric below.
        apical_scales = np.array([c.cell_apical_scale for c in self.cells],
                                  dtype=np.float32)

        sp = op.sphericity
        dists_c    = np.linalg.norm(centres - self._centre_um, axis=1)
        org_radius = float(np.percentile(dists_c + r_phys, 92))

        c_delta     = centres - self._centre_um
        c_ell       = np.sqrt((c_delta[:,0]/sp)**2 + c_delta[:,1]**2 + c_delta[:,2]**2)
        cell_inside = (c_ell / org_radius) <= 1.0

        K    = min(10, n)
        tree = KDTree(centres)

        cell_map      = np.zeros(self.shape, dtype=np.int32)
        organoid_mask = np.zeros(self.shape, dtype=bool)

        YY_2d, XX_2d = np.meshgrid(self._yc, self._xc, indexing='ij')
        search_r = org_radius + float(r_clip.max()) * 1.05

        # Precompute bend noise field: low-frequency 3D noise (Z,Y,X,3)
        # Spatial scale = avg_cell_radius so boundaries bend at cell scale
        bend_amp = tp.membrane_bend_amplitude
        if bend_amp > 0:
            avg_r_um   = float(r_phys.mean())
            avg_vox_xy = vp.voxel_size_xy
            # Coarse noise grid: ~3 grid points per cell radius
            gs_xy = max(4, int(out.vol_x * avg_vox_xy / (avg_r_um * 3)))
            gs_z  = max(4, int(out.vol_z * vp.voxel_size_z / (avg_r_um * 3)))
            rng_b = np.random.default_rng(self.p.random_seed + 77)
            # Three independent noise volumes for x,y,z displacement
            noise_vols = []
            for _ in range(3):
                coarse = rng_b.standard_normal((gs_z, gs_xy, gs_xy)).astype(np.float32)
                up = zoom(coarse,
                          (out.vol_z/gs_z, out.vol_y/gs_xy, out.vol_x/gs_xy),
                          order=1)
                up = up[:out.vol_z, :out.vol_y, :out.vol_x]
                # Normalise to [-1,1]
                mx = np.abs(up).max()
                if mx > 1e-8: up /= mx
                noise_vols.append(up)
            # Scale to µm — displacement amplitude = bend_amp * avg_cell_radius
            disp_scale = bend_amp * avg_r_um
            # Noise in µm for z, y, x axes
            Dnz = noise_vols[0] * disp_scale * vp.voxel_size_z
            Dny = noise_vols[1] * disp_scale * avg_vox_xy
            Dnx = noise_vols[2] * disp_scale * avg_vox_xy
        else:
            Dnz = Dny = Dnx = None

        for zi in tqdm(range(out.vol_z), desc="  Power diagram",
                       unit="slice", ncols=72):
            z_val = float(self._zc[zi])
            ny, nx = out.vol_y, out.vol_x

            sl = np.stack([
                np.full(ny*nx, z_val, dtype=np.float32),
                YY_2d.ravel(), XX_2d.ravel()
            ], axis=1)

            # Apply membrane-bend displacement to query coordinates
            if bend_amp > 0 and Dnz is not None:
                sl_disp = sl.copy()
                sl_disp[:,0] += Dnz[zi].ravel()
                sl_disp[:,1] += Dny[zi].ravel()
                sl_disp[:,2] += Dnx[zi].ravel()
            else:
                sl_disp = sl

            dz = sl[:,0] - self._centre_um[0]
            dy = sl[:,1] - self._centre_um[1]
            dx = sl[:,2] - self._centre_um[2]
            coarse_d = np.sqrt((dz/sp)**2 + dy**2 + dx**2)
            ext_mask = coarse_d <= search_r

            if not ext_mask.any():
                continue

            ext_idx  = np.where(ext_mask)[0]
            sl_in    = sl_disp[ext_idx]   # displaced coords for competition
            sl_orig  = sl[ext_idx]         # original coords for clip distance
            M        = len(sl_in)

            _, idxs = tree.query(sl_in, k=K, workers=-1)
            F_block = np.full((M, K), np.inf, dtype=np.float32)
            D_block = np.full((M, K), np.inf, dtype=np.float32)

            for ki in range(K):
                ci    = idxs[:, ki]
                ci_c  = centres[ci]
                ci_ri = r_inf[ci]
                ci_cf = comp_fac[ci]
                ci_rd = radial_dirs[ci]
                ci_as = apical_scales[ci]   # per-cell apical/flat scale

                disp     = sl_in - ci_c
                rad_proj = np.einsum('mi,mi->m', disp, ci_rd)
                trans    = disp - rad_proj[:,None]*ci_rd
                trans_sq = np.einsum('mi,mi->m', trans, trans)

                # Radial scale combines three effects (all along the outward axis):
                #   radial_compression: squashes core cells radially (existing)
                #   apical_elongation:  stretches peripheral cells radially (new)
                #   surface_flattening: compresses outermost cells radially (new)
                #
                # comp_fac > 0 → existing compression (scale > 1 → radial distances
                #   appear larger → cell claims less radial territory).
                # ci_as > 1    → apical elongation  (dividing by ci_as shrinks the
                #   effective radial distance → cell claims MORE radial territory).
                # ci_as < 1    → surface flattening (dividing by ci_as expands the
                #   effective radial distance → cell claims LESS radial territory).
                #
                # Combined: scale = (1 + comp_fac) / ci_as
                # When ci_as == 1 and comp_fac == 0: scale = 1 (isotropic, old behaviour)
                radial_scale = (1.0 + ci_cf) / (ci_as + 1e-6)
                aniso_sq = (rad_proj * radial_scale)**2 + trans_sq
                F_block[:, ki] = aniso_sq / (ci_ri**2)

                # Clip check uses ORIGINAL (unperturbed) coordinates
                d_orig = sl_orig - ci_c
                D_block[:, ki] = np.sqrt(np.einsum('mi,mi->m', d_orig, d_orig))

            best_ki = np.argmin(F_block, axis=1)
            best_ci = idxs[np.arange(M), best_ki]
            best_D  = D_block[np.arange(M), best_ki]

            winning_inside = cell_inside[best_ci]
            within_clip    = best_D <= r_clip[best_ci]
            # Dropped necrotic cells appear as background
            not_dropped    = np.array(
                [best_ci[i] not in self._necrotic_ids for i in range(M)])
            valid = winning_inside & within_clip & not_dropped

            labels = np.where(valid, best_ci+1, 0).astype(np.int32)

            sl_cell = np.zeros(ny*nx, dtype=np.int32)
            sl_cell[ext_idx] = labels

            cell_map[zi]      = sl_cell.reshape(ny, nx)
            organoid_mask[zi] = (sl_cell > 0).reshape(ny, nx)

        return cell_map, organoid_mask

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_dapi(self) -> np.ndarray:
        volume = np.zeros(self.shape, dtype=np.float32)
        for cell in tqdm(self.cells, desc="  Rendering DAPI nuclei",
                         unit="cell", ncols=72):
            if cell.cell_id in self._necrotic_ids:
                continue
            self._render_nucleus(volume, cell)

        # Apply staining diffusion map
        volume *= self._staining_map
        return volume

    def render_actin(self) -> np.ndarray:
        tp = self.p.texture
        print("  Computing intercellular actin network...", end=" ", flush=True)

        vm = self.cell_map
        cp = self.p.cells

        # Necrotic cell IDs (zero actin for these)
        necrotic_lut = np.zeros(len(self.cells)+1, dtype=bool)
        for cid in self._necrotic_ids:
            necrotic_lut[cid+1] = True

        # Cell-cell interfaces
        interface = np.zeros(self.shape, dtype=bool)
        for slc_a, slc_b in [
            ((slice(None,-1),slice(None),slice(None)),
             (slice(1,None), slice(None),slice(None))),
            ((slice(None),slice(None,-1),slice(None)),
             (slice(None),slice(1,None), slice(None))),
            ((slice(None),slice(None),slice(None,-1)),
             (slice(None),slice(None),slice(1,None))),
        ]:
            diff = (vm[slc_a] != vm[slc_b]) & \
                   (vm[slc_a] > 0) & (vm[slc_b] > 0) & \
                   ~necrotic_lut[vm[slc_a]] & ~necrotic_lut[vm[slc_b]]
            interface[slc_a] |= diff
            interface[slc_b] |= diff

        # Outer surface
        bg = ~self.organoid_mask
        outer_mem = np.zeros(self.shape, dtype=bool)
        for slc_a, slc_b in [
            ((slice(None,-1),slice(None),slice(None)),
             (slice(1,None), slice(None),slice(None))),
            ((slice(None),slice(None,-1),slice(None)),
             (slice(None),slice(1,None), slice(None))),
            ((slice(None),slice(None),slice(None,-1)),
             (slice(None),slice(None),slice(1,None))),
        ]:
            # Only non-necrotic cells show outer membrane
            outer_mem[slc_a] |= (vm[slc_a] > 0) & (vm[slc_b] == 0) \
                                 & ~necrotic_lut[vm[slc_a]]
            outer_mem[slc_b] |= (vm[slc_b] > 0) & (vm[slc_a] == 0) \
                                 & ~necrotic_lut[vm[slc_b]]

        membrane = interface | outer_mem
        print("done")

        # Per-cell brightness LUT
        n     = len(self.cells)
        b_lut = np.zeros(n+1, dtype=np.float32)
        for cell in self.cells:
            b_lut[cell.cell_id+1] = cell.actin_brightness
        b_map = b_lut[vm]

        # Cytoplasm noise
        cyto_noise = self._cytoplasm_noise()

        volume = np.zeros(self.shape, dtype=np.float32)
        in_cell = (vm > 0) & ~membrane & ~necrotic_lut[vm]
        volume[in_cell]   = (b_map[in_cell] * tp.actin_cytoplasm_frac *
                             (0.5 + 0.5*cyto_noise[in_cell]))
        volume[membrane]  = b_map[membrane]

        # Tricellular junction boost
        junctions = self._detect_junctions(vm, necrotic_lut)
        volume[junctions] = np.minimum(volume[junctions]*1.35, 1.0)

        # Apply staining diffusion map
        volume *= self._staining_map

        vmax = volume.max()
        if vmax > 0: volume /= vmax
        return volume

    def render_label_mask(self) -> np.ndarray:
        return self.cell_map.astype(np.uint16)

    def render_nucleus_label_mask(self) -> np.ndarray:
        mask = np.zeros(self.shape, dtype=np.uint16)
        for cell in tqdm(self.cells, desc="  Rendering nucleus labels",
                         unit="cell", ncols=72):
            if cell.cell_id in self._necrotic_ids:
                continue
            nuc_centre = self._nucleus_centres[cell.cell_id]
            bbox = self._nucleus_bbox(cell, nuc_centre, margin_um=0.5)
            if bbox is None: continue
            z0,z1,y0,y1,x0,x1 = bbox
            d = self._irregular_nucleus_distance(cell, nuc_centre,
                                                  z0,z1,y0,y1,x0,x1)
            cell_region = (self.cell_map[z0:z1,y0:y1,x0:x1] == cell.cell_id+1)
            interior    = (d <= 1.0) & cell_region
            region = mask[z0:z1,y0:y1,x0:x1]
            region[interior & (region == 0)] = cell.cell_id + 1
        return mask

    # ------------------------------------------------------------------
    # Nucleus rendering
    # ------------------------------------------------------------------

    def _render_nucleus(self, volume: np.ndarray, cell: Cell):
        cp  = self.p.cells
        tp  = self.p.texture
        nuc_centre = self._nucleus_centres[cell.cell_id]

        # Necrotic zone: condensed (smaller, brighter) nucleus
        is_necrotic_zone = (cp.necrotic_core and
                            cell.radial_pos < cp.necrotic_fraction and
                            cell.cell_id not in self._necrotic_ids)
        if is_necrotic_zone:
            # Bimodal necrotic population — three types weighted by probability:
            #   ~20% ghost cells  : nucleus largely dissolved, dim and barely shrunken
            #   ~65% pyknotic     : condensed + bright (classic necrosis)
            #   ~15% karyorrhectic: intermediate — shrunken, moderately bright
            rng_nc = np.random.default_rng(self.p.random_seed + cell.cell_id * 1337)
            roll = rng_nc.random()
            if roll < 0.20:
                # Ghost cell: membrane gone, nucleus almost full size but very dim
                scale  = float(rng_nc.uniform(0.88, 1.00))
                b_mult = float(rng_nc.uniform(0.15, 0.35))
            elif roll < 0.85:
                # Pyknotic: condensed (small) and bright
                scale  = float(rng_nc.uniform(0.50, 0.72))
                b_mult = float(rng_nc.uniform(0.85, 1.15)) * cp.necrotic_dapi_boost
            else:
                # Karyorrhectic: intermediate — partially fragmented
                scale  = float(rng_nc.uniform(0.60, 0.80))
                b_mult = float(rng_nc.uniform(0.50, 0.85)) * cp.necrotic_dapi_boost
            orig_axes   = cell.nucleus_axes_um.copy()
            cell.nucleus_axes_um = orig_axes * scale
            orig_bright = cell.dapi_brightness
            cell.dapi_brightness = min(orig_bright * b_mult, 1.5)

        bbox = self._nucleus_bbox(cell, nuc_centre)
        if bbox is None:
            if is_necrotic_zone:
                cell.nucleus_axes_um = orig_axes
                cell.dapi_brightness = orig_bright
            return
        z0,z1,y0,y1,x0,x1 = bbox

        d = self._irregular_nucleus_distance(cell, nuc_centre,
                                              z0,z1,y0,y1,x0,x1)
        cell_region = (self.cell_map[z0:z1,y0:y1,x0:x1] == cell.cell_id+1)
        interior    = (d <= 1.0) & cell_region
        if not interior.any():
            if is_necrotic_zone:
                cell.nucleus_axes_um = orig_axes
                cell.dapi_brightness = orig_bright
            return

        fill          = np.clip(1.0-d, 0.0, 1.0)**0.4
        boundary_fade = np.clip((1.0-d)/0.20, 0.0, 1.0)
        texture       = self._nucleus_texture(cell, d.shape)

        signal  = fill * (1.0 + tp.nucleus_texture_amplitude*texture)
        signal *= cell.dapi_brightness * boundary_fade
        signal[~interior] = 0.0

        np.add(volume[z0:z1,y0:y1,x0:x1], signal.astype(np.float32),
               out=volume[z0:z1,y0:y1,x0:x1])

        # Restore if modified
        if is_necrotic_zone:
            cell.nucleus_axes_um = orig_axes
            cell.dapi_brightness = orig_bright

    def _irregular_nucleus_distance(self, cell, nuc_centre,
                                    z0,z1,y0,y1,x0,x1):
        cp  = self.p.cells
        zz  = self.ZZ[z0:z1,y0:y1,x0:x1]
        yy  = self.YY[z0:z1,y0:y1,x0:x1]
        xx  = self.XX[z0:z1,y0:y1,x0:x1]
        dz  = zz - nuc_centre[0]
        dy  = yy - nuc_centre[1]
        dx  = xx - nuc_centre[2]

        o     = cell.orientation
        ref   = np.array([1.,0.,0.]) if abs(o[2])<0.9 else np.array([0.,1.,0.])
        perp1 = np.cross(o,ref); perp1 /= np.linalg.norm(perp1)
        perp2 = np.cross(o,perp1)

        disp = np.stack([dz,dy,dx], axis=-1)
        pl   = np.einsum('...i,i->...', disp, o)
        p1   = np.einsum('...i,i->...', disp, perp1)
        p2   = np.einsum('...i,i->...', disp, perp2)

        a,b,c  = cell.nucleus_axes_um
        d_base = np.sqrt((pl/a)**2 + (p1/b)**2 + (p2/c)**2)

        irr = cp.nucleus_irregularity
        if irr > 0.0:
            rng_n = np.random.default_rng(self.p.random_seed + cell.cell_id*3571)
            shape = d_base.shape
            deform = np.zeros(shape, dtype=np.float32)
            amp = 1.0
            for octave in range(3):
                gs = max(3, int(max(shape)*0.35*(1.5**octave)))
                cn = rng_n.standard_normal((gs,gs,gs)).astype(np.float32)
                up = zoom(cn,(shape[0]/gs,shape[1]/gs,shape[2]/gs),order=1)
                up = self._match_shape(up, shape)
                deform += amp*up; amp *= 0.5
            mx = np.abs(deform).max()
            if mx > 1e-8: deform /= mx
            sw = np.clip(d_base/1.1, 0, 1)**2
            d_base = d_base + irr*sw*deform
        return d_base

    def _nucleus_texture(self, cell: Cell, shape: tuple) -> np.ndarray:
        """
        Two-component chromatin texture model (v9).

        Component 1 -- euchromatin background:
            Low-frequency fractal noise field (same as previous single-field
            implementation). Covers the full nucleus volume.

        Component 2 -- heterochromatin domains:
            Sparse bright Gaussian blobs placed randomly inside the nucleus.
            Number of blobs scales with heterochromatin_fraction and nucleus
            volume. Each blob has sigma ~ nucleus_radius_vox / 4, placing it
            within the nucleus interior. Blobs are 2.5x brighter than background.

        Final texture:
            texture = (1 - hf) * base_field + hf * blob_field * BLOB_CONTRAST
            scaled by nucleus_texture_amplitude (as before).

        When heterochromatin_fraction < 0.01, falls back to pure smooth mode
        for backward compatibility with old presets that lack the parameter.
        """
        tp  = self.p.texture
        vp  = self.p.voxel
        hf  = getattr(tp, 'heterochromatin_fraction', 0.25)

        rng_tex = np.random.default_rng(self.p.random_seed + cell.cell_id * 7919)

        # ---- Component 1: smooth euchromatin background ----
        base = np.zeros(shape, dtype=np.float32)
        amp, f0 = 1.0, max(0.06, tp.nucleus_texture_scale)
        for octave in range(tp.nucleus_texture_octaves):
            gs = max(2, int(max(shape) * f0 * (2 ** octave)))
            c  = rng_tex.standard_normal((gs, gs, gs)).astype(np.float32)
            up = zoom(c, (shape[0]/gs, shape[1]/gs, shape[2]/gs), order=1)
            up = self._match_shape(up, shape)
            base += amp * up
            amp  *= 0.5
        mx = np.abs(base).max()
        if mx > 1e-8:
            base /= mx
        # Shift to [0, 1]
        base = (base - base.min()) / (base.max() - base.min() + 1e-9)

        if hf < 0.01:
            # Pure smooth mode -- backward compatible
            return tp.nucleus_texture_amplitude * base

        # ---- Component 2: heterochromatin blobs ----
        # Nucleus radius in voxels (use mean of xy axes / xy voxel size)
        nuc_r_vox = float(np.mean(cell.nucleus_axes_um[:2])) / vp.voxel_size_xy
        blob_sigma = max(1.0, nuc_r_vox / 4.0)

        # Number of blobs: scales with fraction and nucleus volume
        n_blobs = max(1, int(round(hf * 15)))

        # Build coordinate grid relative to bbox centre (voxel units)
        sz, sy, sx = shape
        gz = np.arange(sz, dtype=np.float32) - sz / 2.0
        gy = np.arange(sy, dtype=np.float32) - sy / 2.0
        gx = np.arange(sx, dtype=np.float32) - sx / 2.0
        GZ, GY, GX = np.meshgrid(gz, gy, gx, indexing='ij')

        blob_field = np.zeros(shape, dtype=np.float32)
        rng_blob   = np.random.default_rng(self.p.random_seed + cell.cell_id * 3137)
        inner_r    = 0.60 * nuc_r_vox   # keep blobs inside nucleus

        placed = 0
        attempts = 0
        while placed < n_blobs and attempts < n_blobs * 50:
            attempts += 1
            cz = rng_blob.uniform(-inner_r, inner_r)
            cy = rng_blob.uniform(-inner_r, inner_r)
            cx = rng_blob.uniform(-inner_r, inner_r)
            if cz**2 + cy**2 + cx**2 > inner_r**2:
                continue
            dists_sq = (GZ - cz)**2 + (GY - cy)**2 + (GX - cx)**2
            blob_field += np.exp(-dists_sq / (2.0 * blob_sigma**2))
            placed += 1

        bmax = blob_field.max()
        if bmax > 1e-8:
            blob_field /= bmax

        # ---- Combine ----
        BLOB_CONTRAST = 2.5
        texture = ((1.0 - hf) * base
                   + hf * blob_field * BLOB_CONTRAST)

        # Do NOT renormalise the combined field -- the variance difference
        # between high and low heterochromatin_fraction must be preserved.
        # Renormalising would map both to [0,1] and erase the CV_chromatin
        # difference between conditions. Clip to [0, 1] to prevent overflow.
        texture = np.clip(texture, 0.0, 1.0)

        return tp.nucleus_texture_amplitude * texture

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cytoplasm_noise(self) -> np.ndarray:
        rng = np.random.default_rng(self.p.random_seed+42)
        Z,Y,X = self.shape
        gs    = 24
        coarse = rng.uniform(0.3,1.0,(gs,gs,gs)).astype(np.float32)
        noise  = zoom(coarse,(Z/gs,Y/gs,X/gs),order=1)
        noise  = self._match_shape(noise, self.shape)
        noise  = gaussian_filter(noise, sigma=3.0)
        mx = noise.max()
        if mx > 1e-8: noise /= mx
        return noise

    def _detect_junctions(self, vm, necrotic_lut) -> np.ndarray:
        axes_iface = np.zeros((*self.shape, 3), dtype=bool)
        for k,(slc_a,slc_b) in enumerate([
            ((slice(None,-1),slice(None),slice(None)),
             (slice(1,None), slice(None),slice(None))),
            ((slice(None),slice(None,-1),slice(None)),
             (slice(None),slice(1,None), slice(None))),
            ((slice(None),slice(None),slice(None,-1)),
             (slice(None),slice(None),slice(1,None))),
        ]):
            diff = (vm[slc_a]!=vm[slc_b]) & (vm[slc_a]>0) & (vm[slc_b]>0) \
                   & ~necrotic_lut[vm[slc_a]] & ~necrotic_lut[vm[slc_b]]
            axes_iface[slc_a+(k,)] |= diff
            axes_iface[slc_b+(k,)] |= diff
        return (axes_iface.sum(axis=-1) >= 2) & (vm > 0)

    def _nucleus_bbox(self, cell, nuc_centre, margin_um=1.5):
        vp  = self.p.voxel; out = self.p.output
        r   = float(np.max(cell.nucleus_axes_um))*1.3 + margin_um
        cz,cy,cx = nuc_centre
        z0 = max(0,int((cz-r)/vp.voxel_size_z))
        z1 = min(out.vol_z,int((cz+r)/vp.voxel_size_z)+2)
        y0 = max(0,int((cy-r)/vp.voxel_size_xy))
        y1 = min(out.vol_y,int((cy+r)/vp.voxel_size_xy)+2)
        x0 = max(0,int((cx-r)/vp.voxel_size_xy))
        x1 = min(out.vol_x,int((cx+r)/vp.voxel_size_xy)+2)
        if z1<=z0 or y1<=y0 or x1<=x0: return None
        return z0,z1,y0,y1,x0,x1

    @staticmethod
    def _match_shape(arr, target):
        result = np.zeros(target, dtype=arr.dtype)
        s = tuple(slice(0,min(a,b)) for a,b in zip(arr.shape, target))
        result[s] = arr[s]
        return result
