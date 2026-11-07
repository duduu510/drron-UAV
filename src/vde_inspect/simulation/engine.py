"""Replay minutes and SOC from actual events; never synthesize geometry.

Events are ordered by (start_min, end_min, event_id). Before a device's
first event it is absent; after an event it holds its final state. At a
shared boundary a newly starting event takes precedence. Zero-duration
events complete immediately. Overlaps have a stable latest-start ordering;
the independent validator reports them as invalid schedules.
"""
from copy import deepcopy
import math


def _number(value, field, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是有限数值")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{field} 数值超出范围")
    return value


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value


def validate_events(events):
    """Return a detached event list, rejecting ambiguous IDs and invalid units."""
    if not isinstance(events, list):
        raise ValueError("events 必须是数组")
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("事件必须是对象")
        for field in ("event_id", "device_id", "event_type", "from_node_id", "to_node_id"):
            _identifier(event.get(field), field)
        if event["event_id"] in seen:
            raise ValueError(f"重复 event_id: {event['event_id']}")
        seen.add(event["event_id"])
        start = _number(event.get("start_min"), "start_min")
        end = _number(event.get("end_min"), "end_min")
        if end < start:
            raise ValueError("end_min 不得早于 start_min")
        for field in ("soc_start", "soc_end"):
            _number(event.get(field), field, maximum=100)
        if "task_id" in event:
            _identifier(event["task_id"], "task_id")
        if "task_ids" in event:
            if not isinstance(event["task_ids"], list):
                raise ValueError("task_ids 必须是数组")
            for task_id in event["task_ids"]:
                _identifier(task_id, "task_ids")
    return deepcopy(events)


class PlaybackEngine:
    def __init__(self, events: list[dict]):
        self._events = sorted(validate_events(events), key=lambda e: (
            e["start_min"], e["end_min"], e["event_id"]))

    def seek(self, minutes: float) -> dict:
        """Reconstruct independently of previous seeks, returning detached states."""
        _number(minutes, "minutes")
        states = {}
        for event in self._events:
            if event["start_min"] > minutes:
                break
            duration = event["end_min"] - event["start_min"]
            progress = min(1.0, (minutes - event["start_min"]) / duration) if duration else 1.0
            complete = minutes >= event["end_min"]
            state = deepcopy(event)
            state.update(
                status="completed" if complete else "active",
                progress=progress,
                soc=event["soc_end"] if complete else (
                    event["soc_start"] + (event["soc_end"] - event["soc_start"]) * progress),
                node_id=event["to_node_id"] if complete else (
                    event["from_node_id"] if progress == 0 else None),
            )
            states[event["device_id"]] = state
        return dict(sorted(states.items()))
