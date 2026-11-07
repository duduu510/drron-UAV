from copy import deepcopy

import pytest

from vde_inspect.solver.baseline_validator import validate_baseline_solution


def tiny_source():
    return {'project_id': 'source', 'name': 'Tiny', 'stations': [
        {'id': 'A', 'name': 'A', 'line_id': 'L', 'x': 0, 'y': 0, 'service_allowed': False},
        {'id': 'B', 'name': 'B', 'line_id': 'L', 'x': 1, 'y': 0, 'service_allowed': False}],
        'lines': [{'id': 'L', 'name': 'L', 'color': '#000000'}],
        'segments': [{'id': 'S', 'line_id': 'L', 'start_station_id': 'A',
                      'end_station_id': 'B', 'length_km': .2, 'direction': 'both'}]}


def actual_result():
    from vde_inspect.solver.baseline import normalize_config, prepare_baseline_project, solve_baseline
    config = normalize_config({'depot_station_id': 'A', 'assume_service_at_all_stations': True,
                               'team_count': 1})
    project = prepare_baseline_project(tiny_source(), config)
    return solve_baseline(project, config), project, config


def test_real_tiny_solution_passes_simulation_check_only():
    solution, project, config = actual_result()
    report = validate_baseline_solution(solution, project, config)
    assert report['passed'], report['violations']
    assert report['scope'] == 'simulation-baseline'
    assert report['publishable'] is False
    assert solution['validation_passed'] is False


@pytest.mark.parametrize('mutation', ['duplicate', 'return', 'cost', 'soc', 'missing', 'partial'])
def test_independent_checker_rejects_mutation(mutation):
    solution, project, config = actual_result()
    bad = deepcopy(solution)
    if mutation == 'duplicate':
        event = deepcopy(next(e for e in bad['schedule_events'] if e['event_type'] == 'inspect'))
        event['event_id'] += '-duplicate'
        bad['schedule_events'].append(event)
    elif mutation == 'return':
        vehicle = project['vehicles'][0]['id']
        last = max((e for e in bad['schedule_events'] if e['device_id'] == vehicle), key=lambda e: e['end_min'])
        last['to_node_id'] = 'B'
    elif mutation == 'cost':
        bad['cost_breakdown_yuan']['vehicle_fixed'] += 1
    elif mutation == 'soc':
        bad['schedule_events'][0]['soc_end'] = 99
    elif mutation == 'missing':
        del bad['sorties']
    else:
        bad['complete'] = False
    report = validate_baseline_solution(bad, project, config)
    assert report['passed'] is False
    assert report['violations']


def test_bad_input_is_diagnostic_not_checker_crash():
    assert not validate_baseline_solution({}, {}, {})['passed']


@pytest.mark.parametrize('mutation', ['launch', 'assumption', 'sortie_metric', 'interval_metric', 'orphan', 'segment'])
def test_checker_reconstructs_sortie_and_assumptions(mutation):
    solution, project, config = actual_result()
    if mutation == 'launch':
        solution['schedule_events'] = [e for e in solution['schedule_events'] if e['event_type'] != 'launch']
    elif mutation == 'assumption':
        solution['model_assumptions']['config']['drone_speed_kmh'] = 999
    elif mutation == 'sortie_metric':
        solution['sorties'][0]['flight_distance_km'] += .1
    elif mutation == 'interval_metric':
        solution['coverage']['original_intervals_completed'] = 0
    elif mutation == 'orphan':
        next(e for e in solution['schedule_events'] if e['event_type'] == 'inspect').pop('sortie_id')
    else:
        next(e for e in solution['schedule_events'] if e['event_type'] == 'inspect')['segment_id'] = 'unrelated'
    assert not validate_baseline_solution(solution, project, config)['passed']


def travel_and_swap_result(**overrides):
    from vde_inspect.solver.baseline import normalize_config, prepare_baseline_project, solve_baseline
    source = tiny_source()
    source['stations'].append(dict(source['stations'][-1], id='C', name='C', x=2))
    source['segments'].append(dict(source['segments'][0], id='T', start_station_id='B', end_station_id='C'))
    config = normalize_config(dict(depot_station_id='A', assume_service_at_all_stations=True,
                                   team_count=1, max_length_km=.1, drone_endurance_min=5,
                                   **overrides))
    project = prepare_baseline_project(source, config)
    return solve_baseline(project, config), project, config


def test_independent_reconstruction_with_ground_travel_and_swaps():
    solution, project, config = travel_and_swap_result()
    assert any(e['event_type'] == 'drive' for e in solution['schedule_events'])
    assert any(e['event_type'] == 'swap' for e in solution['schedule_events'])
    report = validate_baseline_solution(solution, project, config)
    assert report['passed'], report['violations']


@pytest.mark.parametrize('mutation', ['stock', 'sync', 'window', 'ground', 'virtual_service'])
def test_ground_and_resource_mutations_fail(mutation):
    solution, project, config = travel_and_swap_result()
    if mutation == 'stock':
        config['swap_stock'] = 0
        project['baseline_config'] = deepcopy(config)
        solution['model_assumptions']['config'] = deepcopy(config)
    elif mutation == 'sync':
        next(e for e in solution['schedule_events'] if e['event_type'] == 'wait' and e.get('sortie_id'))['start_min'] += .01
    elif mutation == 'window':
        config['window_min'] = .1
        project['baseline_config'] = deepcopy(config)
        solution['model_assumptions']['config'] = deepcopy(config)
    elif mutation == 'ground':
        next(e for e in solution['schedule_events'] if e['event_type'] == 'drive')['distance_km'] += .1
    else:
        next(t for t in project['tasks'] if t['end_node_id'].startswith('virtual:'))['end_service_allowed'] = True
    assert not validate_baseline_solution(solution, project, config)['passed']


def test_honest_partial_keeps_diagnostics_and_partial_cost():
    solution, project, config = travel_and_swap_result(swap_stock=0)
    assert not solution['complete']
    assert 'cost_partial_yuan' in solution and 'cost_total_yuan' not in solution
    report = validate_baseline_solution(solution, project, config)
    assert not report['passed']
    assert {v['check'] for v in report['violations']} == {'completion'}


@pytest.mark.parametrize('gap_at_start', [True, False])
def test_hidden_wait_cannot_evade_elapsed_vehicle_cost(gap_at_start):
    solution, project, config = actual_result()
    if gap_at_start:
        for event in solution['schedule_events']:
            event['start_min'] += 10
            event['end_min'] += 10
        for sortie in solution['sorties']:
            sortie['start_min'] += 10
            sortie['end_min'] += 10
    else:
        # Keep first event at zero but introduce an unrecorded wait before the
        # final land event, extending the vehicle wait and sortie consistently.
        land = next(e for e in solution['schedule_events'] if e['event_type'] == 'land')
        land['start_min'] += 10
        land['end_min'] += 10
        next(e for e in solution['schedule_events'] if e['event_type'] == 'wait')['end_min'] += 10
        solution['sorties'][0]['end_min'] += 10
    solution['return_time_min'] += 10
    report = validate_baseline_solution(solution, project, config)
    assert not report['passed']
    assert 'cost' in {v['check'] for v in report['violations']}


def test_unrecorded_vehicle_gap_rejected_even_if_elapsed_cost_paid():
    solution, project, config = travel_and_swap_result()
    vehicle_id = project['vehicles'][0]['id']
    schedule = sorted((e for e in solution['schedule_events'] if e['device_id'] == vehicle_id), key=lambda e: e['start_min'])
    schedule[0]['start_min'] += .01
    solution['cost_breakdown_yuan']['vehicle_time'] = max(e['end_min'] for e in schedule) * config['vehicle_min_yuan']
    solution['cost_total_yuan'] = sum(solution['cost_breakdown_yuan'].values())
    assert not validate_baseline_solution(solution, project, config)['passed']
