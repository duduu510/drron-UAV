"""Adapters preserve immutable source IDs and expose offline provenance."""
import json
from pathlib import Path
import re
from typing import Protocol, runtime_checkable

from vde_inspect.simulation.engine import _identifier, _number, validate_events


@runtime_checkable
class SolverAdapter(Protocol):
    available: bool
    reason: str

    def solve(self, request: dict) -> dict: ...


class UnavailableSolverAdapter:
    available = False
    reason = "待真实求解器接入"

    def solve(self, request: dict) -> dict:
        raise RuntimeError(self.reason)


def get_solution_events(solution: dict) -> list[dict]:
    """Read canonical schedule_events or the legacy events alias, fail closed.

    An explicit empty array is valid; an absent array is not inferred. When
    both fields exist they must independently validate and contain identical
    records. The returned list is detached so consumers cannot change the
    supplied snapshot through playback or diagnostics.
    """
    if not isinstance(solution, dict):
        raise ValueError("方案必须是 JSON 对象")
    canonical_present = "schedule_events" in solution
    legacy_present = "events" in solution
    if not canonical_present and not legacy_present:
        raise ValueError("方案必须包含实际 schedule_events 数组")
    if canonical_present:
        canonical = validate_events(solution["schedule_events"])
        if legacy_present:
            legacy = validate_events(solution["events"])
            if canonical != legacy:
                raise ValueError("schedule_events 与旧字段 events 内容冲突")
        return canonical
    return validate_events(solution["events"])


def validate_envelope(payload):
    if not isinstance(payload, dict):
        raise ValueError("方案必须是 JSON 对象")
    for field in ("run_id", "solution_id", "project_id"):
        _identifier(payload.get(field), field)
    digest = payload.get("input_hash")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise ValueError("input_hash 必须是 SHA256")
    if payload.get("source_mode") not in ("precomputed", "solver", "simulation"):
        raise ValueError("source_mode 必须为 precomputed/solver/simulation")
    for field in ("cost_total_yuan", "return_time_min"):
        if field in payload:
            _number(payload[field], field)
    for field in ("complete", "validation_passed", "publishable"):
        if field in payload and not isinstance(payload[field], bool):
            raise ValueError(f"{field} 必须是布尔值")
    for field in ("vehicles", "drones", "sorties"):
        if field in payload and not isinstance(payload[field], list):
            raise ValueError(f"{field} 必须是数组")
    if "coverage" in payload:
        coverage = payload["coverage"]
        if not isinstance(coverage, dict):
            raise ValueError("coverage 必须是对象")
        for field, value in coverage.items():
            if not isinstance(field, str):
                raise ValueError("coverage 字段名必须是字符串")
            is_count = (field in ("intervals", "tasks", "subtasks", "total", "completed", "remaining") or
                        field.endswith(("_count", "_intervals", "_tasks", "_subtasks")))
            if is_count and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"coverage.{field} 必须是非负整数")
    get_solution_events(payload)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"JSON 不支持非有限数值: {value}")


def load_fixture(path: Path) -> dict:
    """Load an offline result, never representing it as a newly computed run.

    Imported flags remain source data only. The application must always use
    validate_solution against the active project to obtain validation status.
    """
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError("方案文件超过 25 MiB")
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"无效方案 JSON: {exc}") from exc
    validate_envelope(payload)
    payload["schedule_events"] = get_solution_events(payload)
    payload.pop("events", None)
    payload["provenance_label"] = {
        "precomputed": "预计算离线结果", "solver": "求解器结果导入（离线）",
        "simulation": "仿真结果导入（离线）",
    }[payload["source_mode"]]
    return payload
