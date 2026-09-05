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
SERVER_TRANSMIT = "newObj:transmitCompleteItemToServer()"
CLIENT_TRANSMIT = "newObj:transmitCompleteItemToClients()"
BROKEN_TRANSMIT = SERVER_TRANSMIT
FIXED_TRANSMIT = CLIENT_TRANSMIT
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
        r"(?m)^[ \t]*function[ \t]+MDO_Utils\.addObjectToSquare[ \t]*"
        r"\([ \t]*square[ \t]*,[ \t]*spriteName[ \t]*\)"
        r"[ \t]*(?:--[^\r\n]*)?$"
    )
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise UpstreamChangedError(
            f"expected exactly one function {LUA_FUNCTION}; found {len(matches)}"
        )
    start = matches[0].start()
    next_function = re.search(r"(?m)^[ \t]*function[ \t]+", text[matches[0].end():])
    end = matches[0].end() + next_function.start() if next_function else len(text)
    return start, end


def plan_lua_fix(text):
    """Return replacement text and status for the world-object sync repair."""
    start, end = function_region(text)
    region = text[start:end]
    broken_count = region.count(BROKEN_TRANSMIT)
    fixed_count = region.count(FIXED_TRANSMIT)

    if broken_count == 1 and fixed_count == 0:
        updated_region = region.replace(BROKEN_TRANSMIT, FIXED_TRANSMIT, 1)
        return text[:start] + updated_region + text[end:], "APPLIED"
    if broken_count == 0 and fixed_count == 1:
        return text, "ALREADY PATCHED"

    raise UpstreamChangedError(
        f"{LUA_FUNCTION}: expected one server or one client transmit call in its "
        f"body; found server={broken_count}, client={fixed_count}"
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
    """Plan each independent ladder repair without rejecting unrelated targets."""
    removals = []
    statuses = []
    for sprite_name, expected_ladder in LADDER_PROPERTIES.items():
        try:
            start, end = tile_block(text, sprite_name)
        except UpstreamChangedError as exc:
            statuses.append((sprite_name, "SKIPPED / UPSTREAM CHANGED", str(exc)))
            continue
        block = text[start:end]
        ladders = list(re.finditer(
            r"(?m)^(?P<indent>[ \t]*)(?P<name>ladder[WNES])[ \t]*="
            r"(?P<value>[^\r\n]*)(?:\r?\n|$)",
            block,
        ))
        unexpected = sorted({match.group("name") for match in ladders}
                            - {expected_ladder})
        if unexpected:
            statuses.append((
                sprite_name,
                "SKIPPED / UPSTREAM CHANGED",
                f"expected {expected_ladder} but found {', '.join(unexpected)}",
            ))
            continue
        expected = [match for match in ladders if match.group("name") == expected_ladder]
        if len(expected) > 1:
            statuses.append((
                sprite_name,
                "SKIPPED / UPSTREAM CHANGED",
                f"{expected_ladder} occurs more than once",
            ))
            continue
        force_fade = list(re.finditer(
            r"(?m)^(?P<indent>[ \t]*)forceFade[ \t]*=[ \t]*(?=\r?$)", block
        ))
        if len(force_fade) != 1:
            statuses.append((
                sprite_name,
                "SKIPPED / UPSTREAM CHANGED",
                f"expected exactly one forceFade property; found {len(force_fade)}",
            ))
            continue
        if not expected:
            statuses.append((sprite_name, "ALREADY PATCHED", None))
            continue
        match = expected[0]
        if match.group("value").strip():
            statuses.append((sprite_name, "UPSTREAM FIXED / SKIP", None))
            continue
        removals.append((start + match.start(), start + match.end()))
        statuses.append((sprite_name, "APPLIED", None))

    for start, end in reversed(removals):
        text = text[:start] + text[end:]
    return text, statuses


def run(ctx):
    log = ctx["log"]
    mod_root = ctx["WORKSHOP"] / WORKSHOP_ID / MOD_ROOT
    if not mod_root.is_dir():
        log("MoreDamagedObjects world-object sync: SKIPPED / TARGET NOT INSTALLED.")
        log("MoreDamagedObjects ladder tile properties: SKIPPED / TARGET NOT INSTALLED.")
        return False

    lua_path = mod_root / LUA_RELATIVE
    tile_path = mod_root / TILE_RELATIVE
    lua_changed = False
    if lua_path.is_file():
        try:
            lua_text = lua_path.read_text(encoding="utf-8", errors="strict")
            updated_lua, lua_status = plan_lua_fix(lua_text)
        except (UnicodeError, UpstreamChangedError) as exc:
            log(f"MoreDamagedObjects world-object sync: SKIPPED / UPSTREAM CHANGED ({exc}).")
        else:
            if updated_lua != lua_text:
                rewrite_atomically(lua_path, updated_lua)
                lua_changed = True
                log("MoreDamagedObjects world-object sync: patched.")
            else:
                log(f"MoreDamagedObjects world-object sync: {lua_status}.")
    else:
        log(f"MoreDamagedObjects world-object sync: SKIPPED / TARGET MISSING ({lua_path}).")

    tile_changed = False
    if tile_path.is_file():
        try:
            tile_text = tile_path.read_text(encoding="utf-8", errors="strict")
            updated_tiles, tile_statuses = plan_tile_fix(tile_text)
        except UnicodeError as exc:
            log(f"MoreDamagedObjects ladder tile properties: SKIPPED / UPSTREAM CHANGED ({exc}).")
        else:
            if updated_tiles != tile_text:
                rewrite_atomically(tile_path, updated_tiles)
                tile_changed = True
                log("MoreDamagedObjects ladder tile properties: patched.")
            for sprite_name, status, reason in tile_statuses:
                detail = f" ({reason})" if reason else ""
                log(f"MoreDamagedObjects ladder tile properties {sprite_name}: {status}{detail}.")
    else:
        log(f"MoreDamagedObjects ladder tile properties: SKIPPED / TARGET MISSING ({tile_path}).")
    return lua_changed or tile_changed


FIX = {
    "name": "MoreDamagedObjects B42.20 world sync and ladder tile properties",
    "run": run,
}
