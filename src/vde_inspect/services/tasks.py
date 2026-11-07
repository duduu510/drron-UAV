"""Pure, deterministic physical-segment subdivision; no service at virtual nodes."""
from __future__ import annotations

import hashlib
import math

from vde_inspect.domain.project import nonempty, number

MAX_GENERATED_TASKS = 100_000


def _virtual(segment_id: str, boundary: int, parts: int) -> str:
    digest = hashlib.sha256(segment_id.encode('utf-8')).hexdigest()
    return f'virtual:{digest}:{boundary}:{parts}'


def generate_tasks(project: dict, max_length_km: float) -> list[dict]:
    """Return directional candidates, paired by ``physical_task_id``.

    A bidirectional segment has two alternative candidates for every physical
    piece. A solver must cover each physical group once in an allowed direction;
    the candidate list length is not the number of mandatory executions.
    """
    number(max_length_km, 'max_length_km', positive=True)
    if not isinstance(project, dict):
        raise ValueError('Project must be an object')
    stations = project.get('stations', [])
    segments = project.get('segments', [])
    if not isinstance(stations, list) or not isinstance(segments, list):
        raise ValueError('stations and segments must be arrays')
    station_index = {}
    for station in stations:
        if not isinstance(station, dict):
            raise ValueError('Station must be an object')
        identifier = nonempty(station.get('id'), 'station.id')
        if identifier in station_index or type(station.get('service_allowed')) is not bool:
            raise ValueError('Duplicate station ID or invalid service permission')
        station_index[identifier] = station
    result, seen = [], set()
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError('Segment must be an object')
        identifier = nonempty(segment.get('id'), 'segment.id')
        if identifier in seen:
            raise ValueError('Duplicate segment ID')
        seen.add(identifier)
        start, end = segment.get('start_station_id'), segment.get('end_station_id')
        if not isinstance(start, str) or not isinstance(end, str) or start not in station_index or end not in station_index:
            raise ValueError('Unknown segment station')
        length = number(segment.get('length_km'), 'length_km', positive=True)
        direction = segment.get('direction')
        if direction not in ('forward', 'reverse', 'both'):
            raise ValueError('Invalid segment direction')
        ratio = length / max_length_km
        if not math.isfinite(ratio) or ratio > MAX_GENERATED_TASKS:
            raise ValueError('Task subdivision exceeds supported size')
        count = max(1, math.ceil(ratio))
        directions = ('forward', 'reverse') if direction == 'both' else (direction,)
        if len(result) + count * len(directions) > MAX_GENERATED_TASKS:
            raise ValueError('Task subdivision exceeds supported size')
        nodes = [start] + [_virtual(identifier, i, count) for i in range(1, count)] + [end]
        if any(node in station_index for node in nodes[1:-1]):
            raise ValueError('Virtual node ID collides with a station')
        part_length = length / count
        lengths = [part_length] * count
        # Clamp a possible one-ULP residual so decimal inputs never breach the limit.
        lengths[-1] = min(max_length_km, length - math.fsum(lengths[:-1]))
        if part_length <= 0 or lengths[-1] <= 0:
            raise ValueError('Subdivision is below numeric precision')
        digest = hashlib.sha256(identifier.encode('utf-8')).hexdigest()
        for travel in directions:
            indices = range(count) if travel == 'forward' else range(count - 1, -1, -1)
            for i in indices:
                a, b = (nodes[i], nodes[i + 1]) if travel == 'forward' else (nodes[i + 1], nodes[i])
                result.append({'id': f'task:{digest}:{travel}:{i + 1}:{count}',
                               'physical_task_id': f'physical-task:{digest}:{i + 1}:{count}',
                               'segment_id': identifier, 'direction': travel, 'length_km': lengths[i],
                               'start_node_id': a, 'end_node_id': b,
                               'start_service_allowed': station_index[a]['service_allowed'] if a in station_index else False,
                               'end_service_allowed': station_index[b]['service_allowed'] if b in station_index else False})
    return result


def validate_task_nodes(project: dict) -> None:
    """Validate task references and virtual-node origin without requiring a split limit."""
    stations = {s['id']: s for s in project['stations']}
    segments = {s['id']: s for s in project['segments']}
    for task in project['tasks']:
        segment_id = task.get('segment_id')
        if not isinstance(segment_id, str) or segment_id not in segments:
            raise ValueError('Unknown task segment reference')
        segment = segments[segment_id]
        direction = task.get('direction')
        if direction not in ('forward', 'reverse') or segment['direction'] not in ('both', direction):
            raise ValueError('Task direction conflicts with segment')
        number(task.get('length_km'), 'task.length_km', positive=True)
        if task['length_km'] > segment['length_km']:
            raise ValueError('Task length exceeds segment')
        for side in ('start', 'end'):
            node = nonempty(task.get(f'{side}_node_id'), 'task node')
            allowed = task.get(f'{side}_service_allowed')
            if type(allowed) is not bool:
                raise ValueError('Task service permission must be boolean')
            if node in stations:
                if node not in (segment['start_station_id'], segment['end_station_id']):
                    raise ValueError('Task station is outside its segment')
                if allowed and not stations[node]['service_allowed']:
                    raise ValueError('Task enables service at a forbidden station')
            else:
                try:
                    prefix, digest, boundary, parts = node.split(':')
                    valid = (prefix == 'virtual' and 0 < int(boundary) < int(parts)
                             and int(parts) <= MAX_GENERATED_TASKS
                             and node == _virtual(segment_id, int(boundary), int(parts)))
                except (ValueError, TypeError):
                    valid = False
                if not valid or allowed:
                    raise ValueError('Unknown virtual node or virtual node service forbidden')
