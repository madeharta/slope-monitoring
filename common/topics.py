"""MQTT topic scheme (context.md §6): slope/{site_id}/{device_id}/data.

Consumers subscribe with the wildcard so adding a device needs no
server-side change.
"""

from __future__ import annotations

SUBSCRIBE_ALL = "slope/+/+/data"


def build_topic(site_id: str, device_id: str) -> str:
    for part, name in ((site_id, "site_id"), (device_id, "device_id")):
        if not part or "/" in part or "+" in part or "#" in part:
            raise ValueError(f"invalid {name}: {part!r}")
    return f"slope/{site_id}/{device_id}/data"


def parse_topic(topic: str) -> tuple[str, str]:
    """Return (site_id, device_id) from a concrete data topic, or raise
    ValueError. A received topic must be concrete — wildcards ('+', '#')
    are rejected rather than returned as ids."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "slope" or parts[3] != "data":
        raise ValueError(f"not a slope data topic: {topic!r}")
    site_id, device_id = parts[1], parts[2]
    for part, name in ((site_id, "site_id"), (device_id, "device_id")):
        if not part or "+" in part or "#" in part:
            raise ValueError(f"invalid {name} segment in topic: {topic!r}")
    return site_id, device_id
