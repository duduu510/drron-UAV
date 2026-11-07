import copy

import pytest

from vde_inspect.simulation.engine import PlaybackEngine


def event(event_id="e1", start=5, end=15, **kwargs):
    result = dict(event_id=event_id, device_id="v1", event_type="travel",
                  start_min=start, end_min=end, soc_start=100, soc_end=80,
                  from_node_id="a", to_node_id="b")
    result.update(kwargs)
    return result


def test_seek_boundaries_soc_and_no_invented_geometry():
    engine = PlaybackEngine([event()])
    assert engine.seek(0) == {}
    assert engine.seek(5)["v1"]["soc"] == 100
    state = engine.seek(10)["v1"]
    assert state["soc"] == 90
    assert state["progress"] == 0.5
    assert state["status"] == "active"
    assert state["node_id"] is None
    assert "x" not in state and "y" not in state
    assert engine.seek(15)["v1"]["node_id"] == "b"
    assert engine.seek(20)["v1"]["status"] == "completed"
    assert engine.seek(10) == {"v1": state}


def test_order_is_deterministic_and_same_time_next_event_wins():
    first = event()
    second = event("e2", 15, 20, from_node_id="b", to_node_id="c", soc_start=80, soc_end=70)
    engine = PlaybackEngine([second, first])
    assert engine.seek(15)["v1"]["event_id"] == "e2"
    assert engine.seek(17.5) == PlaybackEngine([first, second]).seek(17.5)
    first["soc_start"] = 0
    state = engine.seek(10)
    state["v1"]["soc"] = -99
    assert engine.seek(10)["v1"]["soc"] == 90


def test_zero_duration_event_is_completed_at_start():
    assert PlaybackEngine([event(start=5, end=5)]).seek(5)["v1"]["soc"] == 80


@pytest.mark.parametrize("field,value", [
    ("start_min", -1), ("end_min", 1), ("end_min", float("inf")),
    ("soc_start", -1), ("soc_end", 101), ("soc_end", float("nan")),
    ("start_min", True), ("end_min", "15"), ("event_id", ""),
])
def test_reject_invalid_events(field, value):
    data = event()
    data[field] = value
    with pytest.raises(ValueError):
        PlaybackEngine([data])


def test_duplicate_event_ids_rejected():
    data = event()
    with pytest.raises(ValueError):
        PlaybackEngine([data, copy.deepcopy(data)])


@pytest.mark.parametrize("time", [-1, float("nan"), float("inf"), True, "10"])
def test_reject_invalid_seek(time):
    with pytest.raises(ValueError):
        PlaybackEngine([]).seek(time)
