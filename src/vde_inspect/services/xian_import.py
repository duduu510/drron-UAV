"""Convert an explicitly supplied OpenMetro Xi'an ZIP without extracting it."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5
import zipfile

from vde_inspect.domain.project import canonical_bytes, nonempty, normalize_project, number
from vde_inspect.services.tasks import generate_tasks

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
REQUIRED = ('lines', 'stations', 'segments', 'stops')


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _read_records(archive, member, label):
    try:
        with archive.open(member) as stream:
            raw = stream.read(MAX_MEMBER_BYTES + 1)
        if len(raw) > MAX_MEMBER_BYTES:
            raise ValueError('Archive member exceeds size limit')
        envelope = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_pairs)
        canonical_bytes(envelope)  # Reject NaN/Infinity and excessive nesting.
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f'Invalid {label}.json') from exc
    if not isinstance(envelope, dict) or envelope.get('network_id') != 'cn-xian':
        raise ValueError(f'{label}.json must identify network_id cn-xian')
    rows = envelope.get('records')
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'{label}.records must be a nonempty array')
    index = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'{label} record must be an object')
        identifier = nonempty(row.get('id'), f'{label}.id')
        if identifier in index:
            raise ValueError(f'Duplicate {label} ID: {identifier}')
        index[identifier] = row
    return rows, index, {key: value for key, value in envelope.items() if key != 'records'}


def load_xian_archive(path: Path) -> dict:
    """Return a validated project; this function never writes a workspace or extracts files."""
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Archive exceeds 32 MiB size limit')
    archive_bytes = path.read_bytes()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError('Archive exceeds member count or expanded size limit')
            by_basename = {}
            names = set()
            for member in members:
                name = member.filename
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith('/') or '\\' in name or ':' in name
                        or '..' in parts or name in names):
                    raise ValueError('Unsafe or duplicate archive member path')
                names.add(name)
                if member.file_size > MAX_MEMBER_BYTES or member.flag_bits & 1:
                    raise ValueError('Oversized or encrypted archive member')
                basename = PurePosixPath(name).name
                if basename in {label + '.json' for label in REQUIRED}:
                    if basename in by_basename:
                        raise ValueError('Ambiguous duplicate source JSON files')
                    by_basename[basename] = member
            rows, indices, envelopes = {}, {}, {}
            for label in REQUIRED:
                member = by_basename.get(label + '.json')
                if member is None:
                    raise ValueError(f'Missing {label}.json')
                rows[label], indices[label], envelopes[label] = _read_records(archive, member, label)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError(f'Invalid or unsupported Xi\'an archive: {exc}') from exc

    lines = []
    for source in rows['lines']:
        line = dict(source)
        if line.get('color') is None or line.get('color') == '':
            line.update(source_color=line.get('color'), color='#808080',
                        color_source='display_fallback_missing_source')
        lines.append(line)

    station_lines = {identifier: [] for identifier in indices['stations']}
    for stop in rows['stops']:
        station_id = nonempty(stop.get('station_id'), 'stop.station_id')
        line_id = nonempty(stop.get('line_id'), 'stop.line_id')
        if station_id not in station_lines or line_id not in indices['lines']:
            raise ValueError('Stop has an unknown station or line reference')
        if line_id not in station_lines[station_id]:
            station_lines[station_id].append(line_id)

    stations = []
    for source in rows['stations']:
        line_ids = station_lines[source['id']]
        if not line_ids:
            raise ValueError('Station has no referenced line stop')
        schematic = source.get('schematic')
        if schematic is not None and not isinstance(schematic, dict):
            raise ValueError('station.schematic must be an object')
        schematic = schematic or {}
        stations.append({**source, 'line_id': line_ids[0], 'line_ids': line_ids,
                         'x': schematic.get('x'), 'y': schematic.get('y'),
                         'coordinate_type': 'schematic', 'service_allowed': False,
                         'service_status_source': 'not_supplied'})

    segments = []
    for source in rows['segments']:
        line_id = nonempty(source.get('line_id'), 'segment.line_id')
        start = nonempty(source.get('from_station_id'), 'from_station_id')
        end = nonempty(source.get('to_station_id'), 'to_station_id')
        if line_id not in indices['lines'] or start not in station_lines or end not in station_lines:
            raise ValueError('Segment has unknown line or station references')
        if line_id not in station_lines[start] or line_id not in station_lines[end]:
            raise ValueError('Segment station is not served by its line')
        for stop_key, station_id in (('from_stop_id', start), ('to_stop_id', end)):
            stop_id = nonempty(source.get(stop_key), stop_key)
            stop = indices['stops'].get(stop_id)
            if stop is None or stop['station_id'] != station_id or stop['line_id'] != line_id:
                raise ValueError('Segment stop reference conflicts with its station or line')
        extras = source.get('extras', {})
        if not isinstance(extras, dict):
            raise ValueError('segment.extras must be an object')
        if 'travel_time_seconds' in source:
            number(source['travel_time_seconds'], 'travel_time_seconds', positive=True)
        segments.append({**source, 'start_station_id': start, 'end_station_id': end,
                         'length_km': source.get('distance_km'),
                         'direction': source.get('direction', 'both'),
                         'distance_source': extras.get('distance_source', 'not_supplied'),
                         'travel_time_semantics': 'passenger_train'})

    metadata = {
        'format': 'OpenMetro', 'network_id': 'cn-xian', 'archive_sha256': digest,
        'record_counts': {label: len(rows[label]) for label in REQUIRED},
        'coordinate_type': 'schematic', 'source_envelopes': envelopes,
        'notes': [
            '站点 x/y 仅使用原包 schematic 坐标，不将经纬度当作示意图坐标。',
            '原包未提供巡检起降、充换电服务许可，所有站点 service_allowed=False，待人工确认。',
            'distance_source=haversine 为地理直线距离估计，不是核验后的轨道里程。',
            'travel_time_seconds 为原包客运列车时间，不用作巡检车辆行驶时间或无人机飞行时间。',
            f'本包实有 {len(segments)} 个区段；交接文档的 274 区段与 1011 任务为待核验目标，不裁剪或补造数据。',
            '未导入或推定车辆、无人机、电池、基地和真实求解结果。',
            '缺少原始线路颜色时仅使用灰色显示，并标记 display_fallback_missing_source；不代表官方线路色。',
        ],
    }
    project = normalize_project({
        'project_id': str(uuid5(NAMESPACE_URL, f'openmetro:cn-xian:sha256:{digest}')),
        'name': '西安地铁线网（导入数据）', 'lines': lines,
        'stations': stations, 'segments': segments, 'source_metadata': metadata,
    })
    metadata = project['source_metadata']
    metadata['total_length_km'] = math.fsum(segment['length_km'] for segment in project['segments'])
    candidates = generate_tasks(project, .5)
    metadata['task_assessment'] = {'max_length_km': .5,
                                   'count': len(candidates),
                                   'directional_candidate_count': len(candidates),
                                   'physical_task_count': len({task['physical_task_id'] for task in candidates}),
                                   'direction_policy': 'preserve_source_direction',
                                   'coverage_policy': 'execute_each_physical_task_once_in_one_allowed_direction',
                                   'committed': False}
    return normalize_project(project)
