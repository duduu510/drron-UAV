"""Native controls for the explicitly consented research simulation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from uuid import uuid4

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QSpinBox, QDoubleSpinBox, QFormLayout, QScrollArea,
    QPlainTextEdit, QProgressBar, QTabWidget,
)

from vde_inspect.solver.baseline import DEFAULT_CONFIG, normalize_config, prepare_baseline_project
from vde_inspect.solver.manager import BaselineRunManager
from vde_inspect.solver.baseline_validator import validate_baseline_solution
from vde_inspect.ui.pages.overview import panel


class BaselinePage(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.setObjectName('baselinePage')
        self.setStyleSheet('''
            QWidget#baselinePage { background:#F5F8FC; }
            QWidget#baselineForm { background:white; }
            QPlainTextEdit { background:#F7FAFD; color:#17243A; border:1px solid #E2E8F1; border-radius:6px; }
            QProgressBar { background:#E2E8F1; border:0; border-radius:4px; min-height:8px; max-height:8px; }
            QProgressBar::chunk { background:#1467E8; border-radius:4px; }
        ''')
        self.context = context
        self._active = False
        self._run_project = None
        self.manager = BaselineRunManager(self)
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        title = QLabel('可复现仿真基线')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('研究模型 · 贪心站点往返 / greedy-station-return 0.1\n'
                      '地面行驶使用无向轨道最短距离代理；参数为实验假设。无人机同站起降，车辆全程等待，无跨车转移。')
        note.setWordWrap(True)
        note.setObjectName('subtitle')
        layout.addWidget(note)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)

        body = QHBoxLayout()
        form_card, form_layout = panel('01  实验参数')
        self.form_tabs = QTabWidget()
        form_layout.addWidget(self.form_tabs)
        self.depot_selector = QComboBox()
        core = self._form_tab('基本配置')
        core.addRow('实际返场站点', self.depot_selector)
        for key, label in [('team_count', '车机团队数（每队 1 车 1 机）'),
                           ('seed', '随机种子'), ('window_min', '作业窗口（min）'),
                           ('max_length_km', '子任务最长（km）')]:
            self._add_field(core, key, label)
        explanation = QLabel('启动后创建新的「仿真基线」项目与冻结运行输入。\n原线网项目保留，可在项目列表重新打开。')
        explanation.setWordWrap(True)
        explanation.setObjectName('muted')
        core.addRow(explanation)
        energy = self._form_tab('速度与能源')
        for key, label in [('vehicle_speed_kmh', '车辆代理速度（km/h）'),
                           ('drone_speed_kmh', '无人机速度（km/h）'),
                           ('drone_endurance_min', '无人机续航（min）'),
                           ('vehicle_range_km', '车辆续航（km）'),
                           ('drone_min_soc', '无人机最低 SOC（%）'),
                           ('vehicle_min_soc', '车辆最低 SOC（%）'),
                           ('swap_stock', '每队备用电池（块）'),
                           ('swap_min', '换电时间（min）'),
                           ('launch_min', '起飞时间（min）'),
                           ('land_min', '降落时间（min）')]:
            self._add_field(energy, key, label)
        costs = self._form_tab('成本假设')
        for key, label in [('vehicle_fixed_yuan', '车辆固定成本（元/车）'),
                           ('drone_fixed_yuan', '无人机固定成本（元/机）'),
                           ('vehicle_km_yuan', '车辆里程成本（元/km）'),
                           ('vehicle_min_yuan', '车辆时间成本（元/min）'),
                           ('swap_yuan', '换电成本（元/次）')]:
            self._add_field(costs, key, label)
        body.addWidget(form_card, 6)

        run_card, run_layout = panel('02  运行与独立检查')
        self.status = QLabel('就绪 · 等待确认实验假设')
        self.status.setWordWrap(True)
        run_layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        run_layout.addWidget(self.progress_bar)
        self.progress_label = QLabel('尚未启动 · 进度来自算法工作进程')
        self.progress_label.setWordWrap(True)
        run_layout.addWidget(self.progress_label)
        self.result_summary = QLabel('尚无仿真结果。\n完成性、成本与仿真独立检查将在运行后显示。')
        self.result_summary.setWordWrap(True)
        self.result_summary.setStyleSheet('font-size:9pt;')
        run_layout.addWidget(self.result_summary)
        log_title = QLabel('工作进程日志')
        log_title.setObjectName('muted')
        run_layout.addWidget(log_title)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(1500)
        self.logs.setMinimumHeight(80)
        run_layout.addWidget(self.logs, 1)
        body.addWidget(run_card, 5)
        layout.addLayout(body, 1)

        self.consent = QCheckBox('我明确同意：所有实际站点允许保障服务仅为本次实验假设，非运营许可。')
        self.consent.setChecked(False)
        layout.addWidget(self.consent)
        actions = QHBoxLayout()
        self.start_button = QPushButton('创建实验并运行基线')
        self.start_button.setObjectName('primary')
        self.cancel_button = QPushButton('取消运行')
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        future = QPushButton('GRASP · 下一阶段')
        future.setEnabled(False)
        actions.addWidget(future)
        layout.addLayout(actions)
        self.consent.toggled.connect(self._update_controls)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.manager.cancel)
        self.manager.progress.connect(self._progress)
        self.manager.log.connect(self.logs.appendPlainText)
        self.manager.finished.connect(self._finished)
        self.manager.failed.connect(self._failed)
        self.manager.cancelled.connect(self._cancelled)
        context.changed.connect(self.refresh)
        self.refresh()

    def _form_tab(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName('baselineForm')
        form = QFormLayout(content)
        form.setContentsMargins(12, 14, 12, 14)
        form.setSpacing(10)
        scroll.setWidget(content)
        self.form_tabs.addTab(scroll, title)
        return form

    def _add_field(self, form, key, label):
        if key in ('team_count', 'swap_stock', 'seed'):
            field = QSpinBox()
            field.setRange(1 if key == 'team_count' else 0, 64 if key == 'team_count' else 2_147_483_647)
        else:
            field = QDoubleSpinBox()
            field.setDecimals(3)
            field.setRange(.001 if key in ('window_min', 'max_length_km', 'vehicle_speed_kmh',
                                          'drone_speed_kmh', 'drone_endurance_min', 'vehicle_range_km') else 0,
                           99.999 if key.endswith('min_soc') else 1_000_000_000)
        field.setObjectName(key)
        field.setValue(DEFAULT_CONFIG[key])
        self.fields[key] = field
        form.addRow(label, field)

    def collect_config(self):
        return {**{key: field.value() for key, field in self.fields.items()},
                'depot_station_id': self.depot_selector.currentData(),
                'assume_service_at_all_stations': self.consent.isChecked()}

    def refresh(self):
        project = self.context.project
        self.source_label.setText(f"当前项目：{project['name']}" if project else '请先在项目管理中选择或导入真实线网。')
        if not self._active:
            selected = self.depot_selector.currentData()
            self.depot_selector.clear()
            for station in (project or {}).get('stations', []):
                self.depot_selector.addItem(f"{station.get('name', station['id'])} · {station['id']}", station['id'])
            index = self.depot_selector.findData(selected)
            if index < 0:
                index = next((i for i, station in enumerate((project or {}).get('stations', []))
                              if station.get('name') == '钟楼'), 0)
            if self.depot_selector.count():
                self.depot_selector.setCurrentIndex(index)
            solution = self.context.solution
            if solution and solution.get('source_mode') == 'simulation':
                self._show_result(solution)
            else:
                self.status.setText('就绪 · 等待确认实验假设')
                self.result_summary.setText('当前项目尚未选择仿真结果。\n完成性、成本与仿真独立检查将在运行后显示。')
        self._update_controls()

    def _update_controls(self, *_):
        self.start_button.setEnabled(bool(self.context.project and self.depot_selector.count()
                                          and self.consent.isChecked() and not self._active))
        self.cancel_button.setEnabled(self._active)
        self.form_tabs.setEnabled(not self._active)
        self.consent.setEnabled(not self._active)

    def start(self):
        if self._active or not self.consent.isChecked() or not self.context.project:
            return
        try:
            config = normalize_config(self.collect_config())
            experiment = prepare_baseline_project(deepcopy(self.context.project), config)
            repository = self.context.repository
            with tempfile.TemporaryDirectory(prefix='.baseline-import-', dir=repository.root) as directory:
                path = Path(directory) / 'experiment.json'
                path.write_text(json.dumps(experiment, ensure_ascii=False, allow_nan=False), encoding='utf-8')
                saved = repository.import_project(path)
            self._active = True
            self._run_project = deepcopy(saved)
            self.context.set_project(saved)
            self.logs.clear()
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_label.setText('工作进程启动中 · 等待真实任务计数')
            self.result_summary.setText('实验输入已冻结，结果待工作进程返回。')
            self.status.setText('运行中 · 仿真基线（非运营调度）')
            self._update_controls()
            self.manager.start(saved, config, repository.root / 'runs' / str(uuid4()))
        except (ValueError, OSError, RuntimeError, KeyError) as error:
            self._failed(str(error))

    def _progress(self, payload):
        processed, total = int(payload['processed']), int(payload['total'])
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(processed)
        self.progress_label.setText(f"已处理 {processed} / {total} · 已完成 {payload.get('completed', 0)}\n{payload.get('message', '')}")

    def _finished(self, payload):
        self._active = False
        try:
            saved = self.context.repository.store_solution(payload)
            if (self.context.project or {}).get('project_id') != saved['project_id']:
                self.context.set_project(self.context.repository.get_project(saved['project_id']))
            self.context.set_solution(saved)
            self._show_result(saved)
        except (ValueError, OSError, KeyError) as error:
            self._failed(str(error))
        self._update_controls()

    def _show_result(self, saved):
        if not self._run_project or self._run_project['project_id'] != saved.get('project_id'):
            self.progress_label.setText('已载入保存结果 · 无当前工作进程计数')
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
        complete = saved.get('complete') is True
        self.status.setText('运行结束 · 完整覆盖' if complete else '运行结束 · 未完成覆盖')
        key = 'cost_total_yuan' if complete else 'cost_partial_yuan'
        amount = saved.get(key)
        cost = f'{amount:,.2f} 元' if isinstance(amount, (int, float)) else '未提供'
        # Source-provided flags are never evidence of independent validation.
        project = self.context.project or {}
        try:
            if not project.get('baseline_config') or not project.get('baseline_provenance'):
                raise ValueError('缺少冻结基线输入')
            check = validate_baseline_solution(saved, project, project['baseline_config'])
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            check = {'passed': False, 'violations': [str(error)]}
        checked = '通过' if check.get('passed') is True else '未通过 / 未提供'
        coverage = saved.get('coverage', {})
        self.result_summary.setText(f"物理任务覆盖：{coverage.get('physical_completed', '—')} / {coverage.get('physical_total', '—')}\n"
                                    f"方向候选：{coverage.get('directional_candidates', '—')}（每个物理任务只执行一个方向）\n"
                                    f"{'完整总成本' if complete else '部分成本'}：{cost}\n"
                                    f"仿真独立检查：{checked}\n"
                                    f"检查问题数：{len(check.get('violations', []))}\n"
                                    '运营完整验证未通过 · 不可发布\n'
                                    f"run_id：{saved.get('run_id', '—')}\n"
                                    f"solution_id：{saved.get('solution_id', '—')}")

    def _failed(self, message):
        self._active = False
        self.status.setText(f'运行失败 · {message}')
        self.logs.appendPlainText(str(message))
        notify = getattr(self.context, 'notify', None)
        if callable(notify):
            notify(str(message))
        self._update_controls()

    def _cancelled(self):
        self._active = False
        self.status.setText('已取消 · 本次结果未接收')
        self._update_controls()

    def closeEvent(self, event):
        if self.manager.running:
            self.manager.cancel()
        super().closeEvent(event)
