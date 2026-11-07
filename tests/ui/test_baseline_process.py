import json

import pytest

from vde_inspect.solver.manager import BaselineRunManager


def prepared():
    from vde_inspect.solver.baseline import normalize_config, prepare_baseline_project
    source = {'project_id': 'source', 'name': 'tiny', 'lines': [{'id': 'L', 'name': 'L', 'color': '#000000'}],
              'stations': [{'id': s, 'name': s, 'line_id': 'L', 'x': i, 'y': 0,
                            'service_allowed': False} for i, s in enumerate(('A', 'B'))],
              'segments': [{'id': 'S', 'line_id': 'L', 'start_station_id': 'A',
                            'end_station_id': 'B', 'length_km': .2, 'direction': 'both'}]}
    config = normalize_config({'depot_station_id': 'A', 'team_count': 1,
                               'assume_service_at_all_stations': True})
    return prepare_baseline_project(source, config), config


def test_actual_process_completes_and_persists_provenance(qtbot, tmp_path):
    project, config = prepared()
    manager = BaselineRunManager()
    progress, errors = [], []
    manager.progress.connect(progress.append)
    manager.failed.connect(errors.append)
    with qtbot.waitSignal(manager.finished, timeout=15000) as signal:
        manager.start(project, config, tmp_path / 'run')
    result = signal.args[0]
    assert not errors
    assert not manager.running
    assert result['baseline_validation']['passed']
    assert result['publishable'] is False
    assert result['provenance_label'] == '本机新计算的仿真基线（研究模型）'
    assert progress and progress[-1]['processed'] == progress[-1]['total']
    assert json.loads((tmp_path / 'run' / 'request.json').read_text(encoding='utf-8'))['project'] == project
    assert json.loads((tmp_path / 'run' / 'state.json').read_text(encoding='utf-8'))['status'] == 'finished'
    assert (tmp_path / 'run' / 'events.jsonl').read_text(encoding='utf-8')


def test_duplicate_start_rejected_and_cancel_never_finishes(qtbot, tmp_path):
    project, config = prepared()
    manager = BaselineRunManager()
    successes = []
    manager.finished.connect(successes.append)
    manager.start(project, config, tmp_path / 'run')
    with pytest.raises(RuntimeError):
        manager.start(project, config, tmp_path / 'second')
    with qtbot.waitSignal(manager.cancelled, timeout=5000):
        manager.cancel()
    assert not manager.running
    assert not successes
    assert json.loads((tmp_path / 'run' / 'state.json').read_text(encoding='utf-8'))['status'] == 'cancelled'


def test_worker_error_persisted_and_manager_reusable(qtbot, tmp_path):
    project, config = prepared()
    manager = BaselineRunManager()
    invalid = dict(config, drone_speed_kmh=0)
    with qtbot.waitSignal(manager.failed, timeout=5000) as failure:
        manager.start(project, invalid, tmp_path / 'bad')
    assert failure.args[0]
    assert not manager.running
    assert json.loads((tmp_path / 'bad' / 'state.json').read_text(encoding='utf-8'))['status'] == 'failed'
    assert not (tmp_path / 'bad' / 'result.json').exists()
    assert 'error' in (tmp_path / 'bad' / 'events.jsonl').read_text(encoding='utf-8')
    with qtbot.waitSignal(manager.finished, timeout=5000):
        manager.start(project, config, tmp_path / 'good')
