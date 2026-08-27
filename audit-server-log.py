#!/usr/bin/env python3
"""Create concise startup and runtime audits from a PZ DebugLog-server file."""
import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
REPORTS_DIR = SCRIPT_DIR / "reports"
STARTED_MARKER = "*** SERVER STARTED ****"
TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b")
NO_SUCH_FILE_PATH_RE = re.compile(
    r"java\.nio\.file\.NoSuchFileException\s*:\s*"
    r"(?P<path>(?:[A-Za-z]:)?[/\\][^\r\n]+)",
    flags=re.I,
)
JAVA_STACK_SUFFIX_RE = re.compile(
    r"\s+at\s+(?:[A-Za-z_$][\w$]*\.)+[A-Za-z_$][\w$]*"
    r"\([^\r\n)]*\)\.?\s*$"
)
OPTIONAL_ANIMATION_PROBE_RE = re.compile(
    r"(?:^|/)steamapps/workshop/content/108600/"
    r"(?P<workshop_id>\d+)/mods/[^/]+/"
    r"(?:common|\d+(?:\.\d+)*)/media/"
    r"(?P<directory>AnimSets|actiongroups)$",
    flags=re.I,
)

CRITICAL_PATTERNS = (
    "nullpointerexception", "kahluaexception", "outofmemoryerror",
    "stackoverflowerror", "illegalstateexception", "illegalargumentexception",
    "classcastexception", "indexoutofboundsexception",
    "concurrentmodificationexception", "assertionerror", "fatal error",
    "server crash", "crash report", "save corruption", "load corruption",
)
DEPENDENCY_PATTERNS = (
    "required mod", "dependency not found", "mod not found",
    "unknown tile properties", "duplicate room metaid", "invalid room metaid",
    "missing vehicle", "missing script template", "template \"",
    "template '",
)
ANIMATION_PATTERNS = (
    "advancedanimator", "animsets", "actiongroups", "missing bones",
    "could not find bone index", "animation", "animation xml",
)
LOW_PATTERNS = (
    "missing thumpsound", "sanitizing container names",
    "sanitizing container name", "cosmetic warning",
)


@dataclass
class Event:
    line_number: int
    line: str
    category: str
    severity: str


def optional_animation_probe_details(line: str) -> tuple[str, str, str] | None:
    """Return an optional PZ animation-directory probe, if this line is one.

    The anchor deliberately accepts only direct conventional loader probes in
    a Steam Workshop mod tree. Missing assets below those directories, local
    mods, and unrelated ``NoSuchFileException`` entries remain auditable.
    """
    exception = NO_SUCH_FILE_PATH_RE.search(line)
    if not exception:
        return None

    path_text = JAVA_STACK_SUFFIX_RE.sub("", exception.group("path"))
    path_text = path_text.strip().strip("\"'").rstrip(".,;:)]}")
    normalized = path_text.replace("\\", "/")
    match = OPTIONAL_ANIMATION_PROBE_RE.search(normalized)
    if not match:
        return None
    return match.group("directory"), path_text, match.group("workshop_id")


def is_optional_animation_probe(line: str) -> bool:
    """Whether a line is a suppressible optional animation-directory probe."""
    return optional_animation_probe_details(line) is not None


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def latest_debug_log(env: dict[str, str]) -> Path:
    data_dir = env.get("PZ_ZOMBOID_DATA_DIR", "").strip()
    if not data_dir:
        raise RuntimeError("PZ_ZOMBOID_DATA_DIR is missing from .env")
    logs_dir = Path(data_dir).expanduser() / "Logs"
    candidates = [path for path in logs_dir.glob("*DebugLog-server.txt") if path.is_file()]
    if not candidates:
        raise RuntimeError(f"No DebugLog-server files found in {logs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def classify(line: str) -> tuple[str, str] | None:
    lowered = line.casefold()
    lua_nil = re.search(r"attempt to (call|index).{0,100}nil", lowered)
    if any(pattern in lowered for pattern in CRITICAL_PATTERNS) or lua_nil:
        return "CRITICAL / HIGH", "critical"
    if any(pattern in lowered for pattern in DEPENDENCY_PATTERNS):
        return "DEPENDENCY / CONFIG", "important"
    if any(pattern in lowered for pattern in ANIMATION_PATTERNS):
        return "ANIMATION / ASSET", "important"
    if any(pattern in lowered for pattern in LOW_PATTERNS):
        return "LOW / NOISE", "low"
    if re.search(r"\b(error|warn|exception)\b", lowered):
        return "OTHER / WARNING", "important"
    return None


def find_events(lines: list[str], start: int, end: int) -> list[Event]:
    events = []
    for index in range(start, end):
        if is_optional_animation_probe(lines[index]):
            continue
        result = classify(lines[index])
        if result:
            category, severity = result
            events.append(Event(index + 1, lines[index], category, severity))
    return events


def counts(lines: list[str]) -> dict[str, int]:
    text = "\n".join(lines)
    return {
        "ERROR": len(re.findall(r"\bERROR\b", text, flags=re.I)),
        "WARN": len(re.findall(r"\bWARN(?:ING)?\b", text, flags=re.I)),
        "Exception": len(re.findall(r"\b\w*Exception\b", text)),
    }


def normalize_message(line: str) -> str:
    message = line.strip()
    lowered = message.casefold()
    if "could not find bone index" in lowered:
        return "Could not find bone index for ..."
    if "missing thumpsound" in lowered:
        return "Missing ThumpSound ..."
    if "exception thrown" in lowered:
        return "Exception thrown"
    if "template" in lowered and "not found" in lowered:
        return 'template "..." not found'
    message = re.sub(r"0x[0-9a-fA-F]+", "0x...", message)
    message = re.sub(r"\b\d+\b", "#", message)
    return message


def source_timestamp(line: str) -> str:
    match = TIMESTAMP_RE.search(line)
    return match.group(0) if match else "unknown timestamp"


def event_context(event: Event, lines: list[str], limit: int = 8) -> list[str]:
    context = [event.line]
    for line in lines[event.line_number:event.line_number + limit]:
        if line.strip() == STARTED_MARKER:
            break
        context.append(line)
    return context


def report_stem(source: Path) -> str:
    match = re.search(
        r"(\d{4})[-_](\d{2})[-_](\d{2})[^0-9]+(\d{2})[-_:](\d{2})",
        source.name,
    )
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}_{match.group(4)}-{match.group(5)}"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", source.stem).strip("-")


def format_report(
    source: Path,
    lines: list[str],
    phase: str,
    phase_start: int,
    phase_end: int,
    marker_index: int | None,
) -> str:
    all_counts = counts(lines)
    phase_lines = lines[phase_start:phase_end]
    phase_counts = counts(phase_lines)
    events = find_events(lines, phase_start, phase_end)
    probe_details = [
        details
        for line in lines[phase_start:phase_end]
        if (details := optional_animation_probe_details(line)) is not None
    ]
    header = [
        "Project Zomboid Server Log Audit",
        f"Phase: {phase}",
        f"Source log: {source}",
        f"Source modification time: {datetime.fromtimestamp(source.stat().st_mtime).astimezone().isoformat()}",
        f"SERVER STARTED reached: {'yes' if marker_index is not None else 'no'}",
        f"SERVER STARTED line number: {marker_index + 1 if marker_index is not None else 'not reached'}",
        f"Raw total log counts: ERROR={all_counts['ERROR']}, WARN={all_counts['WARN']}, Exception={all_counts['Exception']}",
        f"Raw {phase} counts: ERROR={phase_counts['ERROR']}, WARN={phase_counts['WARN']}, Exception={phase_counts['Exception']}",
        f"Actionable classified events: {len(events)}",
        "",
    ]
    if marker_index is None:
        header.extend(["INCOMPLETE STARTUP: SERVER STARTED was not reached.", ""])

    grouped = {category: [] for category in (
        "CRITICAL / HIGH", "DEPENDENCY / CONFIG", "ANIMATION / ASSET",
        "LOW / NOISE", "OTHER / WARNING",
    )}
    for event in events:
        grouped[event.category].append(event)

    body = []
    serious = [event for event in events if event.severity != "low"]
    if phase == "runtime" and not serious:
        body.extend(["No serious runtime errors detected after server startup.", ""])

    body.extend([
        "OPTIONAL LOADER PROBES",
        f"Animation directory probes suppressed: {len(probe_details)}",
        f"Unique requested paths: {len({path for _, path, _ in probe_details})}",
    ])
    if probe_details:
        by_directory = Counter(directory.casefold() for directory, _, _ in probe_details)
        body.extend([
            f"AnimSets probes: {by_directory['animsets']}",
            f"actiongroups probes: {by_directory['actiongroups']}",
            f"Affected Workshop items: {len({workshop_id for _, _, workshop_id in probe_details})}",
        ])
    body.append("")

    for category in ("CRITICAL / HIGH", "DEPENDENCY / CONFIG", "ANIMATION / ASSET", "LOW / NOISE", "OTHER / WARNING"):
        category_events = grouped[category]
        body.append(f"{category} ({len(category_events)})")
        if not category_events:
            body.extend(["None.", ""])
            continue
        for event in category_events[:50]:
            body.append(f"Line {event.line_number} [{source_timestamp(event.line)}]: {event.line}")
            if category == "CRITICAL / HIGH":
                for context_line in event_context(event, lines)[1:]:
                    body.append(f"  {context_line}")
        if len(category_events) > 50:
            body.append(f"... {len(category_events) - 50} additional entries omitted from this section.")
        body.append("")

    if phase == "startup":
        common = Counter(normalize_message(event.line) for event in events)
        body.append("Most common errors")
        if common:
            for message, count in common.most_common(20):
                body.append(f"{count} x {message}")
        else:
            body.append("None.")
        body.append("")

    return "\n".join(header + body) + "\n"


def generate_reports(source: Path, requested: str = "all") -> list[Path]:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    marker_indexes = [index for index, line in enumerate(lines) if STARTED_MARKER in line]
    marker_index = marker_indexes[-1] if marker_indexes else None
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = report_stem(source)
    output = []

    if requested in ("all", "startup") or marker_index is None:
        startup_end = marker_index + 1 if marker_index is not None else len(lines)
        startup = REPORTS_DIR / f"{stem}-startup-errors.txt"
        startup.write_text(format_report(source, lines, "startup", 0, startup_end, marker_index), encoding="utf-8")
        output.append(startup)

    if marker_index is not None and requested in ("all", "runtime"):
        runtime = REPORTS_DIR / f"{stem}-runtime-errors.txt"
        runtime.write_text(format_report(source, lines, "runtime", marker_index, len(lines), marker_index), encoding="utf-8")
        output.append(runtime)

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Project Zomboid DebugLog-server files.")
    parser.add_argument("--log", type=Path, help="DebugLog-server.txt to audit")
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--startup", action="store_const", const="startup", dest="phase")
    phase.add_argument("--runtime", action="store_const", const="runtime", dest="phase")
    phase.add_argument("--all", action="store_const", const="all", dest="phase")
    parser.set_defaults(phase="all")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.log.expanduser() if args.log else latest_debug_log(read_env(ENV_FILE))
    if not source.is_file():
        raise RuntimeError(f"DebugLog-server file not found: {source}")
    reports = generate_reports(source, args.phase)
    for report in reports:
        print(f"Created report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"audit-server-log.py: {exc}", file=sys.stderr)
        raise SystemExit(1)
