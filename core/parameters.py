"""
parameters.py  v6
-----------------
Central configuration for synthetic organoid generation.
All physical units in micrometers unless noted.

New in v6:
  CellParams:   necrotic_core, necrotic_fraction, necrotic_dapi_boost
  OpticsParams: staining_depth_um, scatter_increase_rate, cleared
  TextureParams: membrane_bend_amplitude
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class VoxelParams:
    voxel_size_xy: float = 0.414
    voxel_size_z:  float = 1.0

    @property
    def anisotropy(self) -> float:
        return self.voxel_size_z / self.voxel_size_xy


@dataclass
class OrganoidShapeParams:
    diameter_um:     float = 150.0
    diameter_std_um: float = 10.0
    sphericity:      float = 0.92


@dataclass
class CellParams:
    """
    Cell and nucleus parameters.

    Necrotic core
    -------------
    Large organoids (>150µm) develop a hypoxic/necrotic core where inner
    cells lose membrane integrity, nuclei condense (pyknosis), and actin
    signal collapses. Controlled by:
      necrotic_core     : enable the necrotic zone
      necrotic_fraction : inner fraction of organoid radius affected (0–0.4)
      necrotic_dapi_boost: how much brighter/condensed the pyknotic nuclei are
    """
    cell_radius_core:   float = 6.5
    cell_radius_periph: float = 10.0
    cell_radius_std:    float = 0.6
    nc_ratio_core:      float = 0.72
    nc_ratio_periph:    float = 0.70
    elongation_core:    float = 0.88
    elongation_periph:  float = 0.78
    core_fraction:      float = 0.55
    pressure_core:      float = 0.18
    pressure_periph:    float = 0.06
    radial_compression: float = 0.15
    nucleus_ecc_core:   float = 0.08
    nucleus_ecc_periph: float = 0.22
    nucleus_irregularity: float = 0.25

    # Necrotic core
    necrotic_core:      bool  = False
    necrotic_fraction:  float = 0.25   # inner 25% of radius → necrotic zone
    necrotic_dapi_boost: float = 1.6   # pyknotic nuclei are this much brighter

    # Hollow lumen (cyst mode)
    # When > 0, no cells are placed inside this fractional radius.
    # Use for cyst-forming organoids (e.g. HMECyst A07).
    # 0.0 = solid spheroid (default)
    # 0.5 = cells occupy outer 50% of radius only (thin shell)
    # 0.7 = very thin shell, ~1-2 cell layers
    lumen_fraction:     float = 0.0

    # Apical-basal cell elongation (peripheral cells)
    # Real epithelial cells are taller radially than tangentially — they are
    # columnar, not spherical. This stretches the power-diagram territory of
    # peripheral cells along the radial (outward) axis, making each cell claim
    # more space radially and less tangentially. Ramps from 0 at core_fraction
    # to full value at the organoid surface.
    # 0.0  = isotropic (sphere-like, default — existing behaviour)
    # 0.25 = mild columnar character (typical normal epithelium)
    # 0.50 = clearly columnar (intestinal crypt, polarised monolayer)
    apical_elongation:  float = 0.0

    # Surface flattening (outermost cell layer)
    # The outermost shell of cells in real organoids flattens against the
    # ECM/air interface — they become squamous-like: wide tangentially, thin
    # radially. Applied only in the outermost 15% of organoid radius, ramping
    # from 0 to full value at the surface. Compresses territory radially.
    # 0.0  = no flattening (default)
    # 0.30 = visible squamous outer layer
    # 0.55 = strongly flattened outer cells
    surface_flattening: float = 0.0


@dataclass
class PackingParams:
    n_iterations:       int   = 120
    repulsion_strength: float = 0.45
    damping:            float = 0.55
    target_overlap:     float = 0.02
    boundary_strength:  float = 1.2


@dataclass
class TextureParams:
    nucleus_texture_scale:     float = 0.20
    nucleus_texture_amplitude: float = 0.35
    nucleus_texture_octaves:   int   = 3

    # Membrane
    membrane_thickness_vox:  float = 2.0
    actin_cytoplasm_frac:    float = 0.08

    # Membrane bend: low-freq shape perturbation applied to each cell's
    # power-diagram region before boundary detection.
    # 0.0 = perfectly geometric boundaries
    # 0.15 = gently curved, biological-looking
    # 0.30 = strongly irregular (aggressive tumour morphology)
    membrane_bend_amplitude: float = 0.20   # increased: 3x multiplied in signal_gen

    # Per-cell brightness variation
    dapi_intensity_sigma:    float = 0.18
    actin_intensity_sigma:   float = 0.28
    
    # Heterochromatin blob fraction (two-component chromatin texture model)
    # 0.0 = pure smooth euchromatin background
    # 0.25 = default mixed texture (realistic organoid)
    # 1.0 = maximum heterochromatin blob density (highly granular)
    # Used in signal_generator.py _nucleus_texture_field()
    heterochromatin_fraction: float = 0.25   # range 0.0-1.0
    
    dapi_brightness_core:    float = 0.70
    dapi_brightness_periph:  float = 1.00
    actin_brightness_core:   float = 0.55
    actin_brightness_periph: float = 1.00


@dataclass
class OpticsParams:
    """
    Microscope optics — v6 adds:

    Staining diffusion (radial from organoid surface)
    -------------------------------------------------
    staining_depth_um : half-penetration depth of the stain/antibody.
        At this depth below the organoid surface, brightness drops to 50%.
        Typical values:
          20–35 µm : tight spheroid, poor antibody penetration
          60–100 µm: loosely packed, cleared sample
          9999     : uniform staining (no gradient)

    Depth-dependent scattering (z-axis)
    ------------------------------------
    scatter_increase_rate : fractional increase in PSF sigma per µm depth.
        effective_sigma_xy(z) = psf_sigma_xy * (1 + scatter_increase_rate * z_um)
        Typical values:
          0.0  : no depth broadening (cleared sample / lightsheet)
          0.003: moderate (confocal, 100µm organoid)
          0.008: strong (widefield, uncleared, thick sample)

    cleared : convenience flag — sets both staining and scatter to
              near-zero, simulating a tissue-cleared sample.
    """
    psf_sigma_xy_um:      float = 0.25
    psf_sigma_z_um:       float = 1.20
    z_attenuation_coeff:  float = 0.005
    haze_sigma_um:        float = 10.0
    haze_amplitude:       float = 0.10
    shot_noise_scale:     float = 0.05
    read_noise_std:       float = 0.012
    background_level:     float = 0.04
    crosstalk_fraction:   float = 0.04

    # New v6
    staining_depth_um:       float = 35.0    # half-penetration depth (visible gradient)
    scatter_increase_rate:   float = 0.005   # PSF broadening per µm depth (visible)
    cleared:                 bool  = False   # tissue clearing flag


@dataclass
class OutputParams:
    vol_z: int = 80
    vol_y: int = 256
    vol_x: int = 256
    bit_depth: int = 16
    channel_names:  List[str] = field(default_factory=lambda: ["DAPI","Actin"])
    channel_colors: List[str] = field(default_factory=lambda: ["0000FF","00FF00"])


@dataclass
class OrganoidParams:
    voxel:   VoxelParams         = field(default_factory=VoxelParams)
    shape:   OrganoidShapeParams = field(default_factory=OrganoidShapeParams)
    cells:   CellParams          = field(default_factory=CellParams)
    packing: PackingParams       = field(default_factory=PackingParams)
    texture: TextureParams       = field(default_factory=TextureParams)
    optics:  OpticsParams        = field(default_factory=OpticsParams)
    output:  OutputParams        = field(default_factory=OutputParams)
    random_seed: int = 42

    def auto_diameter_from_ncells(self, n_cells: int):
        """
        Set diameter_um so the organoid contains approximately n_cells.
        Works by inverting the packing geometry: given mean cell volume
        and a random-close-packing fraction of 0.64, solve for organoid radius.

        Call this BEFORE auto_size_volume().

        Example:
            p = OrganoidParams()
            p.auto_diameter_from_ncells(200)
            p.auto_size_volume()
        """
        import math
        r_mean   = (self.cells.cell_radius_core + self.cells.cell_radius_periph) / 2.0
        vol_cell = (4/3) * math.pi * r_mean**3
        vol_org  = n_cells * vol_cell / 0.64        # packing fraction ~0.64
        sp       = self.shape.sphericity
        r_org    = (vol_org / ((4/3) * math.pi * sp)) ** (1/3)
        self.shape.diameter_um = r_org * 2.0
        # Warn if effective cell radius will be below practical minimum
        r_mean = (self.cells.cell_radius_core + self.cells.cell_radius_periph) / 2.0
        if r_mean < 4.0:
            import warnings
            warnings.warn(
                f"Mean cell radius {r_mean:.1f} µm is below 4 µm minimum. "
                f"Nuclei will be unresolvable at typical voxel sizes. "
                f"Increase cell_radius_core / cell_radius_periph.",
                UserWarning, stacklevel=2)
        return self

    def auto_size_volume(self):
        margin = 1.25
        d_xy = int((self.shape.diameter_um * margin) / self.voxel.voxel_size_xy)
        d_z  = int((self.shape.diameter_um * margin) / self.voxel.voxel_size_z)
        self.output.vol_x = ((d_xy + 15) // 16) * 16
        self.output.vol_y = self.output.vol_x
        self.output.vol_z = ((d_z  + 15) // 16) * 16
        return self

    def apply_clearing(self):
        """Convenience: simulate tissue-cleared sample."""
        self.optics.cleared              = True
        self.optics.staining_depth_um    = 9999.0
        self.optics.scatter_increase_rate = 0.0
        self.optics.z_attenuation_coeff  = 0.001
        self.optics.haze_amplitude       = 0.02
        return self
