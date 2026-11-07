from copy import deepcopy
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from vde_inspect.ui.pages.data_pages import DataPage


class Context(QObject):
    changed = Signal()

    def __init__(self, project=None):
        super().__init__()
        self.project = project
        self.errors = []

    def save_project(self, project):
        self.project = deepcopy(project)
        self.changed.emit()

    def report_error(self, message):
        self.errors.append(message)


def test_empty_page_disables_record_editing(qtbot):
    page = DataPage("P02", "线路", Context())
    qtbot.addWidget(page)
    assert not page.editors["lines"].save_button.isEnabled()


def test_add_line_saves_copy_and_refreshes_all_pages(qtbot):
    original = {"project_id": "p1", "name": "测试", "lines": []}
    context = Context(original)
    page = DataPage("P02", "线路", context)
    other = DataPage("P02", "线路", context)
    qtbot.addWidget(page)
    qtbot.addWidget(other)
    editor = page.editors["lines"]
    editor.fields["id"].setText("L1")
    editor.fields["name"].setText("一号线")
    editor.save_button.click()
    assert context.project["lines"][0]["name"] == "一号线"
    assert original["lines"] == []
    assert other.editors["lines"].table.rowCount() == 1


def test_duplicate_id_does_not_overwrite(qtbot):
    context = Context({"lines": [{"id": "L1", "name": "原线路", "color": "#123456"}]})
    page = DataPage("P02", "线路", context)
    qtbot.addWidget(page)
    editor = page.editors["lines"]
    editor.fields["id"].setText("L1")
    editor.fields["name"].setText("重名")
    editor.save_button.click()
    assert context.project["lines"][0]["name"] == "原线路"
    assert context.errors


def test_referenced_line_cannot_be_deleted(qtbot, monkeypatch):
    context = Context({"lines": [{"id": "L1", "name": "线路"}], "stations": [{"id": "A", "line_id": "L1"}]})
    page = DataPage("P02", "线路", context)
    qtbot.addWidget(page)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    editor = page.editors["lines"]
    editor.table.selectRow(0)
    editor.delete_button.click()
    assert len(context.project["lines"]) == 1
    assert context.errors


def test_task_preview_does_not_commit_until_apply(qtbot):
    context = Context({"stations": [{"id": "A", "service_allowed": True}, {"id": "B", "service_allowed": True}], "segments": [{"id": "s1", "start_station_id": "A", "end_station_id": "B", "length_km": 1.2, "direction": "forward"}], "tasks": []})
    page = DataPage("P04", "子任务", context)
    qtbot.addWidget(page)
    page.length_input.setValue(0.5)
    page.preview_button.click()
    assert page.task_table.rowCount() == 3
    assert context.project["tasks"] == []
    page.apply_button.click()
    assert len(context.project["tasks"]) == 3
    page.undo_button.click()
    assert context.project["tasks"] == []


def test_resource_models_start_empty(qtbot):
    page = DataPage("P08", "型号", Context({"vehicle_models": [], "drone_models": []}))
    qtbot.addWidget(page)
    assert page.editors["vehicle_models"].table.rowCount() == 0
    assert page.editors["drone_models"].table.rowCount() == 0


def test_invalid_config_is_not_saved(qtbot):
    context = Context({"cost_config": {}, "safety_config": {}})
    page = DataPage("P11", "约束", context)
    qtbot.addWidget(page)
    page.config_fields["safety_config.minimum_soc"].setText("101")
    page.config_save_button.click()
    assert context.project["safety_config"] == {}
    assert context.errors


def test_project_import_failure_preserves_active_project_and_storage(qtbot, tmp_path):
    from vde_inspect.repositories.workspace import WorkspaceRepository
    repository = WorkspaceRepository(tmp_path / "workspace")
    project = repository.create_project("原项目")
    context = Context(project)
    context.repository = repository
    context.set_project = lambda new: setattr(context, "project", new)
    page = DataPage("P06", "导入", context)
    qtbot.addWidget(page)
    broken = tmp_path / "broken.json"
    broken.write_text('{"name":"坏项目","stations":[{"id":"A"}]}', encoding="utf-8")
    page.import_project(broken)
    assert context.project["project_id"] == project["project_id"]
    assert len(repository.list_projects()) == 1
    assert context.errors


def test_export_uses_saved_project_and_import_selects_valid_project(qtbot, tmp_path):
    from vde_inspect.repositories.workspace import WorkspaceRepository
    repository = WorkspaceRepository(tmp_path / "workspace")
    context = Context(repository.create_project("原项目"))
    context.repository = repository
    context.set_project = lambda new: setattr(context, "project", new)
    page = DataPage("P06", "导入", context)
    qtbot.addWidget(page)
    output = tmp_path / "export.json"
    page.export_project(output)
    assert json.loads(output.read_text(encoding="utf-8"))["name"] == "原项目"
    incoming = tmp_path / "incoming.json"
    incoming.write_text('{"project_id":"incoming","name":"导入项目"}', encoding="utf-8")
    page.import_project(incoming)
    assert context.project["name"] == "导入项目"
    assert repository.get_project("incoming")["name"] == "导入项目"


def test_plan_snapshot_survives_task_edits(qtbot):
    context = Context({"input_hash": "h1", "tasks": [{"id": "t1", "length_km": 0.5}]})
    page = DataPage("P05", "计划", context)
    qtbot.addWidget(page)
    page.plan_name.setText("夜间巡检")
    page.plan_button.click()
    context.project["tasks"][0]["length_km"] = 2
    page.plan_table.selectRow(0)
    page.freeze_button.click()
    plan = context.project["inspection_plans"][0]
    assert plan["tasks"][0]["length_km"] == 0.5
    assert plan["status"] == "frozen"


def test_config_save_keeps_unknown_settings(qtbot):
    context = Context({"cost_config": {"custom_energy": 7}, "safety_config": {"custom_limit": 2}})
    page = DataPage("P11", "约束", context)
    qtbot.addWidget(page)
    page.config_fields["safety_config.minimum_soc"].setText("20")
    page.config_save_button.click()
    assert context.project["cost_config"] == {"custom_energy": 7}
    assert context.project["safety_config"] == {"custom_limit": 2, "minimum_soc": 20}


def test_changed_split_rule_requires_new_preview(qtbot):
    context = Context({"stations": [{"id": "A", "service_allowed": True}, {"id": "B", "service_allowed": True}], "segments": [{"id": "s1", "start_station_id": "A", "end_station_id": "B", "length_km": 1.2, "direction": "forward"}], "tasks": []})
    page = DataPage("P04", "子任务", context)
    qtbot.addWidget(page)
    page.preview_button.click()
    assert page.apply_button.isEnabled()
    page.length_input.setValue(0.3)
    assert not page.apply_button.isEnabled()
    page.apply_button.click()
    assert context.project["tasks"] == []


def test_bidirectional_preview_counts_one_physical_task_and_two_candidates(qtbot):
    context = Context({"stations": [{"id": "A", "service_allowed": True}, {"id": "B", "service_allowed": True}], "segments": [{"id": "s1", "start_station_id": "A", "end_station_id": "B", "length_km": 0.4, "direction": "both"}], "tasks": []})
    page = DataPage("P04", "子任务", context)
    qtbot.addWidget(page)
    page.preview_button.click()
    assert "1 个物理子任务" in page.task_status.text()
    assert "2 个方向候选" in page.task_status.text()
    assert page.task_table.rowCount() == 2
    physical_column = next(i for i in range(page.task_table.columnCount()) if "物理" in page.task_table.horizontalHeaderItem(i).text())
    assert page.task_table.item(0, physical_column).text() == page.task_table.item(1, physical_column).text()
    page.apply_button.click()
    assert "1 个物理子任务" in page.task_status.text()
    assert "2 个方向候选" in page.task_status.text()


def test_saved_legacy_tasks_use_id_as_physical_group(qtbot):
    page = DataPage("P04", "子任务", Context({"tasks": [{"id": "old-a"}, {"id": "old-b"}]}))
    qtbot.addWidget(page)
    assert "2 个物理子任务" in page.task_status.text()
    physical_column = next(i for i in range(page.task_table.columnCount()) if "物理" in page.task_table.horizontalHeaderItem(i).text())
    assert page.task_table.item(0, physical_column).text() == "old-a"
