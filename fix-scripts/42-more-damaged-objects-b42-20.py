#!/usr/bin/env python3
"""Apply guarded Build 42.20 repairs for MoreDamagedObjects."""
import os
from pathlib import Path
import re
import tempfile


WORKSHOP_ID = "3413150945"
MOD_ROOT = Path("mods/MoreDamagedObjects")
LUA_RELATIVE = Path("42.20/media/lua/shared/MDO_Utils.lua")
TILE_RELATIVE = Path("common/media/ct_new_vanilla_def.tiles.txt")
LUA_FUNCTION = "MDO_Utils.addObjectToSquare"
CLIENT_TRANSMIT = "newObj:transmitCompleteItemToClients()"
SERVER_TRANSMIT = "newObj:transmitCompleteItemToServer()"
LADDER_PROPERTIES = {
    "carpentry_02_84": "ladderW",
    "carpentry_02_85": "ladderN",
    "carpentry_02_86": "ladderE",
    "carpentry_02_87": "ladderS",
}


class UpstreamChangedError(RuntimeError):
    """The narrowly targeted upstream structure no longer matches."""


def rewrite_atomically(path, text):
    """Replace a validated text file without creating routine backups."""
    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary:
            descriptor = None
            temporary.write(text)
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


def function_region(text):
    """Return the named function through the next top-level function declaration."""
    header = re.compile(
        r"(?m)^function[ \t]+MDO_Utils\.addObjectToSquare"
        r"\([ \t]*square[ \t]*,[ \t]*spriteName[ \t]*\)[ \t]*$"
    )
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise UpstreamChangedError(
            f"expected exactly one function {LUA_FUNCTION}; found {len(matches)}"
        )
    start = matches[0].start()
    next_function = re.search(r"(?m)^function[ \t]+", text[matches[0].end():])
    end = matches[0].end() + next_function.start() if next_function else len(text)
    return start, end


def plan_lua_fix(text):
    """Return replacement text and status for the world-object sync repair."""
    start, end = function_region(text)
    client_count = text.count(CLIENT_TRANSMIT)
    server_count = text.count(SERVER_TRANSMIT)
    region = text[start:end]

    if client_count == 1 and server_count == 0 and CLIENT_TRANSMIT in region:
        return text.replace(CLIENT_TRANSMIT, SERVER_TRANSMIT, 1), "APPLIED"
    if client_count == 0 and server_count == 1 and SERVER_TRANSMIT in region:
        return text, "ALREADY PATCHED"

    raise UpstreamChangedError(
        f"{LUA_FUNCTION}: expected one client or one server transmit call in its "
        f"body; found client={client_count}, server={server_count}"
    )


def tile_block(text, sprite_name):
    """Return the tile block identified by its sprite comment, never by a line number."""
    comment = re.compile(rf"(?m)^//[ \t]+{re.escape(sprite_name)}[ \t]*$")
    comments = list(comment.finditer(text))
    if len(comments) != 1:
        raise UpstreamChangedError(
            f"{sprite_name}: expected exactly one tile comment; found {len(comments)}"
        )
    following_comment = re.search(r"(?m)^//", text[comments[0].end():])
    search_end = comments[0].end() + following_comment.start() if following_comment else len(text)
    opener = re.search(r"\btile[ \t\r\n]*\{", text[comments[0].end():search_end])
    if opener is None:
        raise UpstreamChangedError(f"{sprite_name}: tile block missing after its comment")
    open_at = comments[0].end() + opener.end() - 1

    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return open_at, index + 1
    raise UpstreamChangedError(f"{sprite_name}: tile block has no closing brace")


def plan_tile_fix(text):
    """Return replacement text and per-tile statuses for the ladder repair."""
    newline = "\r\n" if "\r\n" in text else "\n"
    insertions = []
    statuses = []
    for sprite_name, expected_ladder in LADDER_PROPERTIES.items():
        start, end = tile_block(text, sprite_name)
        block = text[start:end]
        ladders = re.findall(r"(?m)^[ \t]*(ladder[WNES])[ \t]*=", block)
        unexpected = sorted(set(ladders) - {expected_ladder})
        if unexpected:
            raise UpstreamChangedError(
                f"{sprite_name}: expected {expected_ladder} but found "
                f"{', '.join(unexpected)}"
            )
        if ladders.count(expected_ladder) > 1:
            raise UpstreamChangedError(
                f"{sprite_name}: {expected_ladder} occurs more than once"
            )
        if ladders:
            statuses.append((sprite_name, "ALREADY PATCHED"))
            continue

        force_fade = list(re.finditer(
            r"(?m)^(?P<indent>[ \t]*)forceFade[ \t]*=[ \t]*(?=\r?$)", block
        ))
        if len(force_fade) != 1:
            raise UpstreamChangedError(
                f"{sprite_name}: expected exactly one forceFade property; "
                f"found {len(force_fade)}"
            )
        match = force_fade[0]
        insertions.append((start + match.end(), f"{newline}{match.group('indent')}{expected_ladder} ="))
        statuses.append((sprite_name, "APPLIED"))

    for position, insertion in reversed(insertions):
        text = text[:position] + insertion + text[position:]
    return text, statuses


def run(ctx):
    log = ctx["log"]
    mod_root = ctx["WORKSHOP"] / WORKSHOP_ID / MOD_ROOT
    if not mod_root.is_dir():
        log("MoreDamagedObjects world-object sync: SKIPPED / TARGET MISSING (mod not installed).")
        log("MoreDamagedObjects ladder tile properties: SKIPPED / TARGET MISSING (mod not installed).")
        return False

    lua_path = mod_root / LUA_RELATIVE
    tile_path = mod_root / TILE_RELATIVE
    try:
        if lua_path.is_file():
            lua_text = lua_path.read_text(encoding="utf-8", errors="strict")
            updated_lua, lua_status = plan_lua_fix(lua_text)
        else:
            lua_text = updated_lua = None
            lua_status = "SKIPPED / TARGET MISSING"
    except (OSError, UnicodeError, UpstreamChangedError) as exc:
        log(f"MoreDamagedObjects world-object sync: FAILED / UPSTREAM CHANGED ({exc}).")
        raise UpstreamChangedError(str(exc)) from exc

    try:
        if tile_path.is_file():
            tile_text = tile_path.read_text(encoding="utf-8", errors="strict")
            updated_tiles, tile_statuses = plan_tile_fix(tile_text)
        else:
            tile_text = updated_tiles = None
            tile_statuses = []
    except (OSError, UnicodeError, UpstreamChangedError) as exc:
        log(f"MoreDamagedObjects ladder tile properties: FAILED / UPSTREAM CHANGED ({exc}).")
        raise UpstreamChangedError(str(exc)) from exc

    if updated_lua is not None and updated_lua != lua_text:
        rewrite_atomically(lua_path, updated_lua)
    if updated_tiles is not None and updated_tiles != tile_text:
        rewrite_atomically(tile_path, updated_tiles)

    lua_detail = f" ({lua_path})" if lua_text is None else ""
    log(f"MoreDamagedObjects world-object sync: {lua_status}.{lua_detail}")
    if tile_text is None:
        log(f"MoreDamagedObjects ladder tile properties: SKIPPED / TARGET MISSING ({tile_path}).")
    else:
        for sprite_name, status in tile_statuses:
            log(f"MoreDamagedObjects ladder tile properties {sprite_name}: {status}.")
    return (
        (updated_lua is not None and updated_lua != lua_text)
        or (updated_tiles is not None and updated_tiles != tile_text)
    )


FIX = {
    "name": "MoreDamagedObjects B42.20 world sync and ladder tile properties",
    "run": run,
}
