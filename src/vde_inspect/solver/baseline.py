"""Research simulation: seeded greedy inspection with station-return sorties.

The undirected railway is a ground-distance proxy, not a road routing dataset.
This deliberately conservative model makes no operational or optimality claim.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import heapq
import math
import random
from uuid import uuid4

from vde_inspect.domain.project import input_hash, nonempty, normalize_project, number
from vde_inspect.services.tasks import generate_tasks

DEFAULT_CONFIG = dict(team_count=4, max_length_km=.5, window_min=240, seed=7,
    vehicle_speed_kmh=30, drone_speed_kmh=18, drone_endurance_min=40,
    vehicle_range_km=100, drone_min_soc=20, vehicle_min_soc=10,
    swap_min=2, swap_stock=8, launch_min=.5, land_min=.5,
    vehicle_fixed_yuan=400, drone_fixed_yuan=50, vehicle_km_yuan=1.5,
    vehicle_min_yuan=1, swap_yuan=6, assume_service_at_all_stations=False)


def normalize_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError('Baseline config must be an object')
    unknown = set(config) - set(DEFAULT_CONFIG) - {'depot_station_id'}
    if unknown:
        raise ValueError(f'Unknown baseline config fields: {sorted(unknown)}')
    result = dict(DEFAULT_CONFIG, **config)
    if result['assume_service_at_all_stations'] is not True:
        raise ValueError('Research-only simulation requires explicit '
                         'assume_service_at_all_stations=True; actual service permission is unknown')
    nonempty(result.get('depot_station_id'), 'depot_station_id')
    for key in ('team_count', 'swap_stock', 'seed'):
        value = result[key]
        if type(value) is not int or value < (1 if key == 'team_count' else 0):
            raise ValueError(f'{key} must be a valid integer')
    if result['team_count'] > 64:
        raise ValueError('team_count must be 1..64')
    positive = {'max_length_km', 'window_min', 'vehicle_speed_kmh', 'drone_speed_kmh',
                'drone_endurance_min', 'vehicle_range_km'}
    for key in set(DEFAULT_CONFIG) - {'team_count', 'swap_stock', 'seed', 'assume_service_at_all_stations'}:
        value = number(result[key], key, positive=key in positive)
        if value < 0 or (key.endswith('_soc') and value >= 100):
            raise ValueError(f'{key} is outside its allowed range')
    return result


def _graph(project):
    graph = {station['id']: [] for station in project['stations']}
    for segment in project['segments']:
        a, b, distance = segment['start_station_id'], segment['end_station_id'], segment['length_km']
        graph[a].append((b, distance))
        graph[b].append((a, distance))
    for edges in graph.values():
        edges.sort()
    return graph


def _check_connected(project, depot):
    graph = _graph(project)
    if depot not in graph:
        raise ValueError('Depot must be an actual station')
    visited, pending = {depot}, [depot]
    while pending:
        for neighbor, _ in graph[pending.pop()]:
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    if visited != set(graph):
        raise ValueError('Baseline requires a connected station network')


def prepare_baseline_project(source: dict, config: dict) -> dict:
    cfg = normalize_config(config)
    original = normalize_project(source)
    _check_connected(original, cfg['depot_station_id'])
    if not original['segments']:
        raise ValueError('Baseline requires at least one real segment')
    project = deepcopy(original)
    project.update(project_id=str(uuid4()), name=original['name'] + '｜仿真基线', revision=1,
                   baseline_config=cfg,
                   baseline_provenance=dict(source_project_id=original['project_id'],
                                            source_input_hash=original['input_hash'],
                                            source_name=original['name']))
    for station in project['stations']:
        station['service_allowed'] = True
    project['tasks'] = generate_tasks(project, cfg['max_length_km'])
    project['depots'] = [dict(id='simulation-depot', name='仿真基地', station_id=cfg['depot_station_id'])]
    project['vehicle_models'] = [dict(id='simulation-vehicle-model', name='仿真车辆', capacity=1,
        battery_count=max(1, cfg['swap_stock']), range_km=cfg['vehicle_range_km'])]
    project['drone_models'] = [dict(id='simulation-drone-model', name='仿真无人机',
        endurance_min=cfg['drone_endurance_min'])]
    for collection, singular in (('vehicles', 'vehicle'), ('drones', 'drone')):
        project[collection] = [dict(id=f'simulation-{singular}-{i + 1:02}',
            model_id=f'simulation-{singular}-model', depot_id='simulation-depot')
            for i in range(cfg['team_count'])]
    project['batteries'] = [dict(id='simulation-spares', name='仿真备用电池',
        quantity=cfg['swap_stock'] * cfg['team_count'], compatible_models=['simulation-drone-model'])]
    project['cost_config'] = {key: value for key, value in cfg.items() if key.endswith('_yuan')}
    project['safety_config'] = dict(baseline_simulation=True, drone_min_soc=cfg['drone_min_soc'],
                                    vehicle_min_soc=cfg['vehicle_min_soc'])
    return normalize_project(project)


def solve_baseline(project: dict, config: dict, *, run_id: str | None = None,
                   solution_id: str | None = None, progress=None) -> dict:
    cfg = normalize_config(config)
    p = normalize_project(project)
    if (p.get('baseline_config') != cfg or not p.get('baseline_provenance') or
            not p['safety_config'].get('baseline_simulation') or
            project.get('input_hash') != input_hash(p)):
        raise ValueError('Baseline requires the unchanged prepared simulation project and config')
    if p['tasks'] != generate_tasks(p, cfg['max_length_km']):
        raise ValueError('Prepared baseline tasks differ from generated tasks')
    if len(p['vehicles']) != cfg['team_count'] or len(p['drones']) != cfg['team_count']:
        raise ValueError('Prepared baseline resource count differs from config')
    depot = cfg['depot_station_id']
    _check_connected(p, depot)
    graph, cache = _graph(p), {}

    def shortest(start, end):
        if start not in cache:
            distances, paths = {start: 0.0}, {start: [start]}
            queue = [(0.0, start)]
            while queue:
                distance, node = heapq.heappop(queue)
                if distance != distances[node]:
                    continue
                for neighbor, length in graph[node]:
                    value = distance + length
                    if value < distances.get(neighbor, math.inf):
                        distances[neighbor] = value
                        paths[neighbor] = paths[node] + [neighbor]
                        heapq.heappush(queue, (value, neighbor))
            cache[start] = distances, paths
        return cache[start][0][end], cache[start][1][end]

    segments = {s['id']: s for s in p['segments']}
    groups = defaultdict(list)
    for task in p['tasks']:
        groups[task['physical_task_id']].append(task)
    # Keep pieces of an original interval adjacent. Global physical-piece
    # shuffling wastes ground travel by repeatedly crossing the same network.
    # Both segment order and its physical-piece order remain seeded.
    segment_order = sorted(segments)
    rng = random.Random(cfg['seed'])
    rng.shuffle(segment_order)
    by_segment = defaultdict(list)
    for physical in sorted(groups):
        by_segment[groups[physical][0]['segment_id']].append(physical)
    order = []
    for segment_id in segment_order:
        pieces = by_segment[segment_id]
        rng.shuffle(pieces)
        order.extend(pieces)
    teams = [dict(vehicle=v['id'], drone=d['id'], node=depot, time=0.0,
                  vsoc=100.0, dsoc=100.0, stock=cfg['swap_stock'], used=False)
             for v, d in zip(p['vehicles'], p['drones'])]
    events, sorties, unscheduled = [], [], []
    distance_total, swap_total = 0.0, 0
    covered = set()

    def event(team, device, kind, start, end, a, b, soc_start, soc_end, **extra):
        if end <= start:
            return
        events.append(dict(event_id=f'event-{len(events) + 1:07}', device_id=team[device],
            event_type=kind, start_min=start, end_min=end, from_node_id=a, to_node_id=b,
            soc_start=soc_start, soc_end=soc_end, vehicle_id=team['vehicle'],
            drone_id=team['drone'], **extra))

    def drive(team, destination):
        nonlocal distance_total
        distance, path = shortest(team['node'], destination)
        end = team['time'] + distance / cfg['vehicle_speed_kmh'] * 60
        after = team['vsoc'] - distance / cfg['vehicle_range_km'] * 100
        event(team, 'vehicle', 'drive', team['time'], end, team['node'], destination,
              team['vsoc'], after, distance_km=distance, path_node_ids=path)
        event(team, 'drone', 'ride', team['time'], end, team['node'], destination,
              team['dsoc'], team['dsoc'], distance_km=distance, path_node_ids=path)
        team.update(time=end, node=destination, vsoc=after)
        distance_total += distance

    def offset(node, segment):
        if node == segment['start_station_id']:
            return 0.0
        if node == segment['end_station_id']:
            return segment['length_km']
        _, _, boundary, parts = node.split(':')
        return segment['length_km'] * int(boundary) / int(parts)

    def report(processed):
        if progress:
            progress(dict(type='progress', processed=processed, total=len(order),
                          completed=len(covered), message=f'已处理 {processed}/{len(order)} 个物理任务'))

    report(0)
    for processed, physical in enumerate(order, 1):
        choices = []
        for task in sorted(groups[physical], key=lambda t: t['id']):
            segment = segments[task['segment_id']]
            for launch in sorted({segment['start_station_id'], segment['end_station_id']}):
                anchor = offset(launch, segment)
                outbound = abs(offset(task['start_node_id'], segment) - anchor)
                inbound = abs(offset(task['end_node_id'], segment) - anchor)
                flight_distance = outbound + task['length_km'] + inbound
                active = flight_distance / cfg['drone_speed_kmh'] * 60 + cfg['launch_min'] + cfg['land_min']
                depletion = active / cfg['drone_endurance_min'] * 100
                if 100 - depletion < cfg['drone_min_soc']:
                    continue
                return_distance, _ = shortest(launch, depot)
                for index, team in enumerate(teams):
                    distance, _ = shortest(team['node'], launch)
                    swap = team['dsoc'] - depletion < cfg['drone_min_soc']
                    if swap and not team['stock']:
                        continue
                    # A configured instantaneous swap uses one nanominute so every
                    # emitted action has a positive interval and SOC stays explicit.
                    swap_time = max(cfg['swap_min'], 1e-9) if swap else 0
                    finish = team['time'] + distance / cfg['vehicle_speed_kmh'] * 60 + swap_time + active
                    projected = finish + return_distance / cfg['vehicle_speed_kmh'] * 60
                    if (projected > cfg['window_min'] or
                        team['vsoc'] - (distance + return_distance) / cfg['vehicle_range_km'] * 100 < cfg['vehicle_min_soc']):
                        continue
                    choices.append(((projected, index, task['id'], launch), team, task,
                                    launch, outbound, inbound, active, swap, swap_time))
        if not choices:
            unscheduled.append(dict(physical_task_id=physical,
                reason='No team satisfies sortie endurance, battery stock, return SOC and time window'))
        else:
            _, team, task, launch, outbound, inbound, active, swap, swap_time = min(choices, key=lambda c: c[0])
            team['used'] = True
            drive(team, launch)
            if swap:
                end = team['time'] + swap_time
                event(team, 'drone', 'swap', team['time'], end, launch, launch,
                      team['dsoc'], 100.0, battery_quantity=1)
                event(team, 'vehicle', 'wait', team['time'], end, launch, launch,
                      team['vsoc'], team['vsoc'])
                team.update(dsoc=100.0, time=end, stock=team['stock'] - 1)
                swap_total += 1
            start = team['time']
            sortie_id = f'sortie-{len(sorties) + 1:06}'
            actions = [('launch', cfg['launch_min'], launch, launch, 0),
                ('fly', outbound / cfg['drone_speed_kmh'] * 60, launch, task['start_node_id'], outbound),
                ('inspect', task['length_km'] / cfg['drone_speed_kmh'] * 60,
                 task['start_node_id'], task['end_node_id'], task['length_km']),
                ('fly', inbound / cfg['drone_speed_kmh'] * 60, task['end_node_id'], launch, inbound),
                ('land', cfg['land_min'], launch, launch, 0)]
            for kind, duration, a, b, length in actions:
                if not duration:
                    continue
                end = team['time'] + duration
                after = team['dsoc'] - duration / cfg['drone_endurance_min'] * 100
                extra = dict(sortie_id=sortie_id, distance_km=length, segment_id=task['segment_id'])
                if kind == 'inspect':
                    extra.update(task_ids=[task['id']], physical_task_id=physical)
                event(team, 'drone', kind, team['time'], end, a, b, team['dsoc'], after, **extra)
                team.update(time=end, dsoc=after)
            event(team, 'vehicle', 'wait', start, team['time'], launch, launch,
                  team['vsoc'], team['vsoc'], sortie_id=sortie_id)
            sorties.append(dict(sortie_id=sortie_id, drone_id=team['drone'], vehicle_id=team['vehicle'],
                launch_station_id=launch, recovery_station_id=launch, start_min=start, end_min=team['time'],
                task_ids=[task['id']], physical_task_id=physical,
                flight_distance_km=outbound + task['length_km'] + inbound, active_min=active))
            covered.add(physical)
        if processed % 10 == 0 or processed == len(order):
            report(processed)
    for team in teams:
        if team['used']:
            drive(team, depot)
    used = [team for team in teams if team['used']]
    cost = dict(vehicle_fixed=len(used) * cfg['vehicle_fixed_yuan'],
        drone_fixed=len(used) * cfg['drone_fixed_yuan'],
        vehicle_time=math.fsum(t['time'] for t in used) * cfg['vehicle_min_yuan'],
        vehicle_distance=distance_total * cfg['vehicle_km_yuan'], battery_swap=swap_total * cfg['swap_yuan'])
    complete = len(covered) == len(order) and bool(order)
    segment_groups = defaultdict(set)
    for task in p['tasks']:
        segment_groups[task['segment_id']].add(task['physical_task_id'])
    result = dict(schema_version='1.0', run_id=run_id or str(uuid4()),
        solution_id=solution_id or str(uuid4()), project_id=p['project_id'], input_hash=p['input_hash'],
        source_mode='simulation', algorithm_version='greedy-station-return/0.1', complete=complete,
        validation_passed=False, publishable=False,
        vehicles=[deepcopy(v) for v in p['vehicles'] if any(t['vehicle'] == v['id'] for t in used)],
        drones=[deepcopy(d) for d in p['drones'] if any(t['drone'] == d['id'] for t in used)],
        sorties=sorties, schedule_events=sorted(events, key=lambda e: (e['start_min'], e['end_min'], e['event_id'])),
        return_time_min=max((t['time'] for t in used), default=0),
        coverage=dict(physical_total=len(order), physical_completed=len(covered),
            directional_candidates=len(p['tasks']), directional_selected=len(covered),
            original_intervals=len(segment_groups),
            original_intervals_completed=sum(group <= covered for group in segment_groups.values())),
        cost_breakdown_yuan=cost, unscheduled_tasks=unscheduled,
        model_assumptions=dict(config=cfg, road_proxy='Undirected railway shortest-distance proxy; no road dataset',
            original_project=deepcopy(p['baseline_provenance']),
            service='All original stations allowed by explicit research-only assumption; virtual nodes never service',
            energy='Linear distance/range vehicle SOC; linear active minutes/endurance drone SOC; no recharge',
            resources='One drone per vehicle; per-team spare stock; no cross-vehicle transfer',
            sortie='Vehicle waits; drone returns to same original launch station; depot return reserved',
            zero_swap_time='Configured zero swap duration represented by 1e-9 min for explicit SOC event',
            scope='Simulation only; no passenger timetables, real-time telemetry, operational dispatch or optimality claim'))
    result['cost_total_yuan' if complete else 'cost_partial_yuan'] = math.fsum(cost.values())
    return result
