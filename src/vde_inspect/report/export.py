"""Export actual event records, including extension fields, without fake rows."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile

from vde_inspect.solver.adapter import get_solution_events, validate_envelope


EVENT_COLUMNS = ("event_id", "device_id", "event_type", "start_min", "end_min",
                 "soc_start", "soc_end", "from_node_id", "to_node_id")


def _events(solution):
    events = get_solution_events(solution)
    # Check all extension values too, before any file replacement.
    json.dumps(events, ensure_ascii=False, allow_nan=False)
    return events


def _atomic_text(path, text, encoding):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline="",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def export_events_json(solution: dict, path: Path) -> Path:
    events = _events(solution)
    return _atomic_text(path, json.dumps(events, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8")


def export_solution_json(solution: dict, path: Path) -> Path:
    """Export a reloadable full snapshot with source IDs and canonical events.

    Validation and serialization precede atomic replacement. Legacy event
    aliases are normalized only in the exported copy; the source stays intact.
    This is an artifact export, never an approval or operational publication.
    """
    validate_envelope(solution)
    payload = dict(solution)
    payload["schedule_events"] = get_solution_events(solution)
    payload.pop("events", None)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return _atomic_text(path, serialized, "utf-8")


def export_events_csv(solution: dict, path: Path) -> Path:
    events = _events(solution)
    extra = sorted({key for event in events for key in event} - set(EVENT_COLUMNS))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=[*EVENT_COLUMNS, *extra])
    writer.writeheader()
    for event in events:
        writer.writerow({key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                         if isinstance(value, (dict, list)) else value for key, value in event.items()})
    return _atomic_text(path, output.getvalue(), "utf-8-sig")
