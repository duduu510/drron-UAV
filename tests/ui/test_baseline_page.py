from copy import deepcopy

from PySide6.QtCore import QObject, Signal

from vde_inspect.repositories.workspace import WorkspaceRepository
from vde_inspect.ui.context import AppContext


class ControlledManager(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.request = None

    def start(self, project, config, run_directory):
        self.request = deepcopy((project, config, run_directory))
        self.running = True

    def cancel(self):
        self.running = False
        self.cancelled.emit()


def make_page(qtbot, tmp_path, monkeypatch, project=True):
    from vde_inspect.ui.pages import baseline_page
    monkeypatch.setattr(baseline_page, 'BaselineRunManager', ControlledManager)
    repository = WorkspaceRepository(tmp_path / 'workspace')
    context = AppContext(repository)
    if project:
        source = repository.create_project('真实线网')
        source['lines'] = [dict(id='line', name='测试线', color='#1467E8')]
        source['stations'] = [dict(id='a', line_id='line', name='起点', x=0, y=0, service_allowed=False),
                              dict(id='b', line_id='line', name='钟楼', x=1, y=0, service_allowed=False)]
        source['segments'] = [dict(id='ab', line_id='line', start_station_id='a', end_station_id='b',
                                   length_km=.1, direction='both')]
        context.set_project(repository.save_project(source))
    page = baseline_page.BaselinePage(context)
    qtbot.addWidget(page)
    return page, context


def test_consent_is_explicit_and_actual_depot_defaults_to_bell_tower(qtbot, tmp_path, monkeypatch):
    page, context = make_page(qtbot, tmp_path, monkeypatch)
    assert not page.consent.isChecked()
    assert not page.start_button.isEnabled()
    assert page.depot_selector.currentData() == 'b'
    page.consent.setChecked(True)
    assert page.start_button.isEnabled()
    context.set_project(None)
    assert not page.start_button.isEnabled()


def test_start_imports_detached_experiment_and_preserves_selected_depot(qtbot, tmp_path, monkeypatch):
    page, context = make_page(qtbot, tmp_path, monkeypatch)
    original = deepcopy(context.project)
    page.depot_selector.setCurrentIndex(0)
    page.consent.setChecked(True)
    page.start_button.click()
    assert page.manager.running
    experiment, config, directory = page.manager.request
    assert experiment['project_id'] != original['project_id']
    assert context.project['project_id'] == experiment['project_id']
    assert context.repository.get_project(original['project_id']) == original
    assert config['depot_station_id'] == 'a'
    context.changed.emit()
    assert page.depot_selector.currentData() == 'a'
    assert directory.parent == context.repository.root / 'runs'
    assert not page.start_button.isEnabled()
    assert page.cancel_button.isEnabled()
    page.cancel_button.click()
    assert not page.manager.running
    assert '取消' in page.status.text()


def test_finished_partial_is_saved_and_never_shown_as_complete_cost(qtbot, tmp_path, monkeypatch):
    page, context = make_page(qtbot, tmp_path, monkeypatch)
    page.consent.setChecked(True)
    page.start_button.click()
    project = context.project
    result = dict(solution_id='partial-1', project_id=project['project_id'], input_hash=project['input_hash'],
                  complete=False, source_mode='simulation', cost_partial_yuan=12.5,
                  coverage={'physical_completed': 2, 'physical_total': 8},
                  baseline_validation={'passed': False, 'violations': ['coverage']})
    page.manager.running = False
    page.manager.finished.emit(result)
    assert context.solution == result
    assert context.repository.load_solution('partial-1') == result
    assert '部分成本' in page.result_summary.text()
    assert '12.50' in page.result_summary.text()
    assert '完整总成本' not in page.result_summary.text()
    assert '未完成' in page.status.text()
    assert '运营' in page.result_summary.text()
    assert '物理任务覆盖：2 / 8' in page.result_summary.text()


def test_progress_uses_worker_counters_and_error_is_non_modal(qtbot, tmp_path, monkeypatch):
    page, context = make_page(qtbot, tmp_path, monkeypatch)
    errors = []
    notices = []
    context.message.connect(errors.append)
    context.notice.connect(notices.append)
    page.consent.setChecked(True)
    page.start_button.click()
    page.manager.progress.emit(dict(processed=3, total=8, completed=2, message='真实计数'))
    assert page.progress_bar.value() == 3
    assert page.progress_bar.maximum() == 8
    assert '2' in page.progress_label.text()
    page.manager.log.emit('worker line')
    assert 'worker line' in page.logs.toPlainText()
    page.manager.running = False
    page.manager.failed.emit('worker failed')
    assert errors == []
    assert notices == ['worker failed']
    assert not page.cancel_button.isEnabled()


def test_form_exposes_all_baseline_parameters(qtbot, tmp_path, monkeypatch):
    page, _ = make_page(qtbot, tmp_path, monkeypatch)
    from vde_inspect.solver.baseline import DEFAULT_CONFIG
    assert set(page.fields) == set(DEFAULT_CONFIG) - {'depot_station_id', 'assume_service_at_all_stations'}
    page.fields['team_count'].setValue(6)
    page.fields['drone_min_soc'].setValue(25)
    assert page.collect_config()['team_count'] == 6
    assert page.collect_config()['drone_min_soc'] == 25


def test_selected_saved_simulation_shows_complete_cost_and_independent_scope(qtbot, tmp_path, monkeypatch):
    page, context = make_page(qtbot, tmp_path, monkeypatch)
    from vde_inspect.solver.baseline import solve_baseline
    page.consent.setChecked(True)
    page.start_button.click()
    result = solve_baseline(context.project, context.project['baseline_config'], run_id='run-1', solution_id='solution-1')
    page.manager.running = False
    page.manager.finished.emit(result)
    assert '完整总成本' in page.result_summary.text()
    assert '仿真独立检查：通过' in page.result_summary.text()
    assert '不可发布' in page.result_summary.text()
    assert '方向候选：2' in page.result_summary.text()
    assert 'run-1' in page.result_summary.text()
    assert 'solution-1' in page.result_summary.text()


def test_forged_source_validation_flag_cannot_display_passed(qtbot, tmp_path, monkeypatch):
    page, context = make_page(qtbot, tmp_path, monkeypatch)
    context.set_solution(dict(project_id=context.project['project_id'], source_mode='simulation',
                              complete=True, cost_total_yuan=450, baseline_validation={'passed': True, 'violations': []}))
    assert '仿真独立检查：通过' not in page.result_summary.text()
    assert '已载入保存结果' in page.progress_label.text()


def test_closing_page_requests_worker_cancellation(qtbot, tmp_path, monkeypatch):
    page, _ = make_page(qtbot, tmp_path, monkeypatch)
    page.consent.setChecked(True)
    page.start_button.click()
    assert page.manager.running
    page.close()
    assert not page.manager.running
