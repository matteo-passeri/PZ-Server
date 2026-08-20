#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
ROOT_ENV_FILE = PROJECT_DIR / ".env"
COMPOSE_ENV_FILE = PROJECT_DIR / "docker-compose" / ".env"
SCRIPT_ENV_FILE = SCRIPT_DIR / ".env"


CONFIG_ENV_FILE = ROOT_ENV_FILE if ROOT_ENV_FILE.is_file() else SCRIPT_ENV_FILE
MANAGED_ENV_FILE = ROOT_ENV_FILE if ROOT_ENV_FILE.is_file() else COMPOSE_ENV_FILE

APP_ID = None
DEFAULT_COLLECTION_ID = None
COLLECTION_API = None
DETAILS_API = None
USER_AGENT = None
MANAGED_ENV_KEYS = None
BACKUPS_TO_KEEP = None
DEFAULT_WORKSHOP_ROOT = None
MOD_ID_OVERRIDES = None


class SteamAPIError(RuntimeError):
    pass


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f".env non trovato: {path}")

    result: dict[str, str] = {}

    for raw in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        line = raw.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in "\"'"
        ):
            value = value[1:-1]

        result[key.strip()] = value

    return result


def load_environment() -> dict[str, str]:
    if ROOT_ENV_FILE.is_file():
        return read_env(ROOT_ENV_FILE)

    env = read_env(COMPOSE_ENV_FILE)
    env.update(read_env(SCRIPT_ENV_FILE))
    return env


def required_env(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()

    if not value:
        raise RuntimeError(f"{key} non presente o vuoto in {CONFIG_ENV_FILE}")

    return value


def positive_int_env(env: dict[str, str], key: str) -> int:
    raw = required_env(env, key)

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{key} deve essere un intero positivo: {raw!r}"
        ) from exc

    if value <= 0:
        raise RuntimeError(f"{key} deve essere maggiore di zero: {value}")

    return value


def load_configuration() -> None:
    global APP_ID
    global DEFAULT_COLLECTION_ID
    global COLLECTION_API
    global DETAILS_API
    global USER_AGENT
    global MANAGED_ENV_KEYS
    global BACKUPS_TO_KEEP
    global DEFAULT_WORKSHOP_ROOT
    global MOD_ID_OVERRIDES

    env = load_environment()

    APP_ID = positive_int_env(env, "PZ_APP_ID")
    DEFAULT_COLLECTION_ID = required_env(env, "PZ_DEFAULT_COLLECTION_ID")
    COLLECTION_API = required_env(env, "PZ_COLLECTION_API")
    DETAILS_API = required_env(env, "PZ_DETAILS_API")
    USER_AGENT = required_env(env, "PZ_USER_AGENT")
    BACKUPS_TO_KEEP = positive_int_env(env, "PZ_BACKUPS_TO_KEEP")
    DEFAULT_WORKSHOP_ROOT = (
        Path(
            required_env(env, "PZ_DEDICATED_SERVER_DIR")
        ).expanduser()
        / "steamapps/workshop/content/108600"
    )

    managed_keys = tuple(
        key.strip()
        for key in required_env(env, "PZ_MANAGED_ENV_KEYS").split(",")
        if key.strip()
    )

    if not managed_keys:
        raise RuntimeError("PZ_MANAGED_ENV_KEYS non contiene variabili valide")

    MANAGED_ENV_KEYS = managed_keys

    try:
        overrides = json.loads(
            required_env(env, "PZ_MOD_ID_OVERRIDES")
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "PZ_MOD_ID_OVERRIDES deve contenere un oggetto JSON valido"
        ) from exc

    if not isinstance(overrides, dict):
        raise RuntimeError("PZ_MOD_ID_OVERRIDES deve essere un oggetto JSON")

    normalized_overrides: dict[str, list[str]] = {}

    for workshop_id, mod_ids in overrides.items():
        if not isinstance(workshop_id, str) or not workshop_id.isdigit():
            raise RuntimeError(
                "PZ_MOD_ID_OVERRIDES contiene un Workshop ID non valido: "
                f"{workshop_id!r}"
            )

        if (
            not isinstance(mod_ids, list)
            or not mod_ids
            or not all(isinstance(mod_id, str) and mod_id for mod_id in mod_ids)
        ):
            raise RuntimeError(
                "PZ_MOD_ID_OVERRIDES deve associare ogni Workshop ID "
                "a una lista non vuota di Mod ID"
            )

        normalized_overrides[workshop_id] = mod_ids

    MOD_ID_OVERRIDES = normalized_overrides


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Genera e aggiorna la configurazione mod di Project Zomboid da una collection Steam."
    )
    p.add_argument("collection_id", nargs="?", default=DEFAULT_COLLECTION_ID)
    p.add_argument("--output-dir", type=Path, default=Path("."))
    p.add_argument("--env-file", type=Path, default=MANAGED_ENV_FILE)
    p.add_argument("--strict", action="store_true", help="Exit 2 se trova problemi seri")
    p.add_argument("--no-env-update", action="store_true", help="Non modificare .env")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument(
        "--workshop-root",
        type=Path,
        default=DEFAULT_WORKSHOP_ROOT,
        help=(
            "Directory locale steamapps/workshop/content/108600 "
            "usata come fallback per leggere mod.info"
        ),
    )
    return p.parse_args()


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def prune_backups(path: Path, keep: int = BACKUPS_TO_KEEP) -> None:
    """Mantiene solo gli ultimi `keep` backup per il file indicato."""
    backups = sorted(
        path.parent.glob(f"{path.name}.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError as exc:
            print(
                f"ATTENZIONE: impossibile eliminare vecchio backup {old}: {exc}",
                file=sys.stderr,
            )


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.{stamp}.bak")

    shutil.copy2(path, dest)
    prune_backups(path)

    return dest


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def post_json(
    session: requests.Session,
    url: str,
    data: dict[str, str],
    attempts: int = 7,
) -> dict[str, Any]:
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            r = session.post(
                url,
                data=data,
                timeout=(15, 90),
            )

            if r.status_code == 429:
                delay = min(5 * attempt, 45)
                print(
                    f"Steam rate limit; nuovo tentativo tra {delay}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue

            r.raise_for_status()

            obj = r.json()

            if not isinstance(obj, dict):
                raise SteamAPIError("Risposta JSON non valida")

            return obj

        except (requests.RequestException, ValueError, SteamAPIError) as exc:
            last = exc

            if attempt == attempts:
                break

            delay = min(3 * attempt, 30)

            print(
                f"Errore temporaneo: {exc}; nuovo tentativo tra {delay}s...",
                file=sys.stderr,
            )

            time.sleep(delay)

    raise SteamAPIError(f"Richiesta Steam fallita: {last}")


def get_collection(
    session: requests.Session,
    collection_id: str,
) -> tuple[list[str], list[str]]:
    data = {
        "collectioncount": "1",
        "publishedfileids[0]": collection_id,
    }

    obj = post_json(
        session,
        COLLECTION_API,
        data,
    )

    details = obj.get(
        "response",
        {},
    ).get(
        "collectiondetails",
        [],
    )

    if not details:
        raise SteamAPIError("Collection non restituita da Steam")

    collection = details[0]

    if int(collection.get("result", 0)) != 1:
        raise SteamAPIError(
            f"Collection non accessibile, result={collection.get('result')}"
        )

    raw = [
        str(c.get("publishedfileid", "")).strip()
        for c in collection.get("children", [])
    ]

    raw = [
        x
        for x in raw
        if x
    ]

    counts = collections.Counter(raw)

    duplicates = [
        x
        for x, n in counts.items()
        if n > 1
    ]

    unique = list(dict.fromkeys(raw))

    return unique, duplicates


def get_details(
    session: requests.Session,
    ids: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]

        data = {
            "itemcount": str(len(batch))
        }

        for i, wid in enumerate(batch):
            data[f"publishedfileids[{i}]"] = wid

        obj = post_json(
            session,
            DETAILS_API,
            data,
        )

        rows = obj.get(
            "response",
            {},
        ).get(
            "publishedfiledetails",
            [],
        )

        if not isinstance(rows, list):
            raise SteamAPIError("Formato publishedfiledetails inatteso")

        out.extend(rows)

        print(
            f"Letti {min(start + len(batch), len(ids))}/{len(ids)} elementi"
        )

        time.sleep(1)

    return out


def clean_text(raw: str) -> str:
    text = html.unescape(raw or "")

    text = re.sub(
        r"\[/?[^\]]+\]",
        "\n",
        text,
    )

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def extract_values(
    labels: list[str],
    description: str,
) -> list[str]:
    label_re = "|".join(
        re.escape(x)
        for x in labels
    )

    pattern = re.compile(
        rf"^\s*(?:{label_re})\s*:\s*(.+?)\s*$",
        re.I | re.M,
    )

    out: list[str] = []

    for match in pattern.findall(description):
        for part in re.split(
            r"\s*[;|]\s*",
            match,
        ):
            value = html.unescape(part).strip(
                " \t,;|"
            )

            if value and value not in out:
                out.append(value)

    return out



def read_mod_id_from_info(path: Path) -> str | None:
    """Legge il primo id= valido da un file mod.info."""
    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return None

    for raw in lines:
        line = raw.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split("=", 1)

        if key.strip().lower() != "id":
            continue

        mod_id = value.strip()

        if (
            not mod_id
            or ";" in mod_id
            or "\n" in mod_id
            or len(mod_id) > 200
        ):
            return None

        return mod_id

    return None


def mod_info_rank(
    path: Path,
    mod_root: Path,
) -> tuple[int, str]:
    """
    Preferenza per B42.20:
      0 -> .../42.20/mod.info
      1 -> .../42/mod.info
      2 -> .../mod.info non versionato
      3 -> altre directory 42.x
      4 -> tutto il resto (es. 41)
    """
    try:
        rel = path.relative_to(mod_root)
    except ValueError:
        return (99, str(path))

    parts = rel.parts[:-1]

    if "42.20" in parts:
        rank = 0
    elif "42" in parts:
        rank = 1
    elif not parts:
        rank = 2
    elif any(
        re.fullmatch(r"42(?:\.\d+)+", part)
        for part in parts
    ):
        rank = 3
    else:
        rank = 4

    return (rank, str(rel))


def extract_local_mod_ids(
    workshop_root: Path,
    workshop_id: str,
) -> list[str]:
    """
    Ricava i Mod ID dai mod.info locali di un Workshop item.

    Ogni directory mods/<nome-mod> viene trattata separatamente,
    così un Workshop item che contiene più mod continua a produrre
    più Mod ID. Per ciascun mod viene scelta una sola variante,
    preferendo 42.20, poi 42, poi quella non versionata.
    """
    item_root = workshop_root / workshop_id
    mods_root = item_root / "mods"

    if not mods_root.is_dir():
        return []

    out: list[str] = []

    for mod_root in sorted(
        p
        for p in mods_root.iterdir()
        if p.is_dir()
    ):
        candidates = sorted(
            mod_root.rglob("mod.info"),
            key=lambda p: mod_info_rank(
                p,
                mod_root,
            ),
        )

        if not candidates:
            continue

        best_rank = mod_info_rank(
            candidates[0],
            mod_root,
        )[0]

        # Se esistono solo varianti incompatibili/non riconosciute
        # (tipicamente B41), non le usiamo come fallback automatico.
        if best_rank >= 4:
            continue

        mod_id = read_mod_id_from_info(
            candidates[0]
        )

        if mod_id and mod_id not in out:
            out.append(mod_id)

    return out


def suspicious_build(
    title: str,
    description: str,
) -> list[str]:
    text = f"{title}\n{description}".lower()

    warnings: list[str] = []

    b41 = any(
        x in text
        for x in (
            "build 41 only",
            "b41 only",
            "for build 41",
            "41 only",
        )
    )

    b42 = any(
        x in text
        for x in (
            "build 42",
            "b42",
            "42 stable",
        )
    )

    if b41 and not b42:
        warnings.append(
            "sembra destinata esclusivamente a Build 41"
        )

    if (
        "obsolete" in title.lower()
        or "deprecated" in title.lower()
    ):
        warnings.append(
            "titolo marcato obsolete/deprecated"
        )

    return warnings


def read_previous_json(
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        obj = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return obj if isinstance(obj, dict) else None

    except (OSError, ValueError):
        return None


def dotenv_quote(value: str) -> str:
    return '"' + value.replace(
        "\\",
        "\\\\",
    ).replace(
        '"',
        '\\"',
    ) + '"'


def update_env_file(
    path: Path,
    values: dict[str, str],
    make_backup: bool,
) -> Path | None:
    backup = (
        backup_file(path)
        if make_backup
        else None
    )

    existing = (
        path.read_text(
            encoding="utf-8"
        ).splitlines()
        if path.exists()
        else []
    )

    filtered = [
        line
        for line in existing
        if not any(
            line.startswith(k + "=")
            for k in MANAGED_ENV_KEYS
        )
    ]

    filtered_text = "\n".join(filtered).rstrip()

    managed = "\n".join(
        f"{k}={dotenv_quote(values[k])}"
        for k in MANAGED_ENV_KEYS
    )

    content = (
        (filtered_text + "\n\n")
        if filtered_text
        else ""
    ) + managed + "\n"

    atomic_write(
        path,
        content,
    )

    try:
        path.chmod(0o600)
    except OSError:
        pass

    return backup


def main() -> int:
    load_configuration()
    args = parse_args()

    if not str(args.collection_id).isdigit():
        print(
            "ERRORE: collection_id deve essere numerico",
            file=sys.stderr,
        )
        return 1

    outdir = (
        args.output_dir
        .expanduser()
        .resolve()
    )

    env_path = args.env_file.expanduser()

    if not env_path.is_absolute():
        env_path = (
            Path.cwd()
            / env_path
        ).resolve()

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    workshop_root = (
        args.workshop_root
        .expanduser()
        .resolve()
    )

    if workshop_root.is_dir():
        print(
            f"Workshop locale fallback: {workshop_root}"
        )
    else:
        print(
            "ATTENZIONE: Workshop locale fallback non disponibile: "
            f"{workshop_root}",
            file=sys.stderr,
        )

    json_path = (
        outdir
        / "project-zomboid-mods.json"
    )

    env_generated_path = (
        outdir
        / "project-zomboid-mods.env"
    )

    report_path = (
        outdir
        / "project-zomboid-mods-report.txt"
    )

    compose_path = (
        outdir
        / "project-zomboid-mods-compose.yml"
    )

    previous = read_previous_json(
        json_path
    )

    session = requests.Session()

    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html",
    })

    print(
        f"Lettura collection Steam {args.collection_id}..."
    )

    (
        collection_ids,
        duplicate_workshop_ids,
    ) = get_collection(
        session,
        str(args.collection_id),
    )

    print(
        f"Workshop Item unici nella collection: {len(collection_ids)}"
    )

    details = get_details(
        session,
        collection_ids,
    )

    by_id = {
        str(
            d.get(
                "publishedfileid",
                "",
            )
        ).strip(): d
        for d in details
    }

    workshop_ids: list[str] = []
    mod_ids: list[str] = []
    map_names: list[str] = []

    removed: list[str] = []
    missing_mod_id: list[dict[str, str]] = []
    wrong_app: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    malformed: list[dict[str, str]] = []
    records: list[dict[str, Any]] = []

    mod_owners: dict[
        str,
        list[dict[str, str]],
    ] = collections.defaultdict(list)

    map_owners: dict[
        str,
        list[dict[str, str]],
    ] = collections.defaultdict(list)

    for wid in collection_ids:
        d = by_id.get(wid)

        if (
            not d
            or int(
                d.get(
                    "result",
                    0,
                )
                or 0
            ) != 1
            or not str(
                d.get(
                    "title",
                    "",
                )
            ).strip()
        ):
            removed.append(wid)
            continue

        title = str(
            d.get(
                "title",
                "",
            )
        ).strip()

        app_id = int(
            d.get(
                "consumer_app_id",
                0,
            )
            or 0
        )

        if app_id != APP_ID:
            wrong_app.append({
                "workshop_id": wid,
                "title": title,
                "consumer_app_id": app_id,
            })
            continue

        desc = clean_text(
            str(
                d.get(
                    "description",
                    "",
                )
                or ""
            )
        )

        mids = extract_values(
            [
                "Mod ID",
                "ModID",
            ],
            desc,
        )

        # Fallback manuale:
        # se Steam non espone un Mod ID leggibile nella descrizione,
        # usa gli override definiti a inizio script.
        if (
            not mids
            and wid in MOD_ID_OVERRIDES
        ):
            mids = list(
                MOD_ID_OVERRIDES[wid]
            )

            print(
                f"Override Mod ID applicato: "
                f"{wid} ({title}) -> "
                f"{', '.join(mids)}"
            )

        # Fallback locale:
        # alcuni Workshop item (es. Proper Pickaxe) non pubblicano
        # "Mod ID:" nella descrizione Steam, ma hanno un mod.info valido.
        if (
            not mids
            and workshop_root.is_dir()
        ):
            local_mids = extract_local_mod_ids(
                workshop_root,
                wid,
            )

            if local_mids:
                mids = local_mids

                print(
                    f"Mod ID letto da mod.info locale: "
                    f"{wid} ({title}) -> "
                    f"{', '.join(mids)}"
                )

        maps = extract_values(
            [
                "Map Folder",
                "Map Folder Name",
                "Map Name",
            ],
            desc,
        )

        valid_mids: list[str] = []
        valid_maps: list[str] = []

        for mid in mids:
            if (
                ";" in mid
                or "\n" in mid
                or len(mid) > 200
                or mid.startswith(
                    (
                        "http://",
                        "https://",
                    )
                )
            ):
                malformed.append({
                    "workshop_id": wid,
                    "title": title,
                    "type": "Mod ID",
                    "value": mid,
                })
            else:
                valid_mids.append(mid)

                mod_owners[mid].append({
                    "workshop_id": wid,
                    "title": title,
                })

        for m in maps:
            if (
                ";" in m
                or "\n" in m
                or len(m) > 200
            ):
                malformed.append({
                    "workshop_id": wid,
                    "title": title,
                    "type": "Map",
                    "value": m,
                })
            else:
                valid_maps.append(m)

                map_owners[m].append({
                    "workshop_id": wid,
                    "title": title,
                })

        warnings = suspicious_build(
            title,
            desc,
        )

        if warnings:
            suspicious.append({
                "workshop_id": wid,
                "title": title,
                "warnings": warnings,
            })

        if not valid_mids:
            missing_mod_id.append({
                "workshop_id": wid,
                "title": title,
            })

        workshop_ids.append(wid)

        for x in valid_mids:
            if x not in mod_ids:
                mod_ids.append(x)

        for x in valid_maps:
            if x not in map_names:
                map_names.append(x)

        records.append({
            "workshop_id": wid,
            "title": title,
            "mod_ids": valid_mids,
            "map_names": valid_maps,
            "time_created": d.get("time_created"),
            "time_updated": d.get("time_updated"),
        })

    duplicate_mod_ids = {
        k: v
        for k, v in mod_owners.items()
        if len(
            {
                x["workshop_id"]
                for x in v
            }
        ) > 1
    }

    duplicate_maps = {
        k: v
        for k, v in map_owners.items()
        if len(
            {
                x["workshop_id"]
                for x in v
            }
        ) > 1
    }

    final_maps = list(
        map_names
    )

    if "Muldraugh, KY" not in final_maps:
        final_maps.append(
            "Muldraugh, KY"
        )

    prev_workshop = (
        set(
            previous.get(
                "workshop_ids",
                [],
            )
        )
        if previous
        else set()
    )

    prev_mods = (
        set(
            previous.get(
                "mod_ids",
                [],
            )
        )
        if previous
        else set()
    )

    changes = {
        "added_workshop_ids": sorted(
            set(workshop_ids)
            - prev_workshop
        ),
        "removed_workshop_ids": sorted(
            prev_workshop
            - set(workshop_ids)
        ),
        "added_mod_ids": sorted(
            set(mod_ids)
            - prev_mods
        ),
        "removed_mod_ids": sorted(
            prev_mods
            - set(mod_ids)
        ),
    }

    generated = now_utc()

    result = {
        "generated_at_utc": generated,
        "collection_id": str(args.collection_id),
        "workshop_ids": workshop_ids,
        "mod_ids": mod_ids,
        "map_names": final_maps,
        "records": records,
        "duplicate_workshop_ids_in_collection": duplicate_workshop_ids,
        "duplicate_mod_ids": duplicate_mod_ids,
        "duplicate_map_names": duplicate_maps,
        "removed_or_inaccessible_items": removed,
        "missing_mod_id_items": missing_mod_id,
        "wrong_app_items": wrong_app,
        "suspicious_build_items": suspicious,
        "malformed_values": malformed,
        "changes_since_previous_run": changes,
    }

    env_values = {
        "PZ_MOD_IDS": ";".join(
            workshop_ids
        ),
        "PZ_MOD_NAMES": ";".join(
            mod_ids
        ),
        "PZ_MAP_NAMES": ";".join(
            final_maps
        ),
    }

    generated_env = "\n".join([
        "# Generato automaticamente da generate-mod-list.py",
        f"# Collection Steam: {args.collection_id}",
        f"# Generato UTC: {generated}",
        *(
            f"{k}={dotenv_quote(v)}"
            for k, v in env_values.items()
        ),
        "",
    ])

    report: list[str] = [
        "PROJECT ZOMBOID MOD COLLECTION REPORT",
        "=" * 38,
        "",
        f"Generato UTC: {generated}",
        f"Collection: {args.collection_id}",
        f"Workshop validi: {len(workshop_ids)}",
        f"Mod ID unici: {len(mod_ids)}",
        f"Mappe moddate: {len(map_names)}",
        f"Rimossi/non accessibili: {len(removed)}",
        f"Senza Mod ID: {len(missing_mod_id)}",
        f"Mod ID duplicati: {len(duplicate_mod_ids)}",
        f"Mappe duplicate: {len(duplicate_maps)}",
        "",
        "CAMBIAMENTI DALLA PRECEDENTE ESECUZIONE",
        "-" * 39,
        (
            "Workshop aggiunti: "
            + (
                ", ".join(
                    changes[
                        "added_workshop_ids"
                    ]
                )
                or "Nessuno"
            )
        ),
        (
            "Workshop rimossi: "
            + (
                ", ".join(
                    changes[
                        "removed_workshop_ids"
                    ]
                )
                or "Nessuno"
            )
        ),
        (
            "Mod ID aggiunti: "
            + (
                ", ".join(
                    changes[
                        "added_mod_ids"
                    ]
                )
                or "Nessuno"
            )
        ),
        (
            "Mod ID rimossi: "
            + (
                ", ".join(
                    changes[
                        "removed_mod_ids"
                    ]
                )
                or "Nessuno"
            )
        ),
        "",
    ]

    def section(
        title: str,
        lines: list[str],
    ) -> None:
        report.extend([
            title,
            "-" * len(title),
        ])

        report.extend(
            lines or ["Nessuno"]
        )

        report.append("")

    section(
        "ELEMENTI RIMOSSI O NON ACCESSIBILI",
        removed,
    )

    section(
        "ELEMENTI SENZA MOD ID",
        [
            f'{x["workshop_id"]}: {x["title"]}'
            for x in missing_mod_id
        ],
    )

    section(
        "MOD ID DUPLICATI",
        [
            (
                f"{mid}: "
                + ", ".join(
                    f'{o["workshop_id"]} ({o["title"]})'
                    for o in owners
                )
            )
            for mid, owners
            in duplicate_mod_ids.items()
        ],
    )

    section(
        "MAPPE DUPLICATE",
        [
            (
                f"{name}: "
                + ", ".join(
                    f'{o["workshop_id"]} ({o["title"]})'
                    for o in owners
                )
            )
            for name, owners
            in duplicate_maps.items()
        ],
    )

    section(
        "POSSIBILI MOD B41/OBSOLETE",
        [
            (
                f'{x["workshop_id"]}: '
                f'{x["title"]} — '
                f'{"; ".join(x["warnings"])}'
            )
            for x in suspicious
        ],
    )

    section(
        "VALORI MALFORMATI",
        [
            (
                f'{x["workshop_id"]}: '
                f'{x["title"]} — '
                f'{x["type"]}={x["value"]}'
            )
            for x in malformed
        ],
    )

    for path in (
        json_path,
        env_generated_path,
        report_path,
        compose_path,
    ):
        if (
            path.exists()
            and not args.no_backup
        ):
            backup_file(path)

    atomic_write(
        json_path,
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )

    atomic_write(
        env_generated_path,
        generated_env,
    )

    atomic_write(
        report_path,
        "\n".join(report)
        + "\n",
    )

    atomic_write(
        compose_path,
        'MOD_IDS: "${PZ_MOD_IDS}"\n'
        'MOD_NAMES: "${PZ_MOD_NAMES}"\n'
        'MAP_NAMES: "${PZ_MAP_NAMES}"\n',
    )

    env_backup = None

    if not args.no_env_update:
        env_backup = update_env_file(
            env_path,
            env_values,
            not args.no_backup,
        )

    print(
        "\nGenerazione completata:"
    )

    print(
        f"  JSON:    {json_path}"
    )

    print(
        f"  ENV:     {env_generated_path}"
    )

    print(
        f"  REPORT:  {report_path}"
    )

    print(
        f"  COMPOSE: {compose_path}"
    )

    if not args.no_env_update:
        print(
            f"  .env:    {env_path} aggiornato"
        )

        if env_backup:
            print(
                f"  backup:  {env_backup}"
            )

    print(
        f"\nWorkshop validi: {len(workshop_ids)}"
    )

    print(
        f"Mod ID unici: {len(mod_ids)}"
    )

    print(
        f"Rimossi/non accessibili: {len(removed)}"
    )

    print(
        f"Senza Mod ID: {len(missing_mod_id)}"
    )

    print(
        f"Mod ID duplicati: {len(duplicate_mod_ids)}"
    )

    serious = bool(
        removed
        or missing_mod_id
        or duplicate_mod_ids
        or malformed
    )

    if (
        args.strict
        and serious
    ):
        print(
            "Modalità strict: rilevati problemi da correggere.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:
        print(
            "\nInterrotto.",
            file=sys.stderr,
        )

        raise SystemExit(130)

    except Exception as exc:
        print(
            f"ERRORE: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1)
