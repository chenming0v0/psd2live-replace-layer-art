"""Read and compare PSD2Live v1 layer rasters with PSD layers."""

from io import BytesIO
from pathlib import Path
import hashlib
import json
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from psd_tools import PSDImage


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_project(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("Duplicate or missing ZIP entries")
        entries = {name: archive.read(name) for name in names if not name.endswith("/")}
    manifest = json.loads(entries["manifest.json"])
    if manifest.get("format") != "PSD2Live" or manifest.get("version") != 1:
        raise ValueError("Only PSD2Live v1 archives are supported")
    if set(manifest["files"]) != set(entries) - {"manifest.json"}:
        raise ValueError("Project inventory mismatch")
    if any(digest(entries[name]) != checksum for name, checksum in manifest["files"].items()):
        raise ValueError("Project resource checksum mismatch")
    prefix = f"workspace/{manifest['projectId']}/"
    head = json.loads(entries[prefix + "HEAD.json"])
    node_path = prefix + "history/nodes/" + digest(head["headNodeId"].encode()) + ".json"
    node = json.loads(entries[node_path])
    if node["id"] != head["headNodeId"]:
        raise ValueError("HEAD node mismatch")
    snapshot_path = prefix + "history/snapshots/" + digest(node["snapshotHash"].encode()) + ".json"
    snapshot = json.loads(entries[snapshot_path])
    return entries, manifest, prefix, head, snapshot


def unique(items, selector, label):
    matches = [item for item in items if item[0] == selector or item[1] == selector]
    if len(matches) != 1:
        raise ValueError(f"{label} {selector!r}: expected one match, found {len(matches)}")
    return matches[0][2]


def psd_layers(psd):
    result = []

    def visit(parent, path=""):
        for layer in parent:
            layer_path = f"{path}/{layer.name}" if path else layer.name
            if layer.is_group():
                visit(layer, layer_path)
            else:
                result.append((layer_path, layer.name, layer))

    visit(psd)
    return result


def select_layers(snapshot, psd, pairs):
    stored = [(layer["id"], layer["name"], layer) for layer in snapshot["layers"]]
    source = psd_layers(psd)
    selected = []
    seen = set()
    for mapping in pairs:
        project_selector, separator, psd_selector = mapping.partition("=")
        if not project_selector:
            raise ValueError("Empty project layer selector")
        layer = unique(stored, project_selector, "project layer")
        if layer["id"] in seen:
            raise ValueError(f"Duplicate target layer: {layer['id']}")
        seen.add(layer["id"])
        source_layer = unique(source, psd_selector if separator else project_selector, "PSD layer")
        selected.append((layer, source_layer))
    if not selected:
        raise ValueError("Specify at least one --layer")
    return selected


def raster_pair(entries, prefix, snapshot, psd, layer, source_layer):
    width, height = layer["rasterWidth"], layer["rasterHeight"]
    if (width, height) != (layer["width"], layer["height"]):
        raise ValueError(f"Raster and bounds differ: {layer['id']}")
    blob_path = prefix + f"blobs/{digest(layer['rgbaBlob'].encode())}-{width}x{height}.png"
    old = Image.open(BytesIO(entries[blob_path])).convert("RGBA")
    if old.size != (width, height) or digest(old.tobytes()) != layer["rgbaBlob"]:
        raise ValueError(f"Invalid raster blob: {layer['id']}")
    size = (snapshot["canvasWidth"], snapshot["canvasHeight"])
    if psd.size != size:
        raise ValueError(f"Canvas size mismatch: PSD {psd.size}, project {size}")
    source = source_layer.topil()
    if source is None:
        raise ValueError(f"PSD layer has no raster: {source_layer.name}")
    canvas = Image.new("RGBA", size)
    canvas.paste(source.convert("RGBA"), source_layer.bbox[:2])
    left, top = layer["left"], layer["top"]
    box = (left, top, left + width, top + height)
    if left < 0 or top < 0 or box[2] > size[0] or box[3] > size[1]:
        raise ValueError(f"Invalid project raster bounds: {layer['id']}")
    outside = canvas.copy()
    outside.paste((0, 0, 0, 0), box)
    if outside.getchannel("A").getbbox():
        raise ValueError(f"New visible pixels exceed old raster bounds: {layer['id']}")
    return old, canvas.crop(box)


def difference(old, new, offset):
    before = np.asarray(old).astype(np.int16)
    after = np.asarray(new).astype(np.int16)
    alpha = np.abs(before[:, :, 3] - after[:, :, 3])
    rgb = np.max(np.abs(before[:, :, :3] - after[:, :, :3]), axis=2)
    visible = (before[:, :, 3] > 8) & (after[:, :, 3] > 8)
    significant = (alpha > 8) | (visible & (rgb > 8))
    ys, xs = np.where(significant)
    bbox = None if len(xs) == 0 else [int(xs.min() + offset[0]), int(ys.min() + offset[1]),
                                      int(xs.max() + 1 + offset[0]), int(ys.max() + 1 + offset[1])]
    invisible = ~((before[:, :, 3] > 8) | (after[:, :, 3] > 8))
    return {
        "alpha_changed_pixels": int(np.count_nonzero(alpha)),
        "significant_pixels": int(np.count_nonzero(significant)),
        "invisible_rgb_only_pixels": int(np.count_nonzero(invisible & (rgb > 0))),
        "significant_canvas_bbox": bbox,
        "new_alpha_bbox_local": new.getchannel("A").getbbox(),
    }


def comparison_image(rows, output):
    width = max(max(old.width, new.width) for _, old, new in rows)
    height = sum(max(old.height, new.height) + 38 for _, old, new in rows) + 10
    image = Image.new("RGB", (width * 3 + 40, height), "#d0d0d0")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    y = 8
    for name, old, new in rows:
        a, b = np.asarray(old).astype(np.int16), np.asarray(new).astype(np.int16)
        alpha = np.abs(a[:, :, 3] - b[:, :, 3])
        rgb = np.max(np.abs(a[:, :, :3] - b[:, :, :3]), axis=2)
        visible = (a[:, :, 3] > 8) & (b[:, :, 3] > 8)
        heat = np.full((old.height, old.width, 3), 24, dtype=np.uint8)
        heat[:, :, 0] = np.clip(24 + alpha * 3, 0, 255)
        heat[:, :, 1] = np.clip(24 + np.where(visible, rgb, 0) * 3, 0, 255)
        heat[:, :, 2] = heat[:, :, 1]
        for column, (label, item) in enumerate((("OLD", old), ("NEW", new), ("DIFF alpha=red rgb=cyan", Image.fromarray(heat)))):
            x = 10 + column * (width + 10)
            draw.text((x, y), f"{label}: {name}", fill="black", font=font)
            tile = Image.new("RGBA", item.size, "#b9b9b9")
            tile.alpha_composite(item.convert("RGBA"))
            image.paste(tile.convert("RGB"), (x, y + 20))
        y += max(old.height, new.height) + 38
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    image.save(output)


def summarize_event(index, event):
    summary = {"index": index, "op": event.get("op"), "target": event.get("target")}
    for field in ("key", "parameter", "from", "destination"):
        if field in event:
            summary[field] = event.get(field)
    geometry = event.get("geometry") or {}
    if geometry:
        summary["geometry"] = {
            key: len(value) if isinstance(value, list) else value
            for key, value in geometry.items()
        }
    warp = event.get("warp")
    if isinstance(warp, dict):
        summary["warp"] = warp.get("id")
    meshes = event.get("mesh_ids")
    if meshes is None and isinstance(warp, dict):
        meshes = warp.get("mesh_ids")
    if meshes is not None:
        summary["mesh_ids"] = meshes
    return summary


def summarize_journal(journal):
    return [summarize_event(index, event) for index, event in enumerate(journal)]


def mesh_delta_targets(journal):
    found = []
    for event in journal:
        target = event.get("target") or ""
        geometry = event.get("geometry") or {}
        if (event.get("op") == "set" and target.startswith("mesh:")
                and isinstance(geometry.get("positionDeltas"), list)):
            mesh_id = target.split(":", 1)[1]
            if mesh_id not in found:
                found.append(mesh_id)
    return found


def _contains_exact_id(value, mesh_id):
    if isinstance(value, str):
        return value == mesh_id or value == f"mesh:{mesh_id}"
    if isinstance(value, dict):
        return any(_contains_exact_id(item, mesh_id) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_id(item, mesh_id) for item in value)
    return False


def _event_mesh_ids(event):
    # 已验证的存档把 mesh_ids 放在 warp 操作顶层，不在 warp 对象内部。
    meshes = event.get("mesh_ids")
    warp = event.get("warp")
    if meshes is None and isinstance(warp, dict):
        meshes = warp.get("mesh_ids")
    return meshes or []


def plan_obsolete_mesh_removal(snapshot, mesh_id, parameter):
    """Return the only mesh-keyform removal the journal itself proves obsolete."""
    rig = snapshot.get("rigEdits") or {}
    journal = rig.get("authoringJournal") or []
    for field in ("keyformSets", "keyformCopies", "keyformDeletes"):
        if _contains_exact_id(rig.get(field), mesh_id):
            raise ValueError(f"Refusing journal cleanup: {field} still references {mesh_id}")
    target = f"mesh:{mesh_id}"
    matches = [(index, event) for index, event in enumerate(journal) if event.get("target") == target]
    if len(matches) != 4:
        raise ValueError("Refusing journal cleanup: expected exactly four events for this mesh")
    keys = []
    for _, event in matches[:3]:
        key = event.get("key")
        geometry = event.get("geometry") or {}
        deltas = geometry.get("positionDeltas")
        if (event.get("op") != "set" or set(event) != {"op", "target", "key", "geometry"}
                or not isinstance(key, dict) or set(key) != {parameter}
                or isinstance(key[parameter], bool) or not isinstance(key[parameter], (int, float))
                or set(geometry) != {"positionDeltas"} or not isinstance(deltas, list) or not deltas):
            raise ValueError("Refusing journal cleanup: mesh sets must contain only one parameter and positionDeltas")
        keys.append(key[parameter])
    if len(set(keys)) != 3:
        raise ValueError("Refusing journal cleanup: expected three distinct key values")
    delete_index, delete_event = matches[3]
    if (delete_event.get("op") != "delete" or delete_event.get("parameter") != parameter
            or set(delete_event) != {"op", "target", "parameter"}):
        raise ValueError("Refusing journal cleanup: expected one plain delete of the same parameter")
    for index, event in enumerate(journal):
        if event.get("target") == target or event.get("op") == "warp":
            continue
        if (event.get("op") in {"copy", "seed", "deform", "path_deform"}
                and (event.get("target") == target or event.get("destination") == target
                     or mesh_id in _event_mesh_ids(event))):
            raise ValueError(f"Refusing journal cleanup: event {index} derives from the mesh")
        if event.get("target") == target or event.get("destination") == target:
            raise ValueError(f"Refusing journal cleanup: event {index} still references the mesh")
    later = journal[delete_index + 1:]
    owners = []
    for event in later:
        if event.get("op") != "warp" or mesh_id not in _event_mesh_ids(event):
            continue
        warp_id = (event.get("warp") or {}).get("id")
        if not warp_id:
            continue
        values = [
            item.get("key", {}).get(parameter)
            for item in later
            if item.get("op") == "set" and item.get("target") == f"warp:{warp_id}"
            and set(item.get("key") or {}) == {parameter}
        ]
        if set(keys).issubset(values):
            owners.append(warp_id)
    if len(owners) != 1:
        raise ValueError("Refusing journal cleanup: expected exactly one later Warp to own every removed key")
    return {
        "mesh": mesh_id,
        "parameter": parameter,
        "removed_keys": keys,
        "warp": owners[0],
        "removed": [summarize_event(index, event) for index, event in matches],
        "indices": [index for index, _ in matches],
    }
