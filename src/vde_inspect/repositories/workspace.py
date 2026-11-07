"""Short-lived SQLite transactions plus immutable, hash-checked JSON snapshots."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4
import zipfile

from vde_inspect.domain.project import canonical_bytes, nonempty, normalize_project

MAX_JSON_BYTES = 32 * 1024 * 1024


def _load_json(path: Path) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('JSON exceeds the 32 MiB import limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    try:
        with path.open('r', encoding='utf-8-sig') as stream:
            value = json.load(stream, object_pairs_hook=pairs,
                              parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f'Invalid JSON number: {token}')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f'Invalid JSON: {exc}') from exc
    if not isinstance(value, dict):
        raise ValueError('JSON root must be an object')
    return value


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class WorkspaceRepository:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._solutions = self.root / 'solutions'
        self._solutions.mkdir(exist_ok=True)
        self._database = self.root / 'workspace.sqlite3'
        with self._connection(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS solutions (solution_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(project_id), filename TEXT UNIQUE NOT NULL, sha256 TEXT NOT NULL)')

    @contextmanager
    def _connection(self, *, write=False):
        db = sqlite3.connect(self._database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def list_projects(self) -> list[dict]:
        with self._connection() as db:
            return [json.loads(row['payload']) for row in db.execute('SELECT payload FROM projects ORDER BY rowid')]

    def create_project(self, name: str) -> dict:
        project = normalize_project({'project_id': str(uuid4()), 'name': name})
        return self._insert_project(project)

    def _insert_project(self, project: dict) -> dict:
        with self._connection(write=True) as db:
            if db.execute('SELECT 1 FROM projects WHERE project_id=?', (project['project_id'],)).fetchone():
                raise ValueError('Project ID already exists; import cannot overwrite a project')
            db.execute('INSERT INTO projects VALUES (?,?,?)',
                       (project['project_id'], project['revision'], canonical_bytes(project).decode('utf-8')))
        return project

    def get_project(self, project_id: str) -> dict:
        with self._connection() as db:
            row = db.execute('SELECT payload FROM projects WHERE project_id=?', (nonempty(project_id, 'project_id'),)).fetchone()
            if row is None:
                raise ValueError('Unknown project_id')
            return json.loads(row['payload'])

    def save_project(self, project: dict) -> dict:
        normalized = normalize_project(project)
        with self._connection(write=True) as db:
            row = db.execute('SELECT revision FROM projects WHERE project_id=?', (normalized['project_id'],)).fetchone()
            if row is None:
                raise ValueError('Unknown project_id')
            if normalized['revision'] != row['revision']:
                raise ValueError('Stale project revision; reload before saving')
            normalized['revision'] += 1
            db.execute('UPDATE projects SET revision=?,payload=? WHERE project_id=?',
                       (normalized['revision'], canonical_bytes(normalized).decode('utf-8'), normalized['project_id']))
        return normalized

    def import_project(self, path: Path) -> dict:
        return self._insert_project(normalize_project(_load_json(Path(path))))

    def export_project(self, project_id: str, path: Path) -> Path:
        project = self.get_project(project_id)
        destination = Path(path).resolve()
        self._check_destination(destination)
        _atomic_write(destination, canonical_bytes(project))
        return destination

    def _check_destination(self, destination: Path) -> None:
        if destination == self._database or destination == self._solutions or self._solutions in destination.parents:
            raise ValueError('Export destination cannot replace workspace storage')

    def list_solutions(self, project_id: str) -> list[dict]:
        self.get_project(project_id)
        with self._connection() as db:
            return [self._read_solution(row) for row in db.execute('SELECT * FROM solutions WHERE project_id=? ORDER BY rowid', (project_id,))]

    def store_solution(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('Solution must be an object')
        encoded = canonical_bytes(payload)
        if len(encoded) > MAX_JSON_BYTES:
            raise ValueError('Solution exceeds the 32 MiB storage limit')
        solution = json.loads(encoded)
        identifier = nonempty(solution.get('solution_id'), 'solution_id')
        project_id = nonempty(solution.get('project_id'), 'project_id')
        filename = hashlib.sha256(identifier.encode('utf-8')).hexdigest() + '.json'
        path = self._solutions / filename
        created = False
        try:
            with self._connection(write=True) as db:
                if db.execute('SELECT 1 FROM solutions WHERE solution_id=?', (identifier,)).fetchone():
                    raise FileExistsError('Immutable solution_id already exists')
                row = db.execute('SELECT payload FROM projects WHERE project_id=?', (project_id,)).fetchone()
                if row is None:
                    raise ValueError('Unknown solution project_id')
                if solution.get('input_hash') != json.loads(row['payload'])['input_hash']:
                    raise ValueError('Solution input_hash does not match the current project')
                # Exclusive creation also refuses orphan files after an interrupted process.
                with path.open('xb') as stream:
                    created = True
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                db.execute('INSERT INTO solutions VALUES (?,?,?,?)',
                           (identifier, project_id, filename, hashlib.sha256(encoded).hexdigest()))
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        return solution

    def _read_solution(self, row) -> dict:
        expected_filename = hashlib.sha256(row['solution_id'].encode('utf-8')).hexdigest() + '.json'
        if row['filename'] != expected_filename:
            raise ValueError('Solution integrity failure: invalid filename')
        path = self._solutions / expected_filename
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ValueError('Solution integrity failure: snapshot missing or unreadable') from exc
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Solution integrity failure: SHA256 mismatch')
        value = _load_json(path)
        if value.get('solution_id') != row['solution_id'] or value.get('project_id') != row['project_id']:
            raise ValueError('Solution integrity failure: ID mismatch')
        return value

    def load_solution(self, solution_id: str) -> dict:
        with self._connection() as db:
            row = db.execute('SELECT * FROM solutions WHERE solution_id=?', (nonempty(solution_id, 'solution_id'),)).fetchone()
            if row is None:
                raise ValueError('Unknown solution_id')
            return self._read_solution(row)

    def export_solution(self, solution_id: str, path: Path) -> Path:
        """Export the complete verified snapshot without touching workspace storage."""
        solution = self.load_solution(solution_id)
        destination = Path(path).resolve()
        self._check_destination(destination)
        _atomic_write(destination, canonical_bytes(solution))
        return destination

    def backup(self, destination: Path) -> Path:
        """A ZIP of a consistent SQLite snapshot, registered files, and SHA256 manifest."""
        destination = Path(destination).resolve()
        self._check_destination(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_zip = tempfile.mkstemp(prefix='.backup-', dir=destination.parent)
        os.close(fd)
        try:
            with tempfile.TemporaryDirectory(prefix='vde-backup-') as temporary:
                database_copy = Path(temporary) / 'workspace.sqlite3'
                with self._connection() as db:
                    rows = list(db.execute('SELECT * FROM solutions'))
                    target = sqlite3.connect(database_copy)
                    try:
                        db.backup(target)
                    finally:
                        target.close()
                    files = {'workspace.sqlite3': database_copy.read_bytes()}
                    for row in rows:
                        value = self._read_solution(row)
                        files['solutions/' + row['filename']] = canonical_bytes(value)
                manifest = {'format': 'vde-inspect-backup-1',
                            'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
                with zipfile.ZipFile(temporary_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                    for name, data in files.items():
                        archive.writestr(name, data)
                    archive.writestr('manifest.json', canonical_bytes(manifest))
                # Verify the actual archive before publishing the destination.
                with zipfile.ZipFile(temporary_zip) as archive:
                    if archive.testzip() is not None:
                        raise ValueError('Backup integrity failure')
                    for name, digest in manifest['sha256'].items():
                        if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                            raise ValueError('Backup integrity failure')
                os.replace(temporary_zip, destination)
        finally:
            Path(temporary_zip).unlink(missing_ok=True)
        return destination

    def close(self) -> None:
        """Connections belong to individual operations; nothing is held open."""
