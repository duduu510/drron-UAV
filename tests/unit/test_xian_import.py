import hashlib
import json
import zipfile

import pytest

from vde_inspect.services.xian_import import load_xian_archive


def records():
    return {
        'lines': [{'id': 'L1', 'name': '一号线', 'color': '#123456'},
                  {'id': 'L2', 'name': '二号线', 'color': '#654321'}],
        'stations': [
            {'id': 'A', 'name': '甲', 'schematic': {'x': 10, 'y': 20},
             'location': {'lon': 108, 'lat': 34}},
            {'id': 'B', 'name': '乙', 'location': {'lon': 109, 'lat': 35}},
        ],
        'stops': [{'id': 'A1', 'station_id': 'A', 'line_id': 'L1'},
                  {'id': 'A2', 'station_id': 'A', 'line_id': 'L2'},
                  {'id': 'B1', 'station_id': 'B', 'line_id': 'L1'}],
        'segments': [{'id': 'S', 'line_id': 'L1', 'from_station_id': 'A',
                      'to_station_id': 'B', 'from_stop_id': 'A1', 'to_stop_id': 'B1',
                      'distance_km': 1.25, 'direction': 'both', 'travel_time_seconds': 120,
                      'extras': {'distance_source': 'haversine'}}],
    }


def archive(path, data):
    with zipfile.ZipFile(path, 'w') as z:
        for name, rows in data.items():
            z.writestr('cn-xian/' + name + '.json', json.dumps({'network_id': 'cn-xian', 'records': rows}))
    return path


def test_convert_preserves_provenance_and_no_operational_resources(tmp_path):
    path = archive(tmp_path / 'xian.zip', records())
    project = load_xian_archive(path)
    assert project['name'] == '西安地铁线网（导入数据）'
    assert project['stations'][0]['line_ids'] == ['L1', 'L2']
    assert project['stations'][0]['x'] == 10
    assert project['stations'][0]['y'] == 20
    assert project['stations'][1]['x'] is None
    assert project['stations'][1]['y'] is None
    assert all(s['service_allowed'] is False for s in project['stations'])
    segment, = project['segments']
    assert segment['start_station_id'] == 'A'
    assert segment['end_station_id'] == 'B'
    assert segment['length_km'] == 1.25
    assert segment['direction'] == 'both'
    assert segment['distance_source'] == 'haversine'
    assert segment['travel_time_seconds'] == 120
    assert segment['travel_time_semantics'] == 'passenger_train'
    assert not any(project[key] for key in ('tasks', 'depots', 'vehicles', 'drones', 'batteries', 'vehicle_models', 'drone_models'))
    source = project['source_metadata']
    assert source['archive_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert source['record_counts'] == {'lines': 2, 'stations': 2, 'segments': 1, 'stops': 3}
    assert source['total_length_km'] == 1.25
    assert source['task_assessment']['max_length_km'] == .5
    assert source['task_assessment']['count'] == 6
    assert source['task_assessment']['physical_task_count'] == 3
    assert source['task_assessment']['directional_candidate_count'] == 6
    assert load_xian_archive(path) == project


@pytest.mark.parametrize('broken', ['missing-stops', 'station', 'stop', 'line', 'duplicate', 'distance', 'network'])
def test_invalid_archive_references_rejected(tmp_path, broken):
    data = records()
    if broken == 'missing-stops':
        data.pop('stops')
    elif broken == 'station':
        data['segments'][0]['to_station_id'] = 'missing'
    elif broken == 'stop':
        data['segments'][0]['from_stop_id'] = 'missing'
    elif broken == 'line':
        data['stops'][0]['line_id'] = 'missing'
    elif broken == 'duplicate':
        data['stops'].append(dict(data['stops'][0]))
    elif broken == 'distance':
        data['segments'][0]['distance_km'] = 0
    elif broken == 'network':
        data['segments'][0]['from_stop_id'] = 'A2'  # Wrong line for the physical segment.
    with pytest.raises(ValueError):
        load_xian_archive(archive(tmp_path / 'bad.zip', data))


def test_rejects_unsafe_and_ambiguous_archive_members(tmp_path):
    path = archive(tmp_path / 'bad.zip', records())
    with zipfile.ZipFile(path, 'a') as z:
        z.writestr('../outside.txt', 'unsafe')
    with pytest.raises(ValueError):
        load_xian_archive(path)
    assert not (tmp_path / 'outside.txt').exists()


def test_archive_import_is_repository_ready_and_same_source_cannot_overwrite(tmp_path):
    from vde_inspect.repositories.workspace import WorkspaceRepository
    project = load_xian_archive(archive(tmp_path / 'source.zip', records()))
    path = tmp_path / 'project.json'
    path.write_text(json.dumps(project), encoding='utf-8')
    repository = WorkspaceRepository(tmp_path / 'workspace')
    assert repository.import_project(path) == project
    with pytest.raises(ValueError):
        repository.import_project(path)


def test_missing_source_line_color_has_explicit_neutral_display_fallback(tmp_path):
    data = records()
    data['lines'][0]['color'] = None
    project = load_xian_archive(archive(tmp_path / 'source.zip', data))
    line = project['lines'][0]
    assert line['color'] == '#808080'
    assert line['source_color'] is None
    assert line['color_source'] == 'display_fallback_missing_source'
