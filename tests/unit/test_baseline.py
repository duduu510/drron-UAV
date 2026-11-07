import copy

import pytest

from vde_inspect.solver.baseline import normalize_config, prepare_baseline_project, solve_baseline


def source():
    return {'project_id': 'source', 'name': 'Tiny',
            'lines': [{'id': 'L', 'name': 'Line', 'color': '#000000'}],
            'stations': [{'id': key, 'name': key, 'line_id': 'L', 'service_allowed': False,
                          'x': i, 'y': 0} for i, key in enumerate(('A', 'B'))],
            'segments': [{'id': 'S', 'line_id': 'L', 'start_station_id': 'A',
                          'end_station_id': 'B', 'length_km': 1, 'direction': 'both'}]}


def config(**changes):
    return dict(depot_station_id='A', assume_service_at_all_stations=True,
                team_count=1, max_length_km=1, drone_speed_kmh=60,
                vehicle_speed_kmh=60, **changes)


def test_hand_calculated_station_return_soc_cost_and_directions():
    p = prepare_baseline_project(source(), config())
    updates = []
    s = solve_baseline(p, config(), progress=updates.append)
    assert s['complete'] is True
    assert s['return_time_min'] == pytest.approx(3)
    assert s['cost_breakdown_yuan'] == dict(vehicle_fixed=400, drone_fixed=50,
                                         vehicle_time=3, vehicle_distance=0, battery_swap=0)
    assert s['cost_total_yuan'] == pytest.approx(453)
    assert len(s['sorties']) == 1
    inspect, = [e for e in s['schedule_events'] if e['event_type'] == 'inspect']
    assert inspect['task_ids'] == [p['tasks'][0]['id']]
    drone_events = [e for e in s['schedule_events'] if e['device_id'] == p['drones'][0]['id']]
    assert drone_events[-1]['soc_end'] == pytest.approx(92.5)
    assert all(e['end_min'] > e['start_min'] for e in s['schedule_events'])
    assert updates[-1]['processed'] == updates[-1]['total'] == updates[-1]['completed'] == 1
    again = solve_baseline(p, config())
    assert again['run_id'] != s['run_id']
    assert again['schedule_events'] == s['schedule_events']


def test_preparation_detaches_provenance_and_never_enables_virtual_service():
    raw = source()
    before = copy.deepcopy(raw)
    cfg = config()
    cfg['max_length_km'] = .4
    p = prepare_baseline_project(raw, cfg)
    assert raw == before
    assert p['project_id'] != raw['project_id']
    assert p['name'] == 'Tiny｜仿真基线'
    for task in p['tasks']:
        for side in ('start', 'end'):
            if task[f'{side}_node_id'].startswith('virtual:'):
                assert task[f'{side}_service_allowed'] is False


def test_window_partial_has_no_complete_total():
    cfg = config(window_min=1)
    s = solve_baseline(prepare_baseline_project(source(), cfg), cfg)
    assert not s['complete']
    assert s['unscheduled_tasks']
    assert 'cost_total_yuan' not in s
    assert s['cost_partial_yuan'] == 0


def test_disconnected_graph_rejected():
    raw = source()
    raw['stations'].append(dict(id='C', name='C', line_id='L', service_allowed=False))
    with pytest.raises(ValueError, match='connect'):
        prepare_baseline_project(raw, config())


@pytest.mark.parametrize('change', [dict(assume_service_at_all_stations=False),
    dict(team_count=True), dict(seed=-1), dict(drone_speed_kmh=float('nan')),
    dict(vehicle_min_soc=100), dict(swap_stock=1.2)])
def test_configuration_rejects_invalid_assumptions(change):
    cfg = config()
    cfg.update(change)
    with pytest.raises(ValueError):
        normalize_config(cfg)


def test_unprepared_input_rejected():
    with pytest.raises(ValueError):
        solve_baseline(source(), config())


def test_ground_proxy_path_return_soc_and_elapsed_time_cost():
    raw = source()
    raw['stations'].append(dict(id='C', name='C', line_id='L', service_allowed=False))
    raw['segments'][0]['length_km'] = .1
    raw['segments'].append(dict(id='T', line_id='L', start_station_id='B',
                                end_station_id='C', length_km=1, direction='both'))
    cfg = config()
    p = prepare_baseline_project(raw, cfg)
    s = solve_baseline(p, cfg)
    assert s['complete']
    assert s['return_time_min'] == pytest.approx(4.4)
    assert s['cost_total_yuan'] == pytest.approx(454.7)
    drives = [e for e in s['schedule_events'] if e['event_type'] == 'drive']
    assert [e['path_node_ids'] for e in drives] == [['A', 'B'], ['B', 'A']]
    assert drives[-1]['soc_end'] == pytest.approx(99.8)
    for drive in drives:
        ride, = [e for e in s['schedule_events'] if e['event_type'] == 'ride'
                 and e['start_min'] == drive['start_min']]
        assert ride['end_min'] == drive['end_min']
        assert ride['soc_start'] == ride['soc_end']


def test_battery_swap_stock_time_and_cost_are_real_constraints():
    raw = source()
    raw['segments'].append(dict(raw['segments'][0], id='T'))
    cfg = config(drone_endurance_min=5, swap_stock=1)
    p = prepare_baseline_project(raw, cfg)
    s = solve_baseline(p, cfg)
    assert s['complete']
    assert s['return_time_min'] == pytest.approx(8)
    assert s['cost_total_yuan'] == pytest.approx(464)
    swap, = [e for e in s['schedule_events'] if e['event_type'] == 'swap']
    assert swap['soc_start'] == pytest.approx(40)
    assert swap['soc_end'] == 100
    assert swap['end_min'] - swap['start_min'] == 2
    cfg['swap_stock'] = 0
    partial = solve_baseline(prepare_baseline_project(raw, cfg), cfg)
    assert not partial['complete']
    assert partial['coverage']['physical_completed'] == 1
    assert len(partial['unscheduled_tasks']) == 1
    assert 'cost_total_yuan' not in partial


def test_vehicle_return_soc_reserved_before_accepting_remote_task():
    raw = source()
    raw['stations'].append(dict(id='C', name='C', line_id='L', service_allowed=False))
    raw['segments'].append(dict(id='T', line_id='L', start_station_id='B',
                                end_station_id='C', length_km=1, direction='both'))
    cfg = config(vehicle_range_km=1)
    s = solve_baseline(prepare_baseline_project(raw, cfg), cfg)
    assert not s['complete']
    assert s['coverage']['physical_completed'] == 1
    assert all(e['event_type'] != 'drive' for e in s['schedule_events'])


def test_reverse_only_segment_inspects_reverse_candidate():
    raw = source()
    raw['segments'][0]['direction'] = 'reverse'
    p = prepare_baseline_project(raw, config())
    s = solve_baseline(p, config())
    inspect, = [e for e in s['schedule_events'] if e['event_type'] == 'inspect']
    assert inspect['task_ids'] == [p['tasks'][0]['id']]
    assert inspect['from_node_id'] == 'B' and inspect['to_node_id'] == 'A'


def test_prepared_snapshot_and_config_tampering_rejected():
    cfg = config()
    p = prepare_baseline_project(source(), cfg)
    p['stations'][0]['x'] = 777
    with pytest.raises(ValueError, match='unchanged prepared'):
        solve_baseline(p, cfg)


def test_seeded_task_order_keeps_each_original_interval_together():
    raw = source()
    raw['segments'].append(dict(raw['segments'][0], id='T'))
    cfg = config()
    cfg.update(max_length_km=.2, window_min=1000, drone_endurance_min=1000)
    p = prepare_baseline_project(raw, cfg)
    s = solve_baseline(p, cfg)
    sequence = [e['segment_id'] for e in s['schedule_events'] if e['event_type'] == 'inspect']
    assert len(sequence) == 10
    assert sum(a != b for a, b in zip(sequence, sequence[1:])) == 1
