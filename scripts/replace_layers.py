"""Replace selected PSD2Live layer rasters in a new archive copy."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import uuid
import zipfile

from psd_tools import PSDImage

from layer_archive import (
    digest, encode, load_project, mesh_delta_targets, plan_obsolete_mesh_removal, raster_pair, select_layers,
)


def snapshot_changes(before, after):
    layer_changes = []
    for old, new in zip(before["layers"], after["layers"]):
        fields = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
        if fields:
            layer_changes.append({"id": old["id"], "fields": fields})
    rig_before = before.get("rigEdits") or {}
    rig_after = after.get("rigEdits") or {}
    changed_rig = sorted(key for key in set(rig_before) | set(rig_after)
                         if rig_before.get(key) != rig_after.get(key))
    changed_top = sorted(key for key in set(before) | set(after)
                         if key not in {"layers", "rigEdits"} and before.get(key) != after.get(key))
    return layer_changes, changed_rig, changed_top


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Saved .psd2live baseline")
    parser.add_argument("--psd", required=True, help="Revised source PSD")
    parser.add_argument("--output", required=True, help="New .psd2live path; must not exist")
    parser.add_argument("--layer", action="append", required=True,
                        help="Project layer ID/name, or PROJECT=PSD layer name/path; repeatable")
    parser.add_argument("--clean-obsolete-mesh",
                        help="Remove one journal-proven obsolete mesh sequence, MESH_ID:PARAMETER")
    parser.add_argument("--summary", default="Replace selected layer artwork; preserve rig",
                        help="History node summary")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    entries, manifest, prefix, head, snapshot = load_project(args.project)
    updated = deepcopy(snapshot)
    psd = PSDImage.open(args.psd)
    targets = select_layers(snapshot, psd, args.layer)
    changed = []
    for layer, source in targets:
        old, new = raster_pair(entries, prefix, snapshot, psd, layer, source)
        new_bytes = new.tobytes()
        new_blob = digest(new_bytes)
        if new_blob == layer["rgbaBlob"]:
            continue
        width, height = layer["rasterWidth"], layer["rasterHeight"]
        stream = BytesIO()
        new.save(stream, "PNG")
        blob_path = prefix + f"blobs/{digest(new_blob.encode())}-{width}x{height}.png"
        entries[blob_path] = stream.getvalue()
        target = next(item for item in updated["layers"] if item["id"] == layer["id"])
        target["rgbaBlob"] = new_blob
        changed.append(layer["id"])
    if not changed:
        raise ValueError("No selected layer pixels changed")
    cleanup = None
    if args.clean_obsolete_mesh:
        mesh_id, separator, parameter = args.clean_obsolete_mesh.partition(":")
        if not separator or not mesh_id or not parameter:
            raise ValueError("--clean-obsolete-mesh must be MESH_ID:PARAMETER")
        cleanup = plan_obsolete_mesh_removal(updated, mesh_id, parameter)
        removed = set(cleanup.pop("indices"))
        updated["rigEdits"]["authoringJournal"] = [
            event for index, event in enumerate(updated["rigEdits"]["authoringJournal"]) if index not in removed
        ]
    layer_changes, changed_rig, changed_top = snapshot_changes(snapshot, updated)
    for change in layer_changes:
        if change["id"] in changed:
            if change["fields"] != ["rgbaBlob"]:
                raise ValueError(f"Unexpected layer changes: {change['id']} {change['fields']}")
        else:
            raise ValueError(f"Unselected layer changed: {change['id']} {change['fields']}")
    if changed_top or changed_rig != (["authoringJournal"] if cleanup else []):
        raise ValueError(f"Unexpected non-pixel changes: top={changed_top} rig={changed_rig}")
    revision = "revision-" + digest(encode(updated))
    node_id = "history-" + str(uuid.uuid4())
    node = {
        "version": 1,
        "id": node_id,
        "parentId": head["headNodeId"],
        "revisionId": revision,
        "snapshotHash": revision,
        "summary": args.summary,
        "actor": "agent",
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    entries[prefix + "history/snapshots/" + digest(revision.encode()) + ".json"] = encode(updated)
    entries[prefix + "history/nodes/" + digest(node_id.encode()) + ".json"] = encode(node)
    head["headNodeId"] = node_id
    head["nodeOrder"].append(node_id)
    entries[prefix + "HEAD.json"] = encode(head)
    ui = json.loads(entries["workspace.json"])
    ui["selectedHistoryNodeId"] = node_id
    entries["workspace.json"] = encode(ui)
    manifest["files"] = {name: digest(data) for name, data in entries.items() if name != "manifest.json"}
    entries["manifest.json"] = encode(manifest)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Output ZIP failed integrity test")
        for name, checksum in manifest["files"].items():
            if digest(archive.read(name)) != checksum:
                raise ValueError(f"Output manifest mismatch: {name}")
    rig_fields = sorted((snapshot.get("rigEdits") or {}))
    report = {
        "output": str(output),
        "node": node_id,
        "changed_layers": changed,
        "non_pixel_changes": [] if cleanup is None else [{
            "path": "rigEdits.authoringJournal",
            "reason": "removed mesh keyforms whose parameter was deleted and later owned by one Warp",
            **cleanup,
        }],
        "unchanged_rig_fields": [field for field in rig_fields if field != "authoringJournal" or cleanup is None],
        "remaining_mesh_delta_targets": mesh_delta_targets(updated["rigEdits"]["authoringJournal"]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
