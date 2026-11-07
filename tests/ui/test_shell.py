from vde_inspect.repositories.workspace import WorkspaceRepository
from vde_inspect.ui.context import AppContext
from vde_inspect.ui.shell import MainWindow


def test_navigation_all_pages_and_empty_metrics(qtbot, tmp_path):
    context = AppContext(WorkspaceRepository(tmp_path))
    window = MainWindow(context)
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    assert window.module_list.count() == 8
    assert len(window.registry) == 36
    for page_id in window.registry:
        window.navigate(page_id)
        assert window.current_page_id == page_id
    window.navigate("P01")
    assert all(label.text() == "—" for label in window.dashboard.metric_values)


def test_project_switch_clears_previous_solution(qtbot, tmp_path):
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    window = MainWindow(context)
    qtbot.addWidget(window)
    first = repo.create_project("项目甲")
    second = repo.create_project("项目乙")
    context.set_project(first)
    context.set_solution({"solution_id": "s-one", "project_id": first["project_id"]})
    context.set_project(second)
    assert context.solution is None
    assert context.project["name"] == "项目乙"
    assert window.project_combo.currentData() == second["project_id"]


def test_input_changes_preserve_old_selected_solution_only_as_snapshot(qtbot, tmp_path):
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    first = repo.create_project("线路项目")
    context.set_project(first)
    context.set_solution({"solution_id": "s-one", "project_id": first["project_id"], "input_hash": first["input_hash"]})
    edited = dict(first, name="线路项目修改")
    context.save_project(edited)
    assert context.solution is None
    assert repo.get_project(first["project_id"])["name"] == "线路项目修改"


def test_reject_foreign_solution(qtbot, tmp_path):
    import pytest
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    context.set_project(repo.create_project("项目"))
    with pytest.raises(ValueError):
        context.set_solution({"solution_id": "bad", "project_id": "another-project"})


def test_theme_provides_chinese_glyphs(qapp):
    from vde_inspect.ui.theme import apply_theme
    from PySide6.QtGui import QRawFont
    apply_theme(qapp)
    font = QRawFont.fromFont(qapp.font())
    assert font.isValid()
    assert font.supportsCharacter(ord("巡"))


def test_theme_is_valid_in_fresh_application_process():
    import os
    from pathlib import Path
    import subprocess
    import sys
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"), QT_QPA_PLATFORM="offscreen")
    script = "from PySide6.QtWidgets import QApplication; from PySide6.QtGui import QRawFont; from vde_inspect.ui.theme import apply_theme; app=QApplication([]); apply_theme(app); raw=QRawFont.fromFont(app.font()); assert raw.isValid(), 'No renderable font'; assert raw.supportsCharacter(ord('巡'))"
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_solution_page_export_refuses_workspace_database(qtbot, tmp_path, monkeypatch):
    from vde_inspect.ui.pages.workflow import SolutionPage
    from PySide6.QtWidgets import QFileDialog
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    project = repo.create_project("导出保护")
    context.set_project(project)
    solution = {"solution_id":"s-export", "run_id":"r-export", "project_id":project["project_id"], "input_hash":project["input_hash"], "source_mode":"precomputed", "schedule_events":[]}
    context.set_solution(repo.store_solution(solution))
    errors = []
    context.message.connect(errors.append)
    page = SolutionPage("方案导出", context)
    qtbot.addWidget(page)
    database = tmp_path / "workspace.sqlite3"
    before = database.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(database), "JSON (*.json)"))
    page.export_solution()
    assert errors
    assert database.read_bytes() == before
    assert len(repo.list_projects()) == 1


def test_solution_page_export_preserves_envelope(qtbot, tmp_path, monkeypatch):
    from vde_inspect.ui.pages.workflow import SolutionPage
    from vde_inspect.solver.adapter import load_fixture
    from PySide6.QtWidgets import QFileDialog
    repo = WorkspaceRepository(tmp_path / "workspace")
    context = AppContext(repo)
    project = repo.create_project("方案导出")
    context.set_project(project)
    solution = {"solution_id":"s-export", "run_id":"r-export", "project_id":project["project_id"], "input_hash":project["input_hash"], "source_mode":"precomputed", "schedule_events":[]}
    context.set_solution(repo.store_solution(solution))
    page = SolutionPage("方案导出", context)
    qtbot.addWidget(page)
    destination = tmp_path / "solution.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destination), "JSON (*.json)"))
    page.export_solution()
    loaded = load_fixture(destination)
    assert loaded["solution_id"] == "s-export"
    assert loaded["input_hash"] == project["input_hash"]


def test_dashboard_counts_physical_groups_not_direction_candidates(qtbot, tmp_path):
    from vde_inspect.ui.pages.overview import Dashboard
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    project = repo.create_project("物理任务分组")
    project["tasks"] = [{"id":"forward", "physical_task_id":"piece-1"}, {"id":"reverse", "physical_task_id":"piece-1"}]
    context.set_project(project)
    dashboard = Dashboard(context)
    qtbot.addWidget(dashboard)
    assert "物理子任务    1" in dashboard.inventory.text()


def test_solver_create_and_monitor_share_single_manager_page(qtbot, tmp_path):
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    window = MainWindow(context)
    qtbot.addWidget(window)
    window.navigate("P12")
    first = window.stack.currentWidget()
    window.navigate("P13")
    assert window.stack.currentWidget() is first


def test_open_latest_result_selects_saved_project_and_solution(qtbot, tmp_path):
    import json
    from vde_inspect.app import load_latest_result
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    project = repo.create_project("实验")
    solution = repo.store_solution({"solution_id":"s-latest", "run_id":"r-latest", "project_id":project["project_id"], "input_hash":project["input_hash"], "source_mode":"simulation", "schedule_events":[]})
    (tmp_path / "latest-summary.json").write_text(json.dumps({"project_id":project["project_id"], "solution_id":solution["solution_id"]}), encoding="utf-8")
    load_latest_result(context)
    assert context.project["project_id"] == project["project_id"]
    assert context.solution["solution_id"] == "s-latest"


def test_running_input_lock_rejects_project_edit_before_database_write(qtbot, tmp_path):
    import pytest
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    project = repo.create_project("冻结运行输入")
    context.set_project(project)
    context.lock_inputs(True)
    with pytest.raises(ValueError):
        context.save_project(dict(project, name="运行中修改"))
    assert repo.get_project(project["project_id"])["name"] == "冻结运行输入"
    assert repo.get_project(project["project_id"])["input_hash"] == project["input_hash"]
    context.lock_inputs(False)
    context.save_project(dict(project, name="运行结束后修改"))
    assert context.project["name"] == "运行结束后修改"


def test_solution_from_old_input_cannot_mix_with_changed_project(qtbot, tmp_path):
    import pytest
    repo = WorkspaceRepository(tmp_path)
    context = AppContext(repo)
    old = repo.create_project("历史输入")
    context.set_project(old)
    context.save_project(dict(old, name="新输入"))
    with pytest.raises(ValueError):
        context.set_solution({"solution_id":"historical", "project_id":old["project_id"], "input_hash":old["input_hash"]})
    assert context.solution is None
