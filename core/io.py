"""
io.py
-----
Writes synthetic organoid data as OME-TIFF.

Dimension order: TCZYX  (arivis Pro standard)
Saves:
  - <name>.ome.tif       : multichannel fluorescence image (uint16)
  - <name>_labels.ome.tif: integer label mask (uint16, optional)

Physical pixel sizes are embedded in OME-XML so arivis/FIJI/napari
correctly interpret voxel dimensions without manual setup.
"""

import numpy as np
import tifffile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional
from .parameters import OrganoidParams


def _build_ome_xml(
    shape_tczyx: tuple,
    params: OrganoidParams,
    channel_names: List[str],
    channel_colors: List[str],
    image_name: str = "SyntheticOrganoid",
) -> str:
    """
    Build a minimal but complete OME-XML metadata block.
    arivis Pro reads PhysicalSize* fields to set the scale automatically.
    """
    vp = params.voxel
    T, C, Z, Y, X = shape_tczyx

    ome = ET.Element("OME", {
        "xmlns":              "http://www.openmicroscopy.org/Schemas/OME/2016-06",
        "xmlns:xsi":          "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": (
            "http://www.openmicroscopy.org/Schemas/OME/2016-06 "
            "http://www.openmicroscopy.org/Schemas/OME/2016-06/ome.xsd"
        ),
        "Creator": "SyntheticOrganoidGenerator",
    })

    image_el = ET.SubElement(ome, "Image", {"ID": "Image:0", "Name": image_name})

    pixels = ET.SubElement(image_el, "Pixels", {
        "ID":                "Pixels:0",
        "DimensionOrder":    "XYZCT",
        "Type":              "uint16",
        "SizeX":             str(X),
        "SizeY":             str(Y),
        "SizeZ":             str(Z),
        "SizeC":             str(C),
        "SizeT":             str(T),
        "PhysicalSizeX":     f"{vp.voxel_size_xy:.6f}",
        "PhysicalSizeXUnit": "um",
        "PhysicalSizeY":     f"{vp.voxel_size_xy:.6f}",
        "PhysicalSizeYUnit": "um",
        "PhysicalSizeZ":     f"{vp.voxel_size_z:.6f}",
        "PhysicalSizeZUnit": "um",
    })

    # Color hex string → int (OME stores as signed 32-bit)
    def hex_to_int(h: str) -> int:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return (r << 16) | (g << 8) | b

    for c_idx, (name, color) in enumerate(zip(channel_names, channel_colors)):
        ch = ET.SubElement(pixels, "Channel", {
            "ID":              f"Channel:0:{c_idx}",
            "Name":            name,
            "SamplesPerPixel": "1",
            "Color":           str(hex_to_int(color)),
        })

    # TiffData entries
    ifd = 0
    for t in range(T):
        for c in range(C):
            for z in range(Z):
                ET.SubElement(pixels, "TiffData", {
                    "FirstT":   str(t),
                    "FirstC":   str(c),
                    "FirstZ":   str(z),
                    "IFD":      str(ifd),
                    "PlaneCount": "1",
                })
                ifd += 1

    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(ome, encoding="unicode")


def save_ome_tiff(
    channels: List[np.ndarray],
    params: OrganoidParams,
    output_path: str | Path,
    label_mask: Optional[np.ndarray] = None,
    nucleus_label_mask: Optional[np.ndarray] = None,
    image_name: str = "SyntheticOrganoid",
) -> Path:
    """
    Save multichannel 3D volume as OME-TIFF.

    Parameters
    ----------
    channels            : list of float32 arrays shape (Z, Y, X), one per channel
    params              : OrganoidParams (for voxel sizes, channel names/colors)
    output_path         : file path, should end in .ome.tif
    label_mask          : optional uint16 cell body labels — *_labels.ome.tif
    nucleus_label_mask  : optional uint16 nucleus labels — *_nucleus_labels.ome.tif
    image_name          : name embedded in OME-XML

    Returns
    -------
    Path to saved file.
    """
    out    = params.output
    path   = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    C = len(channels)
    Z, Y, X = channels[0].shape

    # Stack into TCZYX and convert to uint16
    max_val = float(2**out.bit_depth - 1)
    stack = np.zeros((1, C, Z, Y, X), dtype=np.uint16)
    for c_idx, ch in enumerate(channels):
        arr = np.clip(ch, 0.0, 1.0)
        stack[0, c_idx] = (arr * max_val).astype(np.uint16)

    ome_xml = _build_ome_xml(
        shape_tczyx=(1, C, Z, Y, X),
        params=params,
        channel_names=out.channel_names[:C],
        channel_colors=out.channel_colors[:C],
        image_name=image_name,
    )

    # Encode OME-XML as bytes (UTF-8) to avoid ASCII restriction
    ome_xml_bytes = ome_xml.encode("utf-8")

    tifffile.imwrite(
        str(path),
        stack,
        photometric="minisblack",
        metadata=None,
        description=ome_xml_bytes,
        imagej=False,
        compression="zlib",
    )

    # Save channel name/color originals for restoration
    lp_tmp = params.output.channel_names[:]
    lc_tmp = params.output.channel_colors[:]

    # Save label mask as a separate OME-TIFF
    if label_mask is not None:
        label_path = path.parent / (path.stem.replace(".ome", "") + "_labels.ome.tif")
        label_stack = label_mask.astype(np.uint16)[np.newaxis, np.newaxis, ...]
        params.output.channel_names  = ["Labels"]
        params.output.channel_colors = ["FFFFFF"]
        label_xml = _build_ome_xml(
            shape_tczyx=(1, 1, Z, Y, X),
            params=params,
            channel_names=["Labels"],
            channel_colors=["FFFFFF"],
            image_name=image_name + "_labels",
        )
        params.output.channel_names  = lp_tmp
        params.output.channel_colors = lc_tmp

        label_xml_bytes = label_xml.encode("utf-8")
        tifffile.imwrite(
            str(label_path),
            label_stack,
            photometric="minisblack",
            metadata=None,
            description=label_xml_bytes,
            imagej=False,
            compression="zlib",
        )
        print(f"  Label mask saved → {label_path}")

    print(f"  OME-TIFF saved  → {path}")
    print(f"  Volume shape    : Z={Z}, Y={Y}, X={X}, C={C}")
    print(f"  Voxel size      : {params.voxel.voxel_size_xy:.3f} x "
          f"{params.voxel.voxel_size_xy:.3f} x "
          f"{params.voxel.voxel_size_z:.3f} µm")
    print(f"  File size       : {path.stat().st_size / 1e6:.1f} MB")

    # Save nucleus label mask
    if nucleus_label_mask is not None:
        nuc_path = path.parent / (path.stem.replace(".ome","") + "_nucleus_labels.ome.tif")
        nuc_stack = nucleus_label_mask.astype(np.uint16)[np.newaxis, np.newaxis, ...]
        params.output.channel_names  = ["Nucleus_Labels"]
        params.output.channel_colors = ["FF0000"]
        nuc_xml = _build_ome_xml(
            shape_tczyx=(1, 1, Z, Y, X),
            params=params,
            channel_names=["Nucleus_Labels"],
            channel_colors=["FF0000"],
            image_name=image_name + "_nucleus_labels",
        )
        params.output.channel_names  = lp_tmp
        params.output.channel_colors = lc_tmp
        tifffile.imwrite(
            str(nuc_path),
            nuc_stack,
            photometric="minisblack",
            metadata=None,
            description=nuc_xml.encode("utf-8"),
            imagej=False,
            compression="zlib",
        )
        print(f"  Nucleus labels  → {nuc_path}")

    return path
