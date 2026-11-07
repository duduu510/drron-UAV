"""Validation and canonical hashes for the provisional project contract."""
from __future__ import annotations

import hashlib
import json
import math
from uuid import uuid4

COLLECTIONS = ('lines', 'stations', 'segments', 'tasks', 'depots', 'vehicle_models',
               'drone_models', 'vehicles', 'drones', 'batteries')


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError('Data must contain finite JSON values') from exc


def nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonempty string')
    return value


def number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be numeric')
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f'{label} must be finite' + (' and positive' if positive else ''))
    return value


def input_hash(project: dict) -> str:
    inputs = {k: v for k, v in project.items() if k not in ('revision', 'input_hash')}
    return hashlib.sha256(canonical_bytes(inputs)).hexdigest()


def normalize_project(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError('Project must be a JSON object')
    project = json.loads(canonical_bytes(raw))
    project.setdefault('project_id', str(uuid4()))
    nonempty(project['project_id'], 'project_id')
    nonempty(project.get('name'), 'name')
    project.setdefault('schema_version', 'provisional-1')
    if project['schema_version'] != 'provisional-1':
        raise ValueError('Unsupported schema_version')
    project.setdefault('revision', 1)
    if type(project['revision']) is not int or project['revision'] < 1:
        raise ValueError('revision must be a positive integer')
    for config in ('cost_config', 'safety_config'):
        project.setdefault(config, {})
        if not isinstance(project[config], dict):
            raise ValueError(f'{config} must be an object')
    indices = {}
    for collection in COLLECTIONS:
        rows = project.setdefault(collection, [])
        if not isinstance(rows, list):
            raise ValueError(f'{collection} must be an array')
        index = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f'{collection} entries must be objects')
            entity_id = nonempty(row.get('id'), f'{collection}.id')
            if entity_id in index:
                raise ValueError(f'Duplicate {collection} ID: {entity_id}')
            index[entity_id] = row
        indices[collection] = index

    def ref(row, key, collection):
        value = nonempty(row.get(key), key)
        if value not in indices[collection]:
            raise ValueError(f'Unknown {collection} reference: {value}')

    for line in project['lines']:
        nonempty(line.get('name'), 'line.name')
        nonempty(line.get('color'), 'line.color')
    for station in project['stations']:
        nonempty(station.get('name'), 'station.name')
        ref(station, 'line_id', 'lines')
        if type(station.get('service_allowed')) is not bool:
            raise ValueError('station.service_allowed must be boolean')
        x, y = station.get('x'), station.get('y')
        if (x is None) != (y is None):
            raise ValueError('Station coordinates must be both present or both absent')
        if x is not None:
            number(x, 'x')
            number(y, 'y')
        if 'line_ids' in station:
            if not isinstance(station['line_ids'], list):
                raise ValueError('line_ids must be an array')
            for line_id in station['line_ids']:
                if not isinstance(line_id, str) or line_id not in indices['lines']:
                    raise ValueError('Unknown station line_ids reference')
    for segment in project['segments']:
        ref(segment, 'line_id', 'lines')
        ref(segment, 'start_station_id', 'stations')
        ref(segment, 'end_station_id', 'stations')
        number(segment.get('length_km'), 'segment.length_km', positive=True)
        if segment.get('direction') not in ('forward', 'reverse', 'both'):
            raise ValueError('Invalid segment direction')
    for depot in project['depots']:
        nonempty(depot.get('name'), 'depot.name')
        ref(depot, 'station_id', 'stations')
    for collection in ('vehicle_models', 'drone_models'):
        for model in project[collection]:
            nonempty(model.get('name'), 'model.name')
            fields = ('capacity', 'battery_count', 'range_km') if collection == 'vehicle_models' else ('endurance_min',)
            for key in fields:
                number(model.get(key), f'model.{key}', positive=True)
            for key in ('capacity', 'battery_count') if collection == 'vehicle_models' else ():
                if type(model[key]) is not int:
                    raise ValueError(f'model.{key} must be an integer')
    for collection, models in (('vehicles', 'vehicle_models'), ('drones', 'drone_models')):
        for device in project[collection]:
            ref(device, 'model_id', models)
            ref(device, 'depot_id', 'depots')
    for battery in project['batteries']:
        nonempty(battery.get('name'), 'battery.name')
        if type(battery.get('quantity')) is not int or battery['quantity'] < 0:
            raise ValueError('battery.quantity must be a nonnegative integer')
        compatible = battery.get('compatible_models')
        if not isinstance(compatible, list):
            raise ValueError('compatible_models must be an array')
        for model_id in compatible:
            if not isinstance(model_id, str) or (model_id not in indices['vehicle_models'] and model_id not in indices['drone_models']):
                raise ValueError('Unknown compatible model reference')
    # Nodes invented by a subdivision are only valid when derivable from its segment.
    from vde_inspect.services.tasks import validate_task_nodes
    validate_task_nodes(project)
    project['input_hash'] = input_hash(project)
    return project
