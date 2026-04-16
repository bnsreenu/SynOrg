# SynOrg — Synthetic Organoid Generator

Parametric physics-based generator of realistic 3D fluorescence organoid images with exact ground-truth label masks. Output is OME-TIFF compatible with arivis Pro, FIJI, napari, and any OME-aware viewer.

Companion to the manuscript:

> Bhattiprolu S. (2025). *Parametric Physics-Based Synthesis of 3D Fluorescence Organoid Images with Exact Ground Truth for Deep Learning Pipeline Development.* bioRxiv. [DOI placeholder]

---

## What it does

- Generates two-channel (DAPI + Actin/phalloidin) volumetric fluorescence images of synthetic organoids
- Produces exact ground-truth cell body and nucleus integer label masks by construction — no manual annotation required
- Models cell placement via force-directed sphere packing, cell morphology via Laguerre power-diagram tessellation, and optical effects via a physically motivated optics pipeline
- Supports hollow lumen (cyst) architectures, necrotic cores with three-phenotype nuclear populations, apical-basal epithelial polarity, and depth-dependent PSF broadening
- Includes a PyQt5 graphical interface with live preview and a slice-by-slice OME-TIFF viewer
- Five condition-specific presets calibrated to published biological measurements (Ong et al., Nature Methods 2025)

---

## Quick start

```bash
pip install -r requirements.txt

# Default organoid (150 µm, 2-channel DAPI + Actin)
python generate_organoid.py

# Named preset
python generate_organoid.py --preset pdac_isotonic --seed 42

# Override diameter
python generate_organoid.py --preset hmecyst_cyst --diameter 190

# Batch of 10 organoids with sequential seeds
python generate_organoid.py --preset pdac_isotonic --batch 10 --output-dir output/batch/

# Launch the graphical interface
python generate_gui.py
```

---

## Output files

Each run produces three OME-TIFF files:

| File | Contents |
|---|---|
| `<preset>_seed<N>_<timestamp>.ome.tif` | 2-channel uint16 fluorescence image (DAPI + Actin) |
| `<preset>_seed<N>_<timestamp>_labels.ome.tif` | Cell body integer label mask (one unique integer per cell) |
| `<preset>_seed<N>_<timestamp>_nucleus_labels.ome.tif` | Nucleus integer label mask (same cell IDs as above) |

Cell and nucleus label IDs are identical, allowing direct linkage without a lookup table.

---

## Available presets

### General-purpose

| Preset | Diameter | ~Cells | Character |
|---|---|---|---|
| `tiny_test` | 55 µm | ~23 | Fast testing only (~5 s) |
| `tumor_spheroid` | 120 µm | ~200 | Dense HCT116/MCF7-like spheroid |
| `pdac_organoid` | 160 µm | ~350 | Pancreatic ductal adenocarcinoma |
| `intestinal_crypt` | 130 µm | ~280 | Columnar epithelium, elongated nuclei |
| `breast_cancer` | 140 µm | ~300 | Pleomorphic, high NC ratio |
| `brain_organoid` | 180 µm | ~250 | Large loose cells, low pressure |
| `prostate_cancer` | 120 µm | ~220 | Glandular, moderate pleomorphism |
| `hepatic_organoid` | 160 µm | ~220 | Large hepatocyte-like cells |
| `kidney_organoid` | 150 µm | ~290 | Tubular epithelium |

### Calibrated (Ong et al. 2025)

| Preset | Diameter | ~Cells | Character |
|---|---|---|---|
| `pdac_isotonic` | 170 µm | ~640 | PDAC spheroid, isotonic control |
| `pdac_hypertonic` | 165 µm | ~610 | PDAC spheroid, osmotic stress |
| `hmecyst_control` | 195 µm | ~260 | HMECyst normal epithelial, solid |
| `hmecyst_cyst` | 190 µm | ~40–60 | HMECyst cyst-forming, lumen_fraction = 0.78 |
| `pdac_large_clustering` | 200 µm | ~1000 | Large primary PDAC with necrotic core |

---

## Project structure

```
SynOrg/
├── generate_organoid.py          # CLI entry point
├── generate_gui.py               # PyQt5 graphical interface
├── requirements.txt
├── README.md
├── command_line_to_generate_multiple_organoids.txt
├── Synthetic_Organoid_Parameter_Guide_v2.pdf
├── core/
│   ├── parameters.py             # All tunable parameters (dataclasses)
│   ├── organoid_scaffold.py      # Force-directed sphere packing
│   ├── signal_generator.py       # Fluorescence rendering + tessellation
│   ├── optics.py                 # PSF, noise, staining gradient, attenuation
│   ├── generator.py              # Pipeline orchestrator
│   └── io.py                     # OME-TIFF writer
├── gui/
│   └── ...                       # PyQt5 GUI components
└── presets/
    └── *.json                    # One JSON file per preset
```

---

## Creating a custom preset

Create a JSON file in `presets/` specifying only the parameters that differ from defaults. Everything else is inherited from `parameters.py`. Then add the preset name to `AVAILABLE_PRESETS` in `generate_organoid.py`.

```json
{
  "_description": "Lung adenocarcinoma organoid",
  "shape": { "diameter_um": 130.0, "sphericity": 0.91 },
  "cells": {
    "cell_radius_core": 6.0,
    "cell_radius_periph": 9.0,
    "nc_ratio_core": 0.74,
    "nc_ratio_periph": 0.71,
    "pressure_core": 0.20,
    "pressure_periph": 0.07,
    "nucleus_irregularity": 0.28,
    "apical_elongation": 0.20,
    "surface_flattening": 0.25
  }
}
```

See `Synthetic_Organoid_Parameter_Guide_v2.pdf` for a complete description of all parameters, their biological meaning, and recommended values by organoid type.

---

## Command-line reference

| Flag | Default | Description |
|---|---|---|
| `--preset` | — | Named preset to load |
| `--seed` | 42 | Random seed for reproducibility |
| `--diameter` | from preset | Override organoid diameter in µm |
| `--ncells` | — | Set diameter from target cell count |
| `--voxel-xy` | 0.414 | XY pixel size in µm |
| `--voxel-z` | 1.0 | Z step size in µm |
| `--output-dir` | `output/` | Directory for output files |
| `--batch` | 1 | Generate N organoids with sequential seeds |
| `--no-labels` | off | Skip label mask export |
| `--gpu` | off | GPU acceleration via CuPy (requires NVIDIA GPU) |

---

## Requirements

```
numpy>=1.24
scipy>=1.10
tifffile>=2023.1
tqdm>=4.65
PyQt5>=5.15
matplotlib>=3.7
```

CuPy is optional for GPU acceleration of the optics stage.

---

## License

This software is licensed under the GNU General Public License v3.0 (GPLv3). Academic and research use is freely permitted. Commercial use is subject to the terms of GPLv3, which requires that any derivative work also be released under GPLv3. Organizations seeking to use this software in proprietary or commercial products should contact digitalsreeni@gmail.com to discuss alternative licensing arrangements.

---

## Citation

If you use SynOrg in your research, please cite:

```
Bhattiprolu S. (2025). Parametric Physics-Based Synthesis of 3D Fluorescence
Organoid Images with Exact Ground Truth for Deep Learning Pipeline Development.
bioRxiv. DOI: [placeholder]
```

---

## Author

Sreenivas Bhattiprolu — DigitalSreeni LLC, California, USA  
digitalsreeni@gmail.com  
[YouTube: DigitalSreeni](https://www.youtube.com/@DigitalSreeni)
