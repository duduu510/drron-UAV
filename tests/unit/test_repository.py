import copy
import hashlib
import json
import zipfile

import pytest

from vde_inspect.repositories.workspace import WorkspaceRepository


def network(project):
    project['lines'] = [{'id': 'L', 'name': 'Line', 'color': '#1467E8'}]
    project['stations'] = [
        {'id': 'A', 'name': 'A', 'line_id': 'L', 'x': 0, 'y': 0, 'service_allowed': True},
        {'id': 'B', 'name': 'B', 'line_id': 'L', 'x': None, 'y': None, 'service_allowed': False},
    ]
    project['segments'] = [{'id': 'S', 'line_id': 'L', 'start_station_id': 'A',
                            'end_station_id': 'B', 'length_km': 2.5, 'direction': 'both'}]
    return project


def test_persistence_revision_and_hash(tmp_path):
    repo = WorkspaceRepository(tmp_path)
    project = repo.create_project('测试')
    saved = repo.save_project(network(project))
    assert saved['revision'] == project['revision'] + 1
    assert saved['input_hash'] != project['input_hash']
    repo.close()
    reopened = WorkspaceRepository(tmp_path)
    assert reopened.get_project(project['project_id']) == saved
    assert reopened.list_projects() == [saved]


def test_stale_save_cannot_replace_new_revision(tmp_path):
    repo = WorkspaceRepository(tmp_path)
    project = repo.create_project('Original')
    stale = copy.deepcopy(project)
    project['name'] = 'Newer'
    saved = repo.save_project(project)
    stale['name'] = 'Stale'
    with pytest.raises(ValueError, match='revision|版本'):
        repo.save_project(stale)
    assert repo.get_project(saved['project_id']) == saved


@pytest.mark.parametrize('kind', ['duplicate', 'reference', 'malformed', 'wrong-array', 'nan'])
def test_invalid_import_is_atomic(tmp_path, kind):
    repo = WorkspaceRepository(tmp_path / 'workspace')
    existing = repo.create_project('Keep')
    incoming = network(copy.deepcopy(existing))
    incoming['project_id'] = 'imported'
    if kind == 'duplicate':
        incoming['stations'].append(copy.deepcopy(incoming['stations'][0]))
    elif kind == 'reference':
        incoming['segments'][0]['end_station_id'] = 'missing'
    elif kind == 'wrong-array':
        incoming['vehicles'] = {}
    elif kind == 'nan':
        incoming['segments'][0]['length_km'] = float('nan')
    path = tmp_path / 'bad.json'
    path.write_text('{' if kind == 'malformed' else json.dumps(incoming), encoding='utf-8')
    with pytest.raises(ValueError):
        repo.import_project(path)
    assert repo.list_projects() == [existing]


def test_export_import_preserves_extension_fields_and_rejects_collision(tmp_path):
    repo = WorkspaceRepository(tmp_path / 'a')
    project = repo.create_project('Export')
    project['adapter_metadata'] = {'source': 'user'}
    project = repo.save_project(project)
    path = repo.export_project(project['project_id'], tmp_path / 'project.json')
    other = WorkspaceRepository(tmp_path / 'b')
    assert other.import_project(path) == project
    with pytest.raises(ValueError):
        other.import_project(path)
    assert other.list_projects() == [project]


def test_snapshot_immutable_and_backup_restorable(tmp_path):
    repo = WorkspaceRepository(tmp_path / 'workspace')
    project = repo.create_project('Project')
    solution = {'solution_id': '../unsafe/id', 'run_id': 'run', 'project_id': project['project_id'],
                'input_hash': project['input_hash'], 'source_mode': 'precomputed', 'events': []}
    assert repo.store_solution(solution) == solution
    with pytest.raises(FileExistsError):
        repo.store_solution({**solution, 'events': [{'changed': True}]})
    project['name'] = 'Changed'
    repo.save_project(project)
    assert repo.load_solution(solution['solution_id']) == solution
    assert repo.list_solutions(project['project_id']) == [solution]
    backup = repo.backup(tmp_path / 'backup.zip')
    with zipfile.ZipFile(backup) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        for name, digest in manifest['sha256'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        archive.extractall(tmp_path / 'restored')
    restored = WorkspaceRepository(tmp_path / 'restored')
    assert restored.load_solution(solution['solution_id']) == solution
    assert restored.get_project(project['project_id'])['name'] == 'Changed'


def test_solution_rejects_foreign_hash_and_detects_corruption(tmp_path):
    repo = WorkspaceRepository(tmp_path)
    project = repo.create_project('Project')
    solution = {'solution_id': 'S', 'project_id': project['project_id'], 'input_hash': '0' * 64}
    with pytest.raises(ValueError):
        repo.store_solution(solution)
    solution['input_hash'] = project['input_hash']
    repo.store_solution(solution)
    snapshot = next((tmp_path / 'solutions').glob('*.json'))
    snapshot.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='integrity|完整'):
        repo.load_solution('S')


def test_referenced_station_cannot_be_deleted_or_virtual_node_serviced(tmp_path):
    from vde_inspect.services.tasks import generate_tasks
    repo = WorkspaceRepository(tmp_path)
    saved = repo.save_project(network(repo.create_project('Network')))
    changed = copy.deepcopy(saved)
    changed['stations'].pop()
    with pytest.raises(ValueError):
        repo.save_project(changed)
    changed = copy.deepcopy(saved)
    changed['tasks'] = generate_tasks(changed, 1)
    changed['tasks'][0]['end_service_allowed'] = True
    with pytest.raises(ValueError):
        repo.save_project(changed)
    assert repo.get_project(saved['project_id']) == saved


def test_generated_tasks_can_be_saved(tmp_path):
    from vde_inspect.services.tasks import generate_tasks
    repo = WorkspaceRepository(tmp_path)
    project = network(repo.create_project('Tasks'))
    project['tasks'] = generate_tasks(project, 1)
    assert len(repo.save_project(project)['tasks']) == 6


def test_threaded_stale_writers_only_one_succeeds(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    repo = WorkspaceRepository(tmp_path)
    project = repo.create_project('Threads')
    def save(index):
        try:
            return repo.save_project({**project, 'name': str(index)})
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(save, range(8)))
    successes = [row for row in results if row is not None]
    assert len(successes) == 1
    assert repo.get_project(project['project_id']) == successes[0]


def test_snapshot_file_is_removed_when_database_transaction_fails(tmp_path):
    import sqlite3
    repo = WorkspaceRepository(tmp_path)
    project = repo.create_project('Rollback')
    # A SQLite constraint failure after creating the file must roll back both resources.
    with sqlite3.connect(tmp_path / 'workspace.sqlite3') as db:
        db.execute("CREATE TRIGGER reject_solution BEFORE INSERT ON solutions BEGIN SELECT RAISE(ABORT, 'rejected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.store_solution({'solution_id': 'rejected', 'project_id': project['project_id'],
                             'input_hash': project['input_hash']})
    assert repo.list_solutions(project['project_id']) == []
    assert list((tmp_path / 'solutions').glob('*.json')) == []


def test_backup_corruption_preserves_previous_destination(tmp_path):
    repo = WorkspaceRepository(tmp_path / 'workspace')
    project = repo.create_project('Backup')
    repo.store_solution({'solution_id': 'broken', 'project_id': project['project_id'],
                         'input_hash': project['input_hash']})
    destination = tmp_path / 'backup.zip'
    destination.write_bytes(b'previous backup')
    next((repo.root / 'solutions').glob('*.json')).unlink()
    with pytest.raises(ValueError):
        repo.backup(destination)
    assert destination.read_bytes() == b'previous backup'


@pytest.mark.parametrize('export_kind', ['project', 'solution'])
@pytest.mark.parametrize('destination_kind', ['database', 'snapshot', 'new-snapshot'])
def test_exports_cannot_replace_workspace_storage(tmp_path, export_kind, destination_kind):
    repo = WorkspaceRepository(tmp_path)
    project = repo.create_project('Export guard')
    solution = {'solution_id': 'S', 'project_id': project['project_id'],
                'input_hash': project['input_hash']}
    repo.store_solution(solution)
    database = tmp_path / 'workspace.sqlite3'
    snapshot = next((tmp_path / 'solutions').glob('*.json'))
    original_database, original_snapshot = database.read_bytes(), snapshot.read_bytes()
    destination = {'database': database, 'snapshot': snapshot,
                   'new-snapshot': tmp_path / 'solutions' / 'other.json'}[destination_kind]
    operation = repo.export_project if export_kind == 'project' else repo.export_solution
    identifier = project['project_id'] if export_kind == 'project' else solution['solution_id']
    with pytest.raises(ValueError):
        operation(identifier, destination)
    assert database.read_bytes() == original_database
    assert snapshot.read_bytes() == original_snapshot
    assert not (tmp_path / 'solutions' / 'other.json').exists()
    assert repo.load_solution('S') == solution


def test_export_solution_preserves_full_offline_envelope(tmp_path):
    from vde_inspect.solver.adapter import load_fixture
    repo = WorkspaceRepository(tmp_path / 'workspace')
    project = repo.create_project('Envelope')
    solution = {'solution_id': 'immutable-solution', 'run_id': 'immutable-run',
                'project_id': project['project_id'], 'input_hash': project['input_hash'],
                'source_mode': 'precomputed', 'adapter_extra': {'origin': 'provided'},
                'schedule_events': [{'event_id': 'e', 'device_id': 'device', 'event_type': 'travel',
                                     'start_min': 0, 'end_min': 2, 'soc_start': 100, 'soc_end': 95,
                                     'from_node_id': 'A', 'to_node_id': 'B'}]}
    repo.store_solution(solution)
    destination = tmp_path / 'export' / 'solution.json'
    assert repo.export_solution(solution['solution_id'], destination) == destination.resolve()
    assert json.loads(destination.read_text(encoding='utf-8')) == solution
    loaded = load_fixture(destination)
    for key, value in solution.items():
        assert loaded[key] == value
    assert repo.load_solution(solution['solution_id']) == solution


def test_export_corrupted_solution_preserves_existing_destination(tmp_path):
    repo = WorkspaceRepository(tmp_path / 'workspace')
    project = repo.create_project('Integrity')
    repo.store_solution({'solution_id': 'S', 'project_id': project['project_id'],
                         'input_hash': project['input_hash']})
    next((repo.root / 'solutions').glob('*.json')).write_bytes(b'{}')
    destination = tmp_path / 'export.json'
    destination.write_bytes(b'previous export')
    with pytest.raises(ValueError):
        repo.export_solution('S', destination)
    assert destination.read_bytes() == b'previous export'
