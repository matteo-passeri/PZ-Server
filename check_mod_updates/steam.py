import json
import urllib.parse
import urllib.request

from .config import STEAM_DETAILS_URL


# ------------------------------------------------------------
# Steam Workshop remoto
# ------------------------------------------------------------

def steam_details(ids):
    result = {}
    batch_size = 50

    for offset in range(
        0,
        len(ids),
        batch_size,
    ):
        batch = ids[
            offset:offset + batch_size
        ]

        fields = {
            "itemcount": str(
                len(batch)
            ),
        }

        for index, workshop_id in enumerate(
            batch
        ):
            fields[
                f"publishedfileids[{index}]"
            ] = workshop_id

        body = urllib.parse.urlencode(
            fields
        ).encode(
            "ascii"
        )

        request = urllib.request.Request(
            STEAM_DETAILS_URL,
            data=body,
            headers={
                "User-Agent":
                    "pz-mod-update-check/4.0",
                "Content-Type":
                    "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=25,
        ) as response:
            payload = json.load(
                response
            )

        details = (
            payload
            .get(
                "response",
                {},
            )
            .get(
                "publishedfiledetails",
                [],
            )
        )

        for item in details:
            workshop_id = str(
                item.get(
                    "publishedfileid",
                    "",
                )
            ).strip()

            if workshop_id:
                result[
                    workshop_id
                ] = item

    return result


def find_updates(
    active_ids,
    remote,
    state,
):
    updates = []
    inaccessible = []

    previous_items = (
        state.get(
            "items",
            {},
        )
        if state
        else {}
    )

    for workshop_id in active_ids:
        info = remote.get(
            workshop_id
        )

        if not info:
            inaccessible.append(
                (
                    workshop_id,
                    "no response from Steam",
                )
            )
            continue

        result_code = int(
            info.get(
                "result",
                0,
            )
            or 0
        )

        if result_code != 1:
            inaccessible.append(
                (
                    workshop_id,
                    f"Steam result={result_code}",
                )
            )
            continue

        remote_time = int(
            info.get(
                "time_updated",
                0,
            )
            or 0
        )

        if remote_time <= 0:
            inaccessible.append(
                (
                    workshop_id,
                    "invalid remote time_updated",
                )
            )
            continue

        previous = previous_items.get(
            workshop_id
        )

        if previous is None:
            updates.append({
                "id": workshop_id,
                "title": info.get(
                    "title",
                    "(unnamed)",
                ),
                "old": None,
                "new": remote_time,
                "reason":
                    "new Workshop item",
            })
            continue

        try:
            old_time = int(
                previous.get(
                    "time_updated",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            old_time = 0

        if remote_time != old_time:
            updates.append({
                "id": workshop_id,
                "title": info.get(
                    "title",
                    "(unnamed)",
                ),
                "old": old_time,
                "new": remote_time,
                "reason":
                    "versione Steam cambiata",
            })

    return (
        updates,
        inaccessible,
    )
