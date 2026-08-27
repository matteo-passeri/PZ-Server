#!/usr/bin/env python3
"""Remove RadArchery Bob animation channels unsupported by PZ's skeleton."""
import copy
import json
import os
from pathlib import Path
import struct
import tempfile


WORKSHOP_ID = "3775407541"
MOD_NAME = "RadArchery"
BOB_RELATIVE = Path("mods/RadArchery/42/media/anims_X/Bob")
GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK_TYPE = b"JSON"
PROTECTED_SECTIONS = (
    "nodes",
    "skins",
    "accessors",
    "bufferViews",
    "buffers",
    "meshes",
    "materials",
)
UNSUPPORTED_NODE_NAMES = frozenset((
    "HLPR-ChestTransform",
    "HLPR=RemapSpace",
    "Bip01_Prop1_end",
    "Bip01_Prop2_end",
    "Bip01_Root",
))


class GLBValidationError(ValueError):
    """A malformed or unexpected GLB that must be left untouched."""


def parse_glb(data):
    """Return a validated GLB document and its original non-JSON chunks."""
    if len(data) < 12:
        raise GLBValidationError("file is shorter than the GLB header")

    magic, version, total_length = struct.unpack_from("<4sII", data)
    if magic != GLB_MAGIC:
        raise GLBValidationError("magic is not glTF")
    if version != GLB_VERSION:
        raise GLBValidationError(f"unsupported GLB version {version}")
    if total_length != len(data):
        raise GLBValidationError(
            f"header length {total_length} does not match file size {len(data)}"
        )

    chunks = []
    offset = 12
    while offset < len(data):
        if len(data) - offset < 8:
            raise GLBValidationError("truncated chunk header")
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        chunk_end = offset + 8 + chunk_length
        if chunk_length % 4:
            raise GLBValidationError("chunk length is not 4-byte aligned")
        if chunk_end > len(data):
            raise GLBValidationError("chunk extends beyond EOF")
        chunks.append((chunk_type, data[offset + 8:chunk_end]))
        offset = chunk_end

    if offset != len(data) or not chunks:
        raise GLBValidationError("GLB chunks do not exactly fill the file")
    if chunks[0][0] != JSON_CHUNK_TYPE:
        raise GLBValidationError("first GLB chunk is not JSON")
    if sum(chunk_type == JSON_CHUNK_TYPE for chunk_type, _ in chunks) != 1:
        raise GLBValidationError("GLB must contain exactly one JSON chunk")

    try:
        document = json.loads(chunks[0][1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GLBValidationError(f"invalid JSON chunk: {exc}") from exc
    if not isinstance(document, dict):
        raise GLBValidationError("GLTF JSON root is not an object")

    return document, chunks


def remove_action_stash_animations(document, intended_name):
    """Retain the one expected animation and reject unrecognized extras."""
    animations = document.get("animations")
    if not isinstance(animations, list):
        raise GLBValidationError("GLTF animations section is missing or invalid")

    intended = []
    action_stash = []
    for animation_index, animation in enumerate(animations):
        if not isinstance(animation, dict):
            raise GLBValidationError(f"animation {animation_index} is not an object")
        name = animation.get("name")
        if name == intended_name:
            intended.append(animation)
        elif isinstance(name, str) and name.startswith("[Action Stash]"):
            action_stash.append(animation)
        else:
            raise GLBValidationError(
                f"animation {animation_index} has an unexpected name {name!r}"
            )

    if len(intended) != 1:
        raise GLBValidationError(
            f"expected exactly one animation named {intended_name!r}; found {len(intended)}"
        )

    document["animations"] = intended
    return len(action_stash)


def remove_unsupported_channels(document):
    """Return the number of channels removed from the intended animation."""
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        raise GLBValidationError("GLTF nodes section is missing or invalid")

    animations = document.get("animations", [])
    if not isinstance(animations, list):
        raise GLBValidationError("GLTF animations section is invalid")

    removed = 0
    for animation_index, animation in enumerate(animations):
        if not isinstance(animation, dict):
            raise GLBValidationError(f"animation {animation_index} is not an object")
        channels = animation.get("channels", [])
        if not isinstance(channels, list):
            raise GLBValidationError(
                f"animation {animation_index} channels section is invalid"
            )

        kept = []
        for channel_index, channel in enumerate(channels):
            if not isinstance(channel, dict):
                raise GLBValidationError(
                    f"animation {animation_index} channel {channel_index} is not an object"
                )
            target = channel.get("target")
            if not isinstance(target, dict):
                raise GLBValidationError(
                    f"animation {animation_index} channel {channel_index} target is invalid"
                )

            # A channel without target.node may use an extension target. It is
            # unrelated to this narrow bone-name repair and is left intact.
            if "node" not in target:
                kept.append(channel)
                continue

            node_index = target["node"]
            if (
                isinstance(node_index, bool)
                or not isinstance(node_index, int)
                or node_index < 0
                or node_index >= len(nodes)
                or not isinstance(nodes[node_index], dict)
            ):
                raise GLBValidationError(
                    f"animation {animation_index} channel {channel_index} "
                    "has an invalid target node"
                )

            node_name = nodes[node_index].get("name")
            if node_name in UNSUPPORTED_NODE_NAMES:
                removed += 1
            else:
                kept.append(channel)
        animation["channels"] = kept

    return removed


def rebuild_glb(document, chunks):
    """Re-encode only JSON; retain each non-JSON chunk's bytes verbatim."""
    try:
        json_data = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise GLBValidationError(f"unable to encode GLTF JSON: {exc}") from exc
    json_data += b" " * (-len(json_data) % 4)

    encoded_chunks = [(JSON_CHUNK_TYPE, json_data)] + [
        (chunk_type, chunk_data)
        for chunk_type, chunk_data in chunks[1:]
    ]
    payload = b"".join(
        struct.pack("<I4s", len(chunk_data), chunk_type) + chunk_data
        for chunk_type, chunk_data in encoded_chunks
    )
    return struct.pack("<4sII", GLB_MAGIC, GLB_VERSION, 12 + len(payload)) + payload


def rewrite_atomically(path, data):
    """Replace a validated file without retaining an automatic backup."""
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "wb") as temporary:
            descriptor = None
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def transform_glb(path):
    """Return both removal counts, or raise before making any file changes."""
    original_data = path.read_bytes()
    original_document, chunks = parse_glb(original_data)
    updated_document = copy.deepcopy(original_document)
    action_stash_removed = remove_action_stash_animations(
        updated_document,
        path.stem,
    )
    channels_removed = remove_unsupported_channels(updated_document)
    if not action_stash_removed and not channels_removed:
        return 0, 0

    for section in PROTECTED_SECTIONS:
        if original_document.get(section) != updated_document.get(section):
            raise GLBValidationError(f"protected {section} section changed unexpectedly")

    rebuilt = rebuild_glb(updated_document, chunks)
    # Re-parse the result before replacing the original and verify binary
    # chunks remain exact, rather than trusting the reconstruction alone.
    rebuilt_document, rebuilt_chunks = parse_glb(rebuilt)
    if any(
        rebuilt_document.get(section) != original_document.get(section)
        for section in PROTECTED_SECTIONS
    ):
        raise GLBValidationError("rebuilt GLB changed a protected section")
    if rebuilt_chunks[1:] != chunks[1:]:
        raise GLBValidationError("rebuilt GLB changed a non-JSON chunk")

    rewrite_atomically(path, rebuilt)
    return action_stash_removed, channels_removed


def run(ctx):
    log = ctx["log"]
    if WORKSHOP_ID not in ctx["active_workshop_ids"]:
        log("RadArchery: Workshop 3775407541 is not active; skip.")
        return False

    root = ctx["WORKSHOP"] / WORKSHOP_ID / BOB_RELATIVE
    if not root.is_dir():
        log("RadArchery: B42 Bob GLB tree not present; skip.")
        return False

    paths = sorted(path for path in root.glob("*.glb") if path.is_file())
    changed_files = 0
    removed_action_stash = 0
    removed_channels = 0
    for path in paths:
        try:
            action_stash_removed, channels_removed = transform_glb(path)
        except (GLBValidationError, OSError) as exc:
            log(f"RadArchery: blocked; leaving {path.name} untouched: {exc}")
            continue
        if action_stash_removed or channels_removed:
            changed_files += 1
            removed_action_stash += action_stash_removed
            removed_channels += channels_removed

    state = "already clean" if not changed_files else "repaired"
    log(
        "RadArchery: "
        f"inspected {len(paths)} Bob GLBs; {state}; "
        f"files changed={changed_files}; "
        f"Action Stash animations removed={removed_action_stash}; "
        f"channels removed={removed_channels}."
    )
    return changed_files > 0


FIX = {
    "name": "RadArchery B42 Bob GLB unsupported bone channels",
    "run": run,
}
