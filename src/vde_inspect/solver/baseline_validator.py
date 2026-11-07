"""Independent reconstruction of the conservative simulation model.

No imports from the scheduling algorithm: geometry, distances, energy and costs
are reconstructed from the frozen project rather than trusting solver metrics.
"""
from collections import Counter, defaultdict
import hashlib
import heapq
import math

from vde_inspect.solver.adapter import get_solution_events, validate_envelope


def validate_baseline_solution(solution: dict, project: dict, config: dict) -> dict:
    checks, violations = [], []

    def require(condition, name, message):
        if not condition:
            violations.append({'check': name, 'message': message})

    def same(actual, expected):
        return (type(actual) in (int, float) and math.isfinite(actual) and
                math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-7))

    def collection(key):
        rows = project[key]
        if not isinstance(rows, list):
            raise ValueError(f'{key} must be an array')
        index = {row['id']: row for row in rows}
        if len(index) != len(rows):
            raise ValueError(f'duplicate {key} IDs')
        return index

    try:
        validate_envelope(solution)
        events = get_solution_events(solution)
        stations, segments, tasks = (collection(k) for k in ('stations', 'segments', 'tasks'))
        vehicles, drones = (collection(k) for k in ('vehicles', 'drones'))
        depot = config['depot_station_id']
        # Access every physical-model parameter up front: malformed inputs fail closed.
        for key in ('vehicle_speed_kmh', 'drone_speed_kmh', 'drone_endurance_min',
                    'vehicle_range_km', 'window_min', 'vehicle_min_soc', 'drone_min_soc',
                    'launch_min', 'land_min', 'swap_min', 'swap_stock', 'vehicle_fixed_yuan',
                    'drone_fixed_yuan', 'vehicle_km_yuan', 'vehicle_min_yuan', 'swap_yuan'):
            value = config[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'invalid config {key}')
        for key in ('vehicle_speed_kmh', 'drone_speed_kmh', 'drone_endurance_min', 'vehicle_range_km'):
            if config[key] <= 0:
                raise ValueError(f'{key} must be positive')
        if not config.get('assume_service_at_all_stations') or depot not in stations:
            raise ValueError('explicit station service assumption and actual depot required')
        required = ('sorties', 'vehicles', 'drones', 'coverage', 'complete', 'return_time_min',
                    'cost_breakdown_yuan', 'unscheduled_tasks', 'model_assumptions')
        for key in required:
            if key not in solution:
                raise ValueError(f'missing solution field: {key}')
        require(solution['project_id'] == project['project_id'] and
                solution['input_hash'] == project['input_hash'], 'identity', '输入快照标识不匹配')
        require(solution['source_mode'] == 'simulation' and solution.get('publishable') is False
                and solution.get('validation_passed') is False, 'scope', '只能标记为仿真结果')
        require(solution['model_assumptions']['config'] == config and project['baseline_config'] == config,
                'scope', '声明的模型假设与冻结输入不一致')
        require(solution['model_assumptions']['original_project'] == project['baseline_provenance'] and
                bool(solution['model_assumptions']['road_proxy']), 'scope', '缺少原始项目来源或路网代理说明')
        graph = defaultdict(dict)
        for segment in segments.values():
            a, b, length = segment['start_station_id'], segment['end_station_id'], segment['length_km']
            if a not in stations or b not in stations or length <= 0:
                raise ValueError('invalid segment geometry')
            graph[a][b] = min(graph[a].get(b, math.inf), length)
            graph[b][a] = min(graph[b].get(a, math.inf), length)

        cache = {}

        def shortest(source, target):
            if source not in cache:
                distances, pending = {source: 0.0}, [(0.0, source)]
                while pending:
                    distance, node = heapq.heappop(pending)
                    if distance > distances[node]:
                        continue
                    for neighbor, length in graph[node].items():
                        updated = distance + length
                        if updated < distances.get(neighbor, math.inf):
                            distances[neighbor] = updated
                            heapq.heappush(pending, (updated, neighbor))
                cache[source] = distances
            return cache[source].get(target, math.inf)

        def offset(node, segment):
            if node == segment['start_station_id']:
                return 0.0
            if node == segment['end_station_id']:
                return segment['length_km']
            prefix, digest, boundary, pieces = node.split(':')
            expected = hashlib.sha256(segment['id'].encode('utf-8')).hexdigest()
            if prefix != 'virtual' or digest != expected or not 0 < int(boundary) < int(pieces):
                raise ValueError('node is not on its declared segment')
            return segment['length_km'] * int(boundary) / int(pieces)

        groups = defaultdict(list)
        for task in tasks.values():
            groups[task['physical_task_id']].append(task)
            segment = segments[task['segment_id']]
            a, b = offset(task['start_node_id'], segment), offset(task['end_node_id'], segment)
            require(same(abs(b-a), task['length_km']), 'geometry', '任务片段长度错误')
            require((task['direction'] == 'forward' and b > a or task['direction'] == 'reverse' and b < a)
                    and segment['direction'] in ('both', task['direction']), 'geometry', '任务方向错误')
            for side in ('start', 'end'):
                node = task[f'{side}_node_id']
                require(not task[f'{side}_service_allowed'] or node in stations and stations[node]['service_allowed'],
                        'service', '虚拟节点或禁止站点提供服务')

        schedules, coverage, by_sortie = defaultdict(list), Counter(), defaultdict(list)
        drive_distance, swaps = 0.0, Counter()
        pairings = defaultdict(set)
        valid_types = {'drive', 'ride', 'wait', 'launch', 'fly', 'inspect', 'land', 'swap'}
        for event in events:
            device, kind = event['device_id'], event['event_type']
            schedules[device].append(event)
            duration = event['end_min'] - event['start_min']
            require(duration > 0, 'time', '基线事件必须有正时长')
            require(kind in valid_types, 'events', f'未知事件类型 {kind}')
            require(device in vehicles or device in drones, 'devices', '未知设备')
            require(event['vehicle_id'] in vehicles and event['drone_id'] in drones and
                    device in (event['vehicle_id'], event['drone_id']), 'devices', '事件所属设备配对错误')
            pairings[event['drone_id']].add(event['vehicle_id'])
            require(event['end_min'] <= config['window_min'] + 1e-7, 'window', '超出仿真时间窗')
            if event.get('sortie_id'):
                by_sortie[event['sortie_id']].append(event)
            expected_soc = event['soc_start']
            if kind in ('drive', 'ride'):
                path = event['path_node_ids']
                require(len(path) >= 2 and path[0] == event['from_node_id'] and path[-1] == event['to_node_id'],
                        'geometry', '地面路径端点错误')
                length = sum(graph[a].get(b, math.inf) for a, b in zip(path, path[1:]))
                require(same(length, event['distance_km']) and same(length, shortest(path[0], path[-1])),
                        'geometry', '地面距离不等于网络最短路径')
                require(same(duration, length / config['vehicle_speed_kmh'] * 60), 'time', '地面行驶时间错误')
                if kind == 'drive':
                    require(device in vehicles, 'devices', 'drive 必须属于车辆')
                    expected_soc -= length / config['vehicle_range_km'] * 100
                    drive_distance += length
                else:
                    require(device in drones, 'devices', 'ride 必须属于无人机')
                    matches = [other for other in events if other['event_type'] == 'drive' and
                               other['device_id'] == event.get('vehicle_id') and all(
                                   other[k] == event[k] for k in ('start_min', 'end_min', 'from_node_id', 'to_node_id'))]
                    require(len(matches) == 1, 'synchronization', '搭乘缺少同步车辆行驶')
            elif kind in ('launch', 'fly', 'inspect', 'land'):
                require(device in drones, 'devices', '飞行事件必须属于无人机')
                require(bool(event.get('sortie_id')), 'sorties', '飞行事件缺少架次引用')
                expected_soc -= duration / config['drone_endurance_min'] * 100
                if kind in ('launch', 'land'):
                    node = event['from_node_id']
                    require(node == event['to_node_id'] and node in stations and stations[node]['service_allowed'],
                            'service', '起降必须在允许服务的实际站点')
                    require(same(duration, config['launch_min' if kind == 'launch' else 'land_min']), 'time', '起降时长错误')
                else:
                    if kind == 'inspect':
                        ids = event['task_ids']
                        require(len(ids) == 1 and ids[0] in tasks, 'coverage', '检查事件必须对应一个允许方向')
                        task = tasks[ids[0]]
                        coverage[task['physical_task_id']] += 1
                        require(event['physical_task_id'] == task['physical_task_id'] and
                                event['segment_id'] == task['segment_id'] and
                                event['from_node_id'] == task['start_node_id'] and
                                event['to_node_id'] == task['end_node_id'], 'geometry', '检查事件未按任务方向覆盖片段')
                        segment = segments[task['segment_id']]
                    else:
                        segment = segments[event['segment_id']]
                    length = abs(offset(event['to_node_id'], segment) - offset(event['from_node_id'], segment))
                    require(same(length, event['distance_km']) and same(duration, length / config['drone_speed_kmh'] * 60),
                            'geometry', '飞行距离或时间错误')
            elif kind == 'swap':
                node = event['from_node_id']
                require(device in drones and node == event['to_node_id'] and node in stations and stations[node]['service_allowed'],
                        'service', '换电必须在允许服务的实际站点')
                require(same(duration, config['swap_min']), 'time', '换电时长错误')
                expected_soc = 100
                require(event['battery_quantity'] == 1, 'stock', '换电必须消耗一块备用电池')
                swaps[device] += 1
                waits = [other for other in events if other['device_id'] == event.get('vehicle_id') and
                         other['event_type'] == 'wait' and other['from_node_id'] == node and
                         other['start_min'] <= event['start_min'] and other['end_min'] >= event['end_min']]
                require(len(waits) == 1, 'synchronization', '换电缺少车辆等待')
            elif kind == 'wait':
                require(device in vehicles and event['from_node_id'] == event['to_node_id'], 'synchronization', '车辆等待位置错误')
            require(same(expected_soc, event['soc_end']), 'energy', '物理 SOC 消耗或换电错误')
            minimum = config['vehicle_min_soc'] if device in vehicles else config['drone_min_soc']
            require(min(event['soc_start'], event['soc_end']) >= minimum - 1e-7, 'energy', 'SOC 安全余量不足')
        require(all(value <= config['swap_stock'] for value in swaps.values()), 'stock', '单队换电库存不足')
        require(all(len(pairs) == 1 for pairs in pairings.values()) and
                len({next(iter(pairs)) for pairs in pairings.values()}) == len(pairings),
                'synchronization', '一车一机固定配对，不支持跨车转移')
        for device, schedule in schedules.items():
            schedule.sort(key=lambda e: (e['start_min'], e['end_min'], e['event_id']))
            require(same(schedule[0]['soc_start'], 100) and schedule[0]['from_node_id'] == depot,
                    'initial', '设备未从基地满电出发')
            if device in vehicles:
                require(same(schedule[0]['start_min'], 0), 'time', '使用车辆必须从零时刻开始完整记录')
            for left, right in zip(schedule, schedule[1:]):
                require(left['end_min'] <= right['start_min'] + 1e-7, 'time', '同设备事件重叠')
                if device in vehicles:
                    require(same(left['end_min'], right['start_min']), 'time', '车辆等待必须显式记录，时间线不可有缺口')
                require(left['to_node_id'] == right['from_node_id'] and same(left['soc_end'], right['soc_start']),
                        'continuity', '设备位置或 SOC 不连续')
            require(schedule[-1]['to_node_id'] == depot, 'return', '设备未返回基地')

        sorties = solution['sorties']
        require(isinstance(sorties, list), 'sorties', 'sorties 必须是数组')
        sortie_ids = [s['sortie_id'] for s in sorties]
        require(len(sortie_ids) == len(set(sortie_ids)), 'sorties', '重复 sortie_id')
        require(set(by_sortie) == set(sortie_ids), 'sorties', '架次引用错误')
        for sortie in sorties:
            launch, recovery = sortie['launch_station_id'], sortie['recovery_station_id']
            require(launch == recovery and launch in stations and stations[launch]['service_allowed'],
                    'service', '架次必须在同一允许的实际站点起降')
            flight = sorted([e for e in by_sortie[sortie['sortie_id']] if e['device_id'] == sortie['drone_id']],
                            key=lambda e: e['start_min'])
            require(bool(flight) and flight[0]['from_node_id'] == launch and flight[-1]['to_node_id'] == launch,
                    'sorties', '架次起降位置错误')
            require(same(flight[0]['start_min'], sortie['start_min']) and same(flight[-1]['end_min'], sortie['end_min']),
                    'sorties', '架次时间错误')
            for left, right in zip(flight, flight[1:]):
                require(same(left['end_min'], right['start_min']), 'sorties', '飞行架次内部存在缺失事件')
            require(all(e['event_type'] in ('launch', 'fly', 'inspect', 'land') for e in flight),
                    'sorties', '飞行架次含非飞行动作')
            for kind, expected in (('launch', int(config['launch_min'] > 0)), ('land', int(config['land_min'] > 0))):
                require(sum(e['event_type'] == kind for e in flight) == expected, 'sorties', '起降动作缺失或重复')
            if config['launch_min'] > 0:
                require(flight[0]['event_type'] == 'launch', 'sorties', '起飞必须是架次首动作')
            if config['land_min'] > 0:
                require(flight[-1]['event_type'] == 'land', 'sorties', '着陆必须是架次末动作')
            require(same(sortie['active_min'], sum(e['end_min']-e['start_min'] for e in flight)) and
                    same(sortie['flight_distance_km'], sum(e.get('distance_km', 0) for e in flight)),
                    'sorties', '架次活动时间或飞行距离统计错误')
            inspections = [e for e in flight if e['event_type'] == 'inspect']
            require(len(inspections) == 1 and inspections[0]['task_ids'] == sortie['task_ids'] and
                    inspections[0]['physical_task_id'] == sortie['physical_task_id'], 'sorties', '架次检查任务错误')
            if len(inspections) == 1:
                segment_id = tasks[inspections[0]['task_ids'][0]]['segment_id']
                segment = segments[segment_id]
                require(all(e['segment_id'] == segment_id for e in flight) and
                        launch in (segment['start_station_id'], segment['end_station_id']),
                        'geometry', '整个架次必须沿被检查区间飞行并在原始端点起降')
            wait = [e for e in by_sortie[sortie['sortie_id']] if e['device_id'] == sortie['vehicle_id'] and e['event_type'] == 'wait']
            require(len(wait) == 1 and wait[0]['from_node_id'] == launch and
                    same(wait[0]['start_min'], sortie['start_min']) and same(wait[0]['end_min'], sortie['end_min']),
                    'synchronization', '架次缺少同步车辆等待')
            require(all(e.get('vehicle_id') == sortie['vehicle_id'] and e.get('drone_id') == sortie['drone_id'] for e in flight),
                    'synchronization', '架次车辆/无人机不匹配')
        actual_vehicles = {device for device in schedules if device in vehicles}
        actual_drones = {device for device in schedules if device in drones}
        def used_ids(rows):
            return [row['id'] if isinstance(row, dict) else row for row in rows]
        require(set(used_ids(solution['vehicles'])) == actual_vehicles and len(used_ids(solution['vehicles'])) == len(actual_vehicles),
                'devices', '使用车辆清单错误')
        require(set(used_ids(solution['drones'])) == actual_drones and len(used_ids(solution['drones'])) == len(actual_drones),
                'devices', '使用无人机清单错误')
        require(all(count == 1 for count in coverage.values()) and set(coverage) <= set(groups), 'coverage', '物理片段重复或未知')
        complete = bool(groups) and set(coverage) == set(groups) and all(count == 1 for count in coverage.values())
        require(solution['complete'] is complete, 'coverage', '完成声明与实际物理覆盖不符')
        require(complete, 'completion', '不完整调度不能通过仿真基线校验')
        c = solution['coverage']
        segment_groups = defaultdict(set)
        for task in tasks.values():
            segment_groups[task['segment_id']].add(task['physical_task_id'])
        for key, expected in {'physical_total': len(groups), 'physical_completed': len(coverage),
                              'directional_candidates': len(tasks), 'directional_selected': sum(coverage.values()),
                              'original_intervals': len(segments),
                              'original_intervals_completed': sum(group <= set(coverage) for group in segment_groups.values())}.items():
            require(c[key] == expected, 'coverage', f'覆盖统计 {key} 错误')
        expected_unscheduled = set(groups) - set(coverage)
        require({row['physical_task_id'] for row in solution['unscheduled_tasks']} == expected_unscheduled,
                'coverage', '未调度任务清单错误')
        return_time = max((schedule[-1]['end_min'] for device, schedule in schedules.items() if device in vehicles), default=0)
        require(same(solution['return_time_min'], return_time), 'return', '返回时间统计错误')
        costs = {'vehicle_fixed': len(actual_vehicles) * config['vehicle_fixed_yuan'],
                 'drone_fixed': len(actual_drones) * config['drone_fixed_yuan'],
                 'vehicle_time': sum(max(e['end_min'] for e in schedules[device]) for device in actual_vehicles) * config['vehicle_min_yuan'],
                 'vehicle_distance': drive_distance * config['vehicle_km_yuan'],
                 'battery_swap': sum(swaps.values()) * config['swap_yuan']}
        require(set(solution['cost_breakdown_yuan']) == set(costs), 'cost', '成本必须恰好包含五项')
        for key, value in costs.items():
            require(same(solution['cost_breakdown_yuan'][key], value), 'cost', f'成本 {key} 复算不符')
        total_key = 'cost_total_yuan' if complete else 'cost_partial_yuan'
        require(same(solution.get(total_key), sum(costs.values())), 'cost', '合计成本错误')
        require(complete or 'cost_total_yuan' not in solution, 'cost', '不完整结果不能报告完整成本')
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, ZeroDivisionError) as exc:
        violations.append({'check': 'schema', 'message': str(exc)})
    for name in ('schema', 'identity', 'scope', 'geometry', 'service', 'coverage', 'time', 'energy',
                 'stock', 'initial', 'continuity', 'return', 'sorties', 'synchronization', 'devices',
                 'window', 'completion', 'cost'):
        failed = any(v['check'] == name for v in violations)
        checks.append({'name': name, 'status': 'fail' if failed else ('unknown' if any(v['check'] == 'schema' for v in violations) else 'pass')})
    return {'passed': not violations, 'checks': checks, 'violations': violations,
            'scope': 'simulation-baseline', 'publishable': False}
