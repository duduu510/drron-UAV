"""Independent basic diagnostics, deliberately insufficient for publication."""
from collections import Counter, defaultdict
import math

from vde_inspect.solver.adapter import get_solution_events, validate_envelope
from vde_inspect.simulation.engine import _identifier


def _entity_ids(project, collection):
    rows = project.get(collection, [])
    if not isinstance(rows, list):
        raise ValueError(f"{collection} 必须是数组")
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{collection} 条目必须是对象")
        identity = _identifier(row.get("id"), f"{collection}.id")
        if identity in identifiers:
            raise ValueError(f"{collection} 含重复 ID: {identity}")
        identifiers.add(identity)
    return identifiers


def validate_solution(solution: dict, project: dict) -> dict:
    """Ignore imported pass flags; unknown operational checks fail closed.

    Coverage counts explicit task_id/task_ids references per physical group;
    directional candidates are alternatives and each group must occur once.
    Legacy tasks without physical_task_id each form their own group. This
    does not prove geometric coverage or task execution. Energy checks validate
    SOC ranges and continuity, never a physical model or battery feasibility.
    """
    checks, violations = [], []

    def record(name, status, message):
        check = {"name": name, "status": status, "message": message}
        checks.append(check)
        if status == "fail":
            violations.append({"check": name, "message": message})

    try:
        validate_envelope(solution)
    except (ValueError, TypeError) as exc:
        record("schema", "fail", str(exc))
        events = None
    else:
        record("schema", "pass", "标识、时间单位与 SOC 范围有效")
        events = get_solution_events(solution)

    if not isinstance(project, dict):
        record("identity", "fail", "项目必须是对象")
        project = {}
    if (not isinstance(solution, dict) or not project.get("project_id") or
            not project.get("input_hash") or
            solution.get("project_id") != project.get("project_id") or
            solution.get("input_hash") != project.get("input_hash")):
        record("identity", "fail", "方案与当前项目或输入快照不匹配")
    else:
        record("identity", "pass", "方案关联当前输入快照")

    try:
        expected = _entity_ids(project, "tasks")
        task_groups = {task["id"]: _identifier(task.get("physical_task_id", task["id"]),
                                              "tasks.physical_task_id")
                       for task in project.get("tasks", [])}
        devices = _entity_ids(project, "vehicles") | _entity_ids(project, "drones")
    except ValueError as exc:
        record("project_schema", "fail", str(exc))
        events = None

    if events is not None:
        assigned = []
        by_device = defaultdict(list)
        for event in events:
            by_device[event["device_id"]].append(event)
            assigned.extend(event.get("task_ids", []))
            if "task_id" in event:
                assigned.append(event["task_id"])
        actual = set(assigned)
        counts = Counter(task_groups[task_id] for task_id in assigned if task_id in expected)
        missing = set(task_groups.values()) - counts.keys()
        repeated = {group: count for group, count in sorted(counts.items()) if count > 1}
        unknown = actual - expected
        if missing or unknown or repeated:
            record("coverage", "fail", f"未覆盖物理任务组: {sorted(missing)}；"
                   f"未知任务: {sorted(unknown)}；重复检查物理任务组: {repeated}")
        elif not expected:
            record("coverage", "unknown", "项目无任务，无法证明任务覆盖")
        else:
            record("coverage", "pass", "每个物理任务组恰有一个方向的显式事件引用；未证明几何覆盖")

        overlaps, discontinuities = [], []
        for device, schedule in sorted(by_device.items()):
            schedule.sort(key=lambda event: (event["start_min"], event["end_min"], event["event_id"]))
            latest_end = -1
            previous = None
            for event in schedule:
                if event["start_min"] < latest_end:
                    overlaps.append(event["event_id"])
                latest_end = max(latest_end, event["end_min"])
                if previous is not None and not math.isclose(
                        previous["soc_end"], event["soc_start"], abs_tol=1e-6, rel_tol=0):
                    discontinuities.append(event["event_id"])
                previous = event
        record("time", "fail" if overlaps else "pass",
               f"同设备事件重叠: {overlaps}" if overlaps else "事件时间有效且无同设备重叠")
        record("energy", "fail" if discontinuities else "pass",
               f"SOC 不连续（缺失中间事件也会触发）: {discontinuities}" if discontinuities else "SOC 范围及相邻事件连续性有效")
        unknown_devices = set(by_device) - devices
        if unknown_devices:
            record("device_references", "fail", f"未知设备: {sorted(unknown_devices)}")
        elif events:
            record("device_references", "pass", "事件设备属于项目")
        else:
            record("device_references", "unknown", "无事件可验证设备引用")

    for name, message in (
        ("operational_coverage", "未验证方向、几何、重复作业与任务完成语义"),
        ("resource_constraints", "未验证载荷、机库、换电、库存和设备兼容性"),
        ("physical_energy", "未接入真实能耗模型、充换电和续航约束"),
        ("safety", "未验证会合、服务节点、禁飞或安全规则"),
        ("objective", "未独立复算目标函数与全部成本"),
    ):
        record(name, "unknown", message)
    return {"passed": False, "publishable": False, "checks": checks, "violations": violations}
