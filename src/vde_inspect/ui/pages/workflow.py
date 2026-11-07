"""Solution, playback and explicit unavailable-feature pages."""
import json
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QTableWidget, QTableWidgetItem, QSlider, QComboBox
from vde_inspect.solver.adapter import load_fixture, UnavailableSolverAdapter, get_solution_events
from vde_inspect.solver.validator import validate_solution
from vde_inspect.simulation.engine import PlaybackEngine
from vde_inspect.ui.pages.data_pages import read_only_table, fill_table


class InfoPage(QWidget):
    def __init__(self, title, text):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("subtitle")
        layout.addWidget(label)
        layout.addStretch()


class SolverPage(InfoPage):
    def __init__(self, title, context):
        super().__init__(title, "待真实求解器接入。当前版本不会模拟算法运行或生成假进度。先导入线网、生成任务，再配置合法服务站、设备与能源参数。")
        self.context = context
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.layout().insertWidget(2, self.status)
        button = QPushButton("开始求解")
        button.setEnabled(False)
        button.setToolTip(UnavailableSolverAdapter().reason)
        self.layout().insertWidget(3, button)
        context.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        p = self.context.project or {}
        missing = [label for key, label in [("tasks", "巡检任务"), ("depots", "车场"), ("vehicles", "车辆实例"), ("drones", "无人机实例")] if not p.get(key)]
        self.status.setText("数据预检：" + ("尚缺 " + "、".join(missing) if missing else "基础集合已有记录，尚需完整运行约束与求解器适配"))


class SolutionPage(InfoPage):
    def __init__(self, title, context):
        super().__init__(title, "只显示当前项目的方案。历史实验图表不等于可执行方案；完整独立校验尚未全部实现，当前禁止发布。")
        self.context = context
        self.rows = []
        actions = QHBoxLayout()
        for caption, callback in [("导入方案 JSON", self.import_solution), ("打开选中方案", self.open_selected), ("导出当前方案", self.export_solution)]:
            button = QPushButton(caption)
            button.clicked.connect(callback)
            actions.addWidget(button)
        self.publish = QPushButton("发布方案")
        self.publish.setEnabled(False)
        self.publish.setToolTip("完整覆盖、时空、能源、容量、库存及返场校验全部通过后才能发布。")
        actions.addWidget(self.publish)
        self.layout().insertLayout(2, actions)
        self.table = read_only_table()
        self.layout().insertWidget(3, self.table, 1)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.layout().insertWidget(4, self.detail)
        self.table.doubleClicked.connect(self.open_selected)
        context.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        p = self.context.project
        self.rows = self.context.repository.list_solutions(p["project_id"]) if p else []
        display = [dict(row, completeness="完整（源文件声明）" if row.get("complete") else "未完成 / 未提供", validation="需独立校验") for row in self.rows]
        fill_table(self.table, display, [("solution_id", "方案 ID"), ("source_mode", "来源"), ("completeness", "完整性"), ("cost_total_yuan", "源文件成本（元）"), ("validation", "验证状态")])
        s = self.context.solution
        if s:
            report = validate_solution(s, p)
            self.detail.setText(f"当前方案：{s['solution_id']}\n独立校验：{'通过' if report['passed'] else '未通过完整校验'}；发布已禁用。\n" + "；".join(f"{c['name']}：{c['status']}" for c in report["checks"]))
        else:
            self.detail.setText("尚无已选方案。没有结果时不填入预设成本、设备数或完成率。")

    def import_solution(self):
        if not self.context.project:
            self.context.report_error("请先选择当前项目。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入真实方案文件", "", "JSON (*.json)")
        if not path: return
        try:
            solution = load_fixture(Path(path))
            if solution["project_id"] != self.context.project["project_id"]:
                raise ValueError("该方案不属于当前项目，不能导入。")
            saved = self.context.repository.store_solution(solution)
            self.context.set_solution(saved)
        except (ValueError, OSError, KeyError) as error:
            self.context.report_error(str(error))

    def open_selected(self, *args):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.rows): return
        try:
            self.context.set_solution(self.context.repository.load_solution(self.rows[row]["solution_id"]))
        except (ValueError, OSError) as error:
            self.context.report_error(str(error))

    def export_solution(self):
        if not self.context.solution:
            self.context.report_error("尚未选择方案。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出方案", "solution.json", "JSON (*.json)")
        if path:
            try: self.context.repository.export_solution(self.context.solution["solution_id"], Path(path))
            except (ValueError, OSError) as error: self.context.report_error(str(error))


class PlaybackPage(InfoPage):
    def __init__(self, title, context):
        super().__init__(title, "所有状态读取同一份方案事件。无轨迹时仅显示事件表，不生成虚构设备运动；SOC 是方案计划值，不是实时遥测。")
        self.context = context
        self.engine = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        controls = QHBoxLayout()
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.toggle)
        controls.addWidget(self.play_button)
        pause = QPushButton("暂停")
        pause.clicked.connect(self.timer.stop)
        controls.addWidget(pause)
        reset = QPushButton("复位")
        reset.clicked.connect(lambda: self.slider.setValue(0))
        controls.addWidget(reset)
        self.speed = QComboBox()
        for speed in [1, 5, 10, 30]: self.speed.addItem(f"{speed} 倍", speed)
        controls.addWidget(self.speed)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek)
        controls.addWidget(self.slider, 1)
        self.time_label = QLabel("无方案事件")
        controls.addWidget(self.time_label)
        self.layout().insertLayout(2, controls)
        self.table = read_only_table()
        self.layout().insertWidget(3, self.table, 1)
        context.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.timer.stop()
        try:
            events = get_solution_events(self.context.solution) if self.context.solution else []
            self.engine = PlaybackEngine(events) if events else None
            end = max((float(e["end_min"]) for e in events), default=0)
            self.slider.setRange(0, int(end*100))
            self.slider.setValue(0)
            self.play_button.setEnabled(bool(events))
            self.seek(0)
        except (ValueError, KeyError) as error:
            self.engine = None
            self.play_button.setEnabled(False)
            self.context.report_error(str(error))

    def seek(self, value):
        if self.engine is None:
            self.table.setRowCount(0)
            self.time_label.setText("无方案事件")
            return
        minute = value/100
        states = self.engine.seek(minute)
        fill_table(self.table, list(states.values()), [("device_id", "设备 ID"), ("event_type", "事件"), ("status", "状态"), ("node_id", "节点"), ("soc", "计划 SOC（%）")])
        self.time_label.setText(f"{minute:.2f} min")

    def toggle(self):
        if self.timer.isActive(): self.timer.stop()
        elif self.engine: self.timer.start()

    def tick(self):
        target = self.slider.value() + int(10*self.speed.currentData())
        self.slider.setValue(min(target, self.slider.maximum()))
        if target >= self.slider.maximum(): self.timer.stop()
