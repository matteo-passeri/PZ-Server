import json
from datetime import datetime

from . import config


# ------------------------------------------------------------
# Stato persistente
# ------------------------------------------------------------

def load_state():
    if not config.STATE_FILE.is_file():
        return None

    try:
        payload = json.loads(
            config.STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            f"Impossibile leggere {config.STATE_FILE}: {exc}"
        )

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Formato stato non valido: {config.STATE_FILE}"
        )

    items = payload.get(
        "items",
        {},
    )

    if not isinstance(items, dict):
        raise RuntimeError(
            f"Formato items non valido: {config.STATE_FILE}"
        )

    return payload


def save_state(
    remote_items,
    active_ids,
):
    items = {}

    for workshop_id in active_ids:
        info = remote_items.get(
            workshop_id
        )

        if not info:
            continue

        result_code = int(
            info.get(
                "result",
                0,
            )
            or 0
        )

        if result_code != 1:
            continue

        remote_time = int(
            info.get(
                "time_updated",
                0,
            )
            or 0
        )

        if remote_time <= 0:
            continue

        items[workshop_id] = {
            "time_updated": remote_time,
            "title": info.get(
                "title",
                "(senza nome)",
            ),
        }

    payload = {
        "updated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "items": items,
    }

    tmp = config.STATE_FILE.with_suffix(
        config.STATE_FILE.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    tmp.replace(
        config.STATE_FILE
    )
