import copy
import math

import pytest

from vde_inspect.services.tasks import generate_tasks


def project(direction='both'):
    return {'stations': [{'id': 'A', 'service_allowed': True}, {'id': 'B', 'service_allowed': False}],
            'segments': [{'id': 'S', 'start_station_id': 'A', 'end_station_id': 'B',
                          'length_km': 2.5, 'direction': direction}]}


def test_split_preserves_direction_length_mapping_and_never_services_virtual_nodes():
    source = project()
    before = copy.deepcopy(source)
    tasks = generate_tasks(source, 1)
    assert source == before
    assert len(tasks) == 6
    assert len({t['id'] for t in tasks}) == 6
    for direction, start, end in [('forward', 'A', 'B'), ('reverse', 'B', 'A')]:
        directed = [t for t in tasks if t['direction'] == direction]
        assert math.fsum(t['length_km'] for t in directed) == pytest.approx(2.5)
        assert all(0 < t['length_km'] <= 1 and t['segment_id'] == 'S' for t in directed)
        assert directed[0]['start_node_id'] == start
        assert directed[-1]['end_node_id'] == end
        for left, right in zip(directed, directed[1:]):
            assert left['end_node_id'] == right['start_node_id']
            assert left['end_service_allowed'] is False
            assert right['start_service_allowed'] is False
    forward = [t for t in tasks if t['direction'] == 'forward']
    reverse = [t for t in tasks if t['direction'] == 'reverse']
    assert forward[0]['start_service_allowed'] is True
    assert reverse[-1]['end_service_allowed'] is True
    assert reverse[0]['start_service_allowed'] is False
    assert forward[0]['end_node_id'] == reverse[-1]['start_node_id']
    assert len({task['physical_task_id'] for task in tasks}) == 3
    for left, right in zip(forward, reversed(reverse)):
        assert left['physical_task_id'] == right['physical_task_id']
        assert left['length_km'] == right['length_km']
    assert generate_tasks(source, 1) == tasks


def test_physical_group_identity_is_independent_of_allowed_direction():
    both = generate_tasks(project('both'), 1)
    reverse = generate_tasks(project('reverse'), 1)
    assert {task['physical_task_id'] for task in both} == {task['physical_task_id'] for task in reverse}


@pytest.mark.parametrize('limit', [0, -1, float('inf'), float('nan'), True, '1'])
def test_invalid_limit_rejected(limit):
    with pytest.raises(ValueError):
        generate_tasks(project(), limit)


def test_unsplit_reverse_and_unknown_station():
    task, = generate_tasks(project('reverse'), 3)
    assert task['start_node_id'] == 'B'
    assert task['end_node_id'] == 'A'
    assert task['length_km'] == 2.5
    bad = project()
    bad['segments'][0]['end_station_id'] = 'unknown'
    with pytest.raises(ValueError):
        generate_tasks(bad, 1)


def test_very_short_segment_still_generates_one_task():
    source = project('forward')
    source['segments'][0]['length_km'] = 1e-300
    task, = generate_tasks(source, 1e300)
    assert task['length_km'] == 1e-300


def test_excessive_subdivision_is_rejected_before_allocation():
    with pytest.raises(ValueError):
        generate_tasks(project(), 1e-12)


def test_decimal_roundoff_does_not_exceed_task_length_limit():
    source = project('forward')
    source['segments'][0]['length_km'] = 1.2
    tasks = generate_tasks(source, .1)
    assert all(t['length_km'] <= .1 for t in tasks)
    assert math.fsum(t['length_km'] for t in tasks) == pytest.approx(1.2)
