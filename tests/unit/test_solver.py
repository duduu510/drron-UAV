import copy
import csv
import json

import pytest

from vde_inspect.solver.adapter import UnavailableSolverAdapter, load_fixture
from vde_inspect.solver.validator import validate_solution
from vde_inspect.report.export import export_events_csv, export_events_json
from vde_inspect.solver import adapter as adapter_module
from vde_inspect.report import export as export_module


def sample_solution():
    return {
        "run_id": "run-1", "solution_id": "solution-1", "project_id": "project-1",
        "input_hash": "a" * 64, "source_mode": "precomputed",
        "events": [{"event_id": "e1", "device_id": "v1", "event_type": "travel",
                    "start_min": 0, "end_min": 10, "soc_start": 100, "soc_end": 80,
                    "from_node_id": "a", "to_node_id": "b", "task_id": "t1"}],
    }


def write_fixture(tmp_path, payload):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_solver_refuses_run():
    adapter = UnavailableSolverAdapter()
    assert adapter.available is False
    with pytest.raises(RuntimeError, match="待真实求解器接入"):
        adapter.solve({})


def test_offline_loader_preserves_identity_and_labels_origin(tmp_path):
    payload = sample_solution()
    loaded = load_fixture(write_fixture(tmp_path, payload))
    assert loaded["solution_id"] == "solution-1"
    assert loaded["run_id"] == "run-1"
    assert loaded["source_mode"] == "precomputed"
    assert "预计算" in loaded["provenance_label"]


@pytest.mark.parametrize("field,value", [
    ("run_id", ""), ("solution_id", 123), ("project_id", None),
    ("input_hash", "bogus"), ("source_mode", "live"), ("events", {}),
])
def test_fixture_rejects_invalid_envelope(tmp_path, field, value):
    payload = sample_solution()
    payload[field] = value
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


@pytest.mark.parametrize("field,value", [
    ("start_min", -1), ("end_min", -1), ("end_min", float("nan")),
    ("soc_start", 101), ("soc_end", -0.1), ("soc_start", True),
    ("start_min", "0"), ("event_type", None),
])
def test_fixture_rejects_invalid_events(tmp_path, field, value):
    payload = sample_solution()
    payload["events"][0][field] = value
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


def test_imported_pass_flags_never_enable_publish():
    payload = sample_solution()
    payload.update(passed=True, publishable=True, validation={"passed": True})
    project = {"project_id": "project-1", "input_hash": "a" * 64,
               "tasks": [{"id": "t1"}], "vehicles": [{"id": "v1"}]}
    result = validate_solution(payload, project)
    assert result["passed"] is False
    assert result["publishable"] is False
    assert any(check["status"] == "unknown" for check in result["checks"])


def test_independent_diagnostics_catch_wrong_snapshot_missing_task_and_overlap():
    payload = sample_solution()
    payload["input_hash"] = "b" * 64
    other = copy.deepcopy(payload["events"][0])
    other.update(event_id="e2", start_min=5, end_min=12, task_id="t2")
    payload["events"].append(other)
    project = {"project_id": "project-1", "input_hash": "a" * 64,
               "tasks": [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}],
               "vehicles": [{"id": "v1"}]}
    result = validate_solution(payload, project)
    assert {v["check"] for v in result["violations"]} >= {"identity", "coverage", "time"}
    assert result["publishable"] is False


def test_export_contains_only_actual_events(tmp_path):
    payload = sample_solution()
    path_json = export_events_json(payload, tmp_path / "events.json")
    assert json.loads(path_json.read_text(encoding="utf-8")) == payload["events"]
    path_csv = export_events_csv(payload, tmp_path / "events.csv")
    with path_csv.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["event_id"] == "e1"
    assert rows[0]["task_id"] == "t1"
    assert rows[0]["end_min"] == "10"


def test_invalid_export_does_not_replace_existing_file(tmp_path):
    payload = sample_solution()
    payload["events"][0]["soc_end"] = float("inf")
    path = tmp_path / "events.json"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError):
        export_events_json(payload, path)
    assert path.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("raw", [
    "[]", "null", "{broken", '{"solution_id":"a","solution_id":"b"}',
])
def test_fixture_rejects_ambiguous_or_malformed_json(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixture(path)


def test_validator_handles_invalid_solution_without_trusting_flags():
    result = validate_solution({"passed": True, "publishable": True}, {})
    assert result["passed"] is False
    assert result["publishable"] is False
    assert {item["check"] for item in result["violations"]} == {"schema", "identity"}


def test_validator_reports_soc_discontinuity():
    payload = sample_solution()
    second = copy.deepcopy(payload["events"][0])
    second.update(event_id="e2", start_min=10, end_min=20, soc_start=90, soc_end=70)
    payload["events"].append(second)
    project = {"project_id": "project-1", "input_hash": "a" * 64,
               "tasks": [{"id": "t1"}], "vehicles": [{"id": "v1"}]}
    result = validate_solution(payload, project)
    assert any(v["check"] == "energy" for v in result["violations"])


def test_empty_export_does_not_invent_rows(tmp_path):
    path = export_events_json({"events": []}, tmp_path / "empty.json")
    assert json.loads(path.read_text(encoding="utf-8")) == []
    csv_path = export_events_csv({"events": []}, tmp_path / "empty.csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream)) == []


@pytest.mark.parametrize("collection,value", [
    ("tasks", None), ("tasks", [{"id": []}]), ("vehicles", [None]),
    ("drones", [{"id": "d1"}, {"id": "d1"}]),
])
def test_malformed_project_returns_failed_diagnostic(collection, value):
    project = {"project_id": "project-1", "input_hash": "a" * 64, collection: value}
    result = validate_solution(sample_solution(), project)
    assert result["publishable"] is False
    assert any(v["check"] == "project_schema" for v in result["violations"])


def standard_solution():
    payload = sample_solution()
    payload["schedule_events"] = payload.pop("events")
    return payload


@pytest.mark.parametrize("field,value", [
    ("soc_end", -1), ("soc_start", 101), ("start_min", -1),
    ("end_min", -1), ("start_min", "0"), ("soc_end", True),
])
def test_standard_schedule_events_are_validated_on_load(tmp_path, field, value):
    payload = standard_solution()
    payload["schedule_events"][0][field] = value
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


def test_standard_events_reach_independent_diagnostics():
    payload = standard_solution()
    other = copy.deepcopy(payload["schedule_events"][0])
    other.update(event_id="e2", start_min=5, end_min=12, task_id="t2")
    payload["schedule_events"].append(other)
    project = {"project_id": "project-1", "input_hash": "a" * 64,
               "tasks": [{"id": "t1"}, {"id": "t2"}], "vehicles": [{"id": "v1"}]}
    result = validate_solution(payload, project)
    assert any(v["check"] == "time" for v in result["violations"])
    assert next(c for c in result["checks"] if c["name"] == "coverage")["status"] == "pass"


def test_shared_event_accessor_accepts_both_names_without_mutation():
    for payload in (sample_solution(), standard_solution()):
        original = copy.deepcopy(payload)
        events = adapter_module.get_solution_events(payload)
        assert len(events) == 1 and events[0]["event_id"] == "e1"
        events[0]["soc_end"] = -99
        assert payload == original


@pytest.mark.parametrize("canonical", [[], None, "not-list"])
def test_conflicting_or_invalid_aliases_rejected(tmp_path, canonical):
    payload = sample_solution()
    payload["schedule_events"] = canonical
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))
    with pytest.raises(ValueError):
        export_events_json(payload, tmp_path / "events.json")
    assert any(v["check"] == "schema" for v in validate_solution(payload, {})["violations"])


def test_matching_aliases_accepted_and_loader_normalizes_legacy(tmp_path):
    payload = sample_solution()
    payload["schedule_events"] = copy.deepcopy(payload["events"])
    loaded = load_fixture(write_fixture(tmp_path, payload))
    assert loaded["schedule_events"] == payload["events"]
    assert "events" not in loaded
    legacy = load_fixture(write_fixture(tmp_path, sample_solution()))
    assert legacy["schedule_events"][0]["event_id"] == "e1"
    assert "events" not in legacy


def test_solution_requires_explicit_event_array(tmp_path):
    payload = sample_solution()
    payload.pop("events")
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


def test_standard_event_only_exports_include_actual_events(tmp_path):
    payload = standard_solution()
    path = export_events_json(payload, tmp_path / "events.json")
    assert json.loads(path.read_text(encoding="utf-8")) == payload["schedule_events"]
    path = export_events_csv(payload, tmp_path / "events.csv")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream))[0]["event_id"] == "e1"


@pytest.mark.parametrize("payload_factory", [sample_solution, standard_solution])
def test_full_solution_export_roundtrips_identity_source_and_extensions(tmp_path, payload_factory):
    payload = payload_factory()
    payload.update(metrics={"cost": 123.45}, custom={"note": "original"})
    original = copy.deepcopy(payload)
    path = export_module.export_solution_json(payload, tmp_path / "solution.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert {key: raw[key] for key in ("solution_id", "run_id", "project_id", "input_hash", "source_mode")} == {
        "solution_id": "solution-1", "run_id": "run-1", "project_id": "project-1",
        "input_hash": "a" * 64, "source_mode": "precomputed"}
    assert raw["schedule_events"][0]["event_id"] == "e1"
    assert "events" not in raw
    assert raw["custom"] == {"note": "original"}
    loaded = load_fixture(path)
    assert loaded["metrics"] == {"cost": 123.45}
    assert loaded["schedule_events"][0]["soc_end"] == 80
    assert payload == original


def test_invalid_full_export_leaves_existing_file_intact(tmp_path):
    payload = standard_solution()
    payload["schedule_events"][0]["soc_end"] = -1
    path = tmp_path / "solution.json"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError):
        export_module.export_solution_json(payload, path)
    assert path.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("field", ["cost_total_yuan", "return_time_min"])
@pytest.mark.parametrize("value", ["100", [], None, True, -1, float("inf"), float("nan")])
def test_rejects_unsafe_optional_numeric_summaries(tmp_path, field, value):
    payload = standard_solution()
    payload[field] = value
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))
    assert any(v["check"] == "schema" for v in validate_solution(payload, {})["violations"])


@pytest.mark.parametrize("field", ["complete", "validation_passed", "publishable"])
@pytest.mark.parametrize("value", ["false", 0, 1, None, []])
def test_rejects_non_boolean_optional_flags(tmp_path, field, value):
    payload = standard_solution()
    payload[field] = value
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


@pytest.mark.parametrize("coverage", [None, [], "all", {"completed_intervals": True},
                                       {"original_intervals": -1}, {"completed_intervals": "274"},
                                       {"completed_subtasks": 1.5}, {"task_count": -1}])
def test_rejects_unsafe_coverage_counts(tmp_path, coverage):
    payload = standard_solution()
    payload["coverage"] = coverage
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


@pytest.mark.parametrize("field", ["vehicles", "drones", "sorties"])
@pytest.mark.parametrize("value", [None, {}, "none", True])
def test_rejects_non_array_optional_resources(tmp_path, field, value):
    payload = standard_solution()
    payload[field] = value
    with pytest.raises(ValueError):
        load_fixture(write_fixture(tmp_path, payload))


def test_optional_summaries_flags_and_arrays_preserved_without_approval(tmp_path):
    payload = standard_solution()
    payload.update(cost_total_yuan=0, return_time_min=239.5,
                   complete=False, validation_passed=True, publishable=True,
                   coverage={"original_intervals": 274, "completed_intervals": 274,
                             "completed_subtasks": 1011, "task_count": 1011},
                   vehicles=[], drones=[], sorties=[])
    loaded = load_fixture(write_fixture(tmp_path, payload))
    for field in ("cost_total_yuan", "return_time_min", "coverage", "complete",
                  "validation_passed", "publishable", "vehicles", "drones", "sorties"):
        assert loaded[field] == payload[field]
    diagnostic = validate_solution(loaded, {"project_id": "project-1", "input_hash": "a" * 64})
    assert diagnostic["passed"] is False and diagnostic["publishable"] is False


def test_invalid_summary_full_export_cannot_replace_snapshot(tmp_path):
    payload = standard_solution()
    payload["cost_total_yuan"] = "malformed"
    path = tmp_path / "solution.json"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError):
        export_module.export_solution_json(payload, path)
    assert path.read_text(encoding="utf-8") == "original"


def grouped_project():
    return {"project_id": "project-1", "input_hash": "a" * 64,
            "tasks": [{"id": "t1", "physical_task_id": "physical-1", "direction": "forward"},
                      {"id": "t1-reverse", "physical_task_id": "physical-1", "direction": "reverse"}],
            "vehicles": [{"id": "v1"}]}


@pytest.mark.parametrize("selected", ["t1", "t1-reverse"])
def test_one_direction_per_physical_task_passes_basic_coverage(selected):
    payload = standard_solution()
    payload["schedule_events"][0]["task_id"] = selected
    result = validate_solution(payload, grouped_project())
    coverage = next(c for c in result["checks"] if c["name"] == "coverage")
    assert coverage["status"] == "pass"
    assert result["passed"] is False and result["publishable"] is False
    assert next(c for c in result["checks"] if c["name"] == "operational_coverage")["status"] == "unknown"


@pytest.mark.parametrize("selected", [["t1", "t1-reverse"], ["t1", "t1"], ["t1-reverse", "t1-reverse"]])
def test_double_inspection_of_one_physical_task_fails_basic_coverage(selected):
    payload = standard_solution()
    event = payload["schedule_events"][0]
    event.pop("task_id")
    event["task_ids"] = selected
    result = validate_solution(payload, grouped_project())
    assert next(c for c in result["checks"] if c["name"] == "coverage")["status"] == "fail"
    assert any(v["check"] == "coverage" for v in result["violations"])


def test_duplicate_physical_group_across_events_fails_basic_coverage():
    payload = standard_solution()
    second = copy.deepcopy(payload["schedule_events"][0])
    second.update(event_id="e2", start_min=10, end_min=20, task_id="t1-reverse", soc_start=80, soc_end=70)
    payload["schedule_events"].append(second)
    result = validate_solution(payload, grouped_project())
    assert next(c for c in result["checks"] if c["name"] == "coverage")["status"] == "fail"


def test_missing_physical_group_and_unknown_task_fail_basic_coverage():
    project = grouped_project()
    project["tasks"].append({"id": "t2", "physical_task_id": "physical-2"})
    payload = standard_solution()
    payload["schedule_events"][0].update(task_ids=["unknown-task"])
    result = validate_solution(payload, project)
    coverage = next(c for c in result["checks"] if c["name"] == "coverage")
    assert coverage["status"] == "fail"
    assert "physical-2" in coverage["message"]
    assert "unknown-task" in coverage["message"]


@pytest.mark.parametrize("selected,status", [(["legacy-1"], "pass"),
                                             (["legacy-1", "legacy-1"], "fail"), ([], "fail")])
def test_legacy_task_has_its_own_required_group(selected, status):
    project = grouped_project()
    project["tasks"].append({"id": "legacy-1"})
    payload = standard_solution()
    payload["schedule_events"][0]["task_ids"] = selected
    result = validate_solution(payload, project)
    assert next(c for c in result["checks"] if c["name"] == "coverage")["status"] == status


@pytest.mark.parametrize("group", [None, [], ""])
def test_invalid_physical_group_returns_project_diagnostic(group):
    project = grouped_project()
    project["tasks"][0]["physical_task_id"] = group
    result = validate_solution(standard_solution(), project)
    assert any(v["check"] == "project_schema" for v in result["violations"])
