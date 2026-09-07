"""Small guarded helpers shared by vehicle compatibility fixes."""
import re
import shutil


TEMPLATE_RE = re.compile(r"\btemplate\s+vehicle\s+([A-Za-z0-9_]+)\b")
PART_RE = re.compile(r"\bpart\s+([A-Za-z0-9_]+)\b")
MOD_INFO_ID_RE = re.compile(r"(?m)^\s*id\s*=\s*([^\r\n]+?)\s*$")


def balanced(text):
    depth = 0
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def block_after(text, match):
    start = text.find("{", match.end())
    if start < 0:
        return None
    depth = 0
    for end in range(start, len(text)):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():end + 1]
    return None


def named_blocks(text, pattern):
    result = {}
    for match in pattern.finditer(text):
        block = block_after(text, match)
        if block is None:
            raise ValueError(f"unbalanced block for {match.group(1)}")
        result.setdefault(match.group(1), block)
    return result


def files_under(tree):
    scripts = tree / "media" / "scripts"
    return sorted(scripts.rglob("*.txt")) if scripts.is_dir() else []


def mod_info_ids(mod_root):
    """Return declared Mod IDs without following lowercase alias symlinks."""
    result = set()
    try:
        for info in mod_root.rglob("mod.info"):
            if info.is_symlink() or not info.is_file():
                continue
            result.update(MOD_INFO_ID_RE.findall(info.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return set()
    return result


def active_mod_roots(workshop, active_workshop_ids, active_mod_ids):
    """Yield real roots for configured active mods in active Workshop items."""
    active_ids = set(active_mod_ids)
    for workshop_id in active_workshop_ids:
        mods_root = workshop / workshop_id / "mods"
        if not mods_root.is_dir():
            continue
        try:
            mod_roots = sorted(mods_root.iterdir())
        except OSError:
            continue
        for mod_root in mod_roots:
            if mod_root.is_symlink() or not mod_root.is_dir():
                continue
            if not active_ids or mod_info_ids(mod_root) & active_ids:
                yield mod_root


def active_mod_script_files(workshop, active_workshop_ids, active_mod_ids):
    """Yield text scripts from real active mod roots and their installed versions."""
    for mod_root in active_mod_roots(workshop, active_workshop_ids, active_mod_ids):
        script_roots = [mod_root / "media" / "scripts"]
        try:
            versions = sorted(mod_root.iterdir())
        except OSError:
            continue
        script_roots.extend(
            version / "media" / "scripts"
            for version in versions
            if not version.is_symlink() and version.is_dir()
        )
        for scripts in script_roots:
            if scripts.is_symlink() or not scripts.is_dir():
                continue
            try:
                for path in sorted(scripts.rglob("*.txt")):
                    if not path.is_symlink() and ".pz-local-fix" not in path.name:
                        yield path
            except OSError:
                continue


def template_locations(tree):
    locations = {}
    for path in files_under(tree):
        try:
            blocks = named_blocks(path.read_text(encoding="utf-8", errors="replace"), TEMPLATE_RE)
        except ValueError:
            continue
        for name, block in blocks.items():
            locations.setdefault(name, (path, block))
    return locations


def backup_and_write(path, text):
    backup = path.with_suffix(path.suffix + ".pz-local-fix.bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def backup_and_write_bytes(path, data):
    """Write bytes in place so the target file retains its ownership and mode."""
    backup = path.with_suffix(path.suffix + ".pz-local-fix.bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    with path.open("r+b") as stream:
        stream.write(data)
        stream.truncate()


def add_compatibility_templates(path, wanted, upstream, log, label):
    """Append missing named blocks in a separate module without replacing content."""
    current = {}
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        if not balanced(text):
            log(f"{label}: blocked; existing compatibility file has unbalanced braces: {path}")
            return False
        names = [match.group(1) for match in TEMPLATE_RE.finditer(text)]
        if len(names) != len(set(names)):
            log(f"{label}: blocked; duplicate template names in {path}")
            return False
        try:
            current = named_blocks(text, TEMPLATE_RE)
        except ValueError as exc:
            log(f"{label}: blocked; {exc}: {path}")
            return False

    additions = []
    for name in sorted(wanted):
        if name in upstream:
            log(f"{label}: upstream fixed {name}; skip.")
        elif name in current:
            log(f"{label}: {name} already fixed; skip.")
        else:
            additions.append(wanted[name].rstrip())

    if not additions:
        return False
    payload = "\n\nmodule Base\n{\n" + "\n\n".join(additions) + "\n}\n"
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    backup_and_write(path, old.rstrip() + payload)
    log(f"{label}: patched {path.name} with {len(additions)} compatibility template(s).")
    return True


def tree(workshop, workshop_id, mod_name, version):
    return workshop / workshop_id / "mods" / mod_name / version


def clone_template(source_block, old_name, new_name):
    return re.sub(
        r"(\btemplate\s+vehicle\s+)" + re.escape(old_name) + r"\b",
        r"\g<1>" + new_name,
        source_block,
        count=1,
    )
