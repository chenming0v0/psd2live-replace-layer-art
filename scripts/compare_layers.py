"""Render old/new/difference panels and pixel counts for PSD2Live layers."""

import argparse
import json

from psd_tools import PSDImage

from layer_archive import comparison_image, difference, load_project, raster_pair, select_layers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Saved .psd2live baseline")
    parser.add_argument("--psd", required=True, help="Revised source PSD")
    parser.add_argument("--layer", action="append", required=True,
                        help="Project layer ID/name, or PROJECT=PSD layer name/path; repeatable")
    parser.add_argument("--output", required=True, help="New comparison PNG path")
    args = parser.parse_args()
    entries, _, prefix, _, snapshot = load_project(args.project)
    psd = PSDImage.open(args.psd)
    panels, results = [], []
    for layer, source in select_layers(snapshot, psd, args.layer):
        old, new = raster_pair(entries, prefix, snapshot, psd, layer, source)
        panels.append((layer["name"], old, new))
        results.append({"id": layer["id"], "name": layer["name"],
                        **difference(old, new, (layer["left"], layer["top"]))})
    comparison_image(panels, args.output)
    print(json.dumps({"comparison": args.output, "layers": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
