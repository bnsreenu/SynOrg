"""
generate_organoid.py
--------------------
Command-line entry point for synthetic organoid generation.

Output naming (when --output is not specified):
  output/<preset>_seed<seed>_<timestamp>.ome.tif

Examples
--------
  python generate_organoid.py
      → output/default_seed42_20240402_143012.ome.tif

  python generate_organoid.py --preset tumor_spheroid
      → output/tumor_spheroid_seed42_20240402_143012.ome.tif

  python generate_organoid.py --preset pdac_organoid --seed 7
      → output/pdac_organoid_seed7_20240402_143012.ome.tif

  python generate_organoid.py --preset tumor_spheroid --batch 5
      → output/tumor_spheroid_seed42_<ts>_001.ome.tif
         output/tumor_spheroid_seed43_<ts>_002.ome.tif
         ...

  python generate_organoid.py --output my_folder/my_name.ome.tif
      → my_folder/my_name.ome.tif  (explicit path, no auto-naming)
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from core.parameters import (
    OrganoidParams, VoxelParams, OrganoidShapeParams,
    CellParams, PackingParams, TextureParams, OpticsParams, OutputParams
)
from core.generator import SyntheticOrganoidGenerator


# ── Preset helpers ──────────────────────────────────────────────────

AVAILABLE_PRESETS = [
    "tiny_test",
    "tumor_spheroid",
    "pdac_organoid",
    "intestinal_crypt",
    "breast_cancer",
    "brain_organoid",
    "prostate_cancer",
    "hepatic_organoid",
    "kidney_organoid",
    "pdac_isotonic",
    "pdac_hypertonic",
    "hmecyst_control",
    "hmecyst_cyst",
    "pdac_large_clustering",
]


def load_preset(name: str) -> dict:
    p = Path(__file__).parent / "presets" / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Preset '{name}' not found.\n"
            f"Expected: {p}\n"
            f"Available: {', '.join(AVAILABLE_PRESETS)}"
        )
    with open(p) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def apply_preset(params: OrganoidParams, preset: dict):
    for section, values in preset.items():
        obj = getattr(params, section, None)
        if obj is None:
            continue
        for key, val in values.items():
            if hasattr(obj, key):
                setattr(obj, key, val)


def build_params(args) -> OrganoidParams:
    params = OrganoidParams()
    if args.preset:
        apply_preset(params, load_preset(args.preset))
        print(f"  Loaded preset   : {args.preset}")
    if args.seed     is not None: params.random_seed         = args.seed
    if args.voxel_xy is not None: params.voxel.voxel_size_xy = args.voxel_xy
    if args.voxel_z  is not None: params.voxel.voxel_size_z  = args.voxel_z
    # ncells sets diameter unless --diameter explicitly overrides
    if args.ncells   is not None: params.auto_diameter_from_ncells(args.ncells)
    if args.diameter is not None: params.shape.diameter_um   = args.diameter
    params.auto_size_volume()
    return params


# ── Auto output path ────────────────────────────────────────────────

def auto_output_path(preset_name: str, seed: int,
                     output_dir: str = "output") -> Path:
    """
    Build an auto output path that includes preset name + seed + timestamp.
    Never overwrites a previous run.
    """
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = preset_name if preset_name else "default"
    stem = f"{name}_seed{seed}_{ts}"
    path = Path(output_dir) / f"{stem}.ome.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def auto_batch_path(preset_name: str, seed: int, index: int,
                    total: int, ts: str,
                    output_dir: str = "output") -> Path:
    """
    Build a batch output path:
      <preset>_seed<seed>_<timestamp>_<NNN_of_TTT>.ome.tif
    """
    name  = preset_name if preset_name else "default"
    stem  = f"{name}_seed{seed}_{ts}_{index:03d}of{total:03d}"
    path  = Path(output_dir) / f"{stem}.ome.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Synthetic 3D Organoid Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--preset", type=str, default=None,
        choices=AVAILABLE_PRESETS,
        help="Parameter preset to load (default: built-in defaults)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--diameter", type=float, default=None,
        help="Override organoid diameter in µm"
    )
    parser.add_argument(
        "--ncells", type=int, default=None,
        help="Target approximate cell count (sets diameter automatically). "
             "Overridden by --diameter if both given."
    )
    parser.add_argument(
        "--voxel-xy", type=float, default=None,
        help="Override XY pixel size in µm"
    )
    parser.add_argument(
        "--voxel-z", type=float, default=None,
        help="Override Z step size in µm"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help=(
            "Explicit output path (e.g. results/my_organoid.ome.tif). "
            "If omitted, auto-named as: output/<preset>_seed<N>_<timestamp>.ome.tif"
        )
    )
    parser.add_argument(
        "--output-dir", type=str, default="output",
        help="Output directory for auto-named files (default: output/)"
    )
    parser.add_argument(
        "--no-labels", action="store_true",
        help="Skip saving label masks"
    )
    parser.add_argument(
        "--gpu", action="store_true",
        help="GPU acceleration via CuPy (optics step)"
    )
    parser.add_argument(
        "--batch", type=int, default=1,
        help="Generate N organoids with sequential seeds (42, 43, ...)"
    )
    args = parser.parse_args()

    print("\n" + "="*58)
    print("  Synthetic Organoid Generator")
    print("="*58)

    save_labels = not args.no_labels

    if args.batch > 1:
        # ── Batch mode ──────────────────────────────────────────────
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"  Batch mode      : {args.batch} organoids")
        print(f"  Seeds           : {args.seed} → {args.seed + args.batch - 1}")
        print(f"  Timestamp       : {ts}\n")

        for i in range(args.batch):
            seed = args.seed + i
            args_copy = argparse.Namespace(**vars(args))
            args_copy.seed = seed

            if args.output:
                # User gave explicit path → insert batch index before extension
                p = Path(args.output)
                out = p.parent / f"{p.stem}_{i+1:03d}of{args.batch:03d}.ome.tif"
            else:
                out = auto_batch_path(
                    args.preset, seed, i+1, args.batch, ts, args.output_dir)

            print(f"\n── [{i+1}/{args.batch}]  seed={seed}  →  {out.name} ──")
            params = build_params(args_copy)
            SyntheticOrganoidGenerator(params, use_gpu=args.gpu)\
                .generate(out, save_labels=save_labels)

    else:
        # ── Single mode ─────────────────────────────────────────────
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            out = auto_output_path(args.preset, args.seed, args.output_dir)
            print(f"  Auto output     : {out}")

        params = build_params(args)
        SyntheticOrganoidGenerator(params, use_gpu=args.gpu)\
            .generate(out, save_labels=save_labels)

    print("\n" + "="*58)
    print("  Generation complete.")
    print("="*58 + "\n")


if __name__ == "__main__":
    main()
