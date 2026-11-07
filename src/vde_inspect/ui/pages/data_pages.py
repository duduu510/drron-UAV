"""Project data pages P02–P11. All displayed records belong to the active project."""
from copy import deepcopy
import math
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from vde_inspect.ui.widgets.records import RecordEditor


ID = ("id", "编号", "text")
NAME = ("name", "名称", "text")
SPECS = {
    "lines": ("线路", [ID, NAME, ("color", "线色（#RRGGBB）", "text")]),
    "stations": ("站点", [ID, NAME, ("line_id", "线路 ID", "text"), ("x", "横坐标", "optional_float"), ("y", "纵坐标", "optional_float"), ("service_allowed", "合法起降 / 接应", "bool")]),
    "segments": ("原始区间", [ID, ("line_id", "线路 ID", "text"), ("start_station_id", "起站 ID", "text"), ("end_station_id", "终站 ID", "text"), ("length_km", "长度（km）", "float"), ("direction", "方向", ("forward", "reverse", "both"))]),
    "depots": ("车场", [ID, NAME, ("station_id", "所在站点 ID", "text")]),
    "vehicle_models": ("车辆型号", [ID, NAME, ("capacity", "载机数量（架）", "int"), ("battery_count", "携带电池（块）", "int"), ("range_km", "续航（km）", "float")]),
    "drone_models": ("无人机型号", [ID, NAME, ("endurance_min", "续航（min）", "float")]),
    "vehicles": ("车辆实例", [ID, ("model_id", "车型 ID", "text"), ("depot_id", "所属车场 ID", "text"), ("enabled", "投入使用", "bool")]),
    "drones": ("无人机实例", [ID, ("model_id", "机型 ID", "text"), ("depot_id", "所属车场 ID", "text"), ("enabled", "投入使用", "bool")]),
    "batteries": ("电池库存", [ID, NAME, ("quantity", "库存（块）", "int"), ("compatible_models", "兼容型号 ID", "list")]),
}
COLLECTIONS = {"P02": ["lines"], "P03": ["stations", "segments"], "P07": ["depots"], "P08": ["vehicle_models", "drone_models"], "P09": ["vehicles", "drones"], "P10": ["batteries"]}
TASK_COLUMNS = [("id", "方向候选 ID"), ("physical_task_id", "物理子任务 ID"), ("segment_id", "原始区间"), ("direction", "方向"), ("length_km", "长度（km）"), ("start_node_id", "起点"), ("end_node_id", "终点"), ("start_service_allowed", "起点接应"), ("end_service_allowed", "终点接应")]


def task_counts_text(tasks):
    physical_count = len({task.get("physical_task_id", task["id"]) for task in tasks})
    return f"{physical_count} 个物理子任务，{len(tasks)} 个方向候选"


def fill_table(table, records, columns):
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels([label for _, label in columns])
    table.setRowCount(len(records))
    for row, record in enumerate(records):
        for col, (key, _) in enumerate(columns):
            value = record.get(key, record.get("id", "—") if key == "physical_task_id" else "—")
            if isinstance(value, bool):
                value = "允许" if value else "禁止"
            table.setItem(row, col, QTableWidgetItem(str(value)))
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)


def read_only_table():
    table = QTableWidget()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    return table


class DataPage(QWidget):
    def __init__(self, page_id, title, context, parent=None):
        super().__init__(parent)
        self.page_id, self.context = page_id, context
        self.editors = {}
        self.preview_tasks = None
        self.undo_tasks = None
        self.undo_hash = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(24, 20, 24, 24)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        self.layout.addWidget(heading)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.layout.addWidget(self.status)
        if page_id in COLLECTIONS:
            tabs = QTabWidget()
            for collection in COLLECTIONS[page_id]:
                label, columns = SPECS[collection]
                editor = RecordEditor(collection, columns, context)
                self.editors[collection] = editor
                tabs.addTab(editor, label)
            self.layout.addWidget(tabs, 1)
            notes = {"P02": "坐标在「站点与原始区间」中维护；没有坐标时可使用列表维护拓扑。", "P07": "车场必须关联已有站点。责任区和库存调度将在后续批次接入。", "P09": "先维护型号和车场，再创建实例；编号属于实际设备台账。载机关系和库存上限校验尚未接入。", "P10": "兼容性仅使用明确列出的型号 ID；空列表表示未配置兼容型号。换电事件及动态库存将在能源模块接入。"}
            if page_id in notes:
                note = QLabel(notes[page_id])
                note.setWordWrap(True)
                self.layout.addWidget(note)
        elif page_id == "P04":
            self.build_tasks()
        elif page_id == "P05":
            self.build_plans()
        elif page_id == "P06":
            self.build_import()
        elif page_id == "P11":
            self.build_config()
        context.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        project = self.context.project
        if project is None:
            self.status.setText("尚未选择项目。请从顶部新建或打开项目后维护数据。")
        else:
            self.status.setText(f"{project.get('name', '当前项目')}　版本 {project.get('revision', '—')}　所有修改保存至当前工作空间")
        if self.page_id == "P04":
            self.preview_tasks = None
            self.apply_button.setEnabled(False)
            self.preview_button.setEnabled(project is not None)
            self.undo_button.setEnabled(project is not None and self.undo_tasks is not None and self.undo_hash == project.get("input_hash"))
            tasks = (project or {}).get("tasks", [])
            fill_table(self.task_table, tasks, TASK_COLUMNS)
            self.task_status.setText(f"当前已保存：{task_counts_text(tasks)}。同一物理子任务只需选择一个允许方向执行一次；虚拟节点禁止接应。输入最大长度后可生成替换预览。")
        elif self.page_id == "P05":
            self.plan_button.setEnabled(project is not None)
            self.freeze_button.setEnabled(project is not None)
            self.copy_plan_button.setEnabled(project is not None)
            fill_table(self.plan_table, (project or {}).get("inspection_plans", []), [("id", "计划 ID"), ("name", "名称"), ("status", "状态"), ("task_count", "方向候选数"), ("input_hash", "来源输入哈希")])
        elif self.page_id == "P06":
            self.export_button.setEnabled(project is not None)
        elif self.page_id == "P11":
            self.config_save_button.setEnabled(project is not None)
            for path, widget in self.config_fields.items():
                group, key = path.split(".")
                widget.setText(str((project or {}).get(group, {}).get(key, "")))
                widget.setEnabled(project is not None)

    def build_tasks(self):
        bar = QHBoxLayout()
        bar.addWidget(QLabel("最大子任务长度（km）"))
        self.length_input = QDoubleSpinBox()
        self.length_input.setRange(0.001, 10000)
        self.length_input.setDecimals(3)
        self.length_input.setValue(0.5)
        bar.addWidget(self.length_input)
        self.preview_button = QPushButton("生成分段预览")
        self.apply_button = QPushButton("保存此任务集")
        self.apply_button.setObjectName("primary")
        self.undo_button = QPushButton("撤销本次生成")
        for button in (self.preview_button, self.apply_button, self.undo_button):
            bar.addWidget(button)
        bar.addStretch()
        self.layout.addLayout(bar)
        self.task_status = QLabel()
        self.task_status.setWordWrap(True)
        self.layout.addWidget(self.task_status)
        self.task_table = read_only_table()
        self.layout.addWidget(self.task_table, 1)
        self.preview_button.clicked.connect(self.preview_generation)
        self.apply_button.clicked.connect(self.apply_generation)
        self.undo_button.clicked.connect(self.undo_generation)
        self.length_input.valueChanged.connect(self.invalidate_preview)

    def invalidate_preview(self):
        if self.preview_tasks is not None:
            self.preview_tasks = None
            self.apply_button.setEnabled(False)
            self.task_status.setText("分段规则已改变，请重新生成预览后保存。")

    def preview_generation(self):
        if self.context.project is None:
            return
        try:
            from vde_inspect.services.tasks import generate_tasks
            self.preview_tasks = generate_tasks(self.context.project, self.length_input.value())
            if not self.preview_tasks:
                raise ValueError("没有可分段的原始区间，请先维护站点与原始区间")
            fill_table(self.task_table, self.preview_tasks, TASK_COLUMNS)
            self.task_status.setText(f"预览：{len(self.context.project.get('segments', []))} 个原始区间 → {task_counts_text(self.preview_tasks)}。同一物理子任务只需选择一个允许方向执行一次。尚未保存。")
            self.apply_button.setEnabled(True)
        except (ValueError, KeyError, OSError) as exc:
            self.preview_tasks = None
            self.apply_button.setEnabled(False)
            self.task_status.setText(f"分段失败，未提交：{exc}")
            self.context.report_error(str(exc))

    def apply_generation(self):
        if self.preview_tasks is None or self.context.project is None:
            return
        try:
            project = deepcopy(self.context.project)
            old_tasks = deepcopy(project.get("tasks", []))
            project["tasks"] = deepcopy(self.preview_tasks)
            self.context.save_project(project)
            self.undo_tasks = old_tasks
            self.undo_hash = self.context.project.get("input_hash")
            self.undo_button.setEnabled(True)
            self.task_status.setText(f"已保存：{task_counts_text(project['tasks'])}。同一物理子任务只需选择一个允许方向执行一次。")
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))

    def undo_generation(self):
        if self.undo_tasks is None or self.context.project is None or self.undo_hash != self.context.project.get("input_hash"):
            return
        try:
            project = deepcopy(self.context.project)
            project["tasks"] = deepcopy(self.undo_tasks)
            self.context.save_project(project)
            self.undo_tasks = None
            self.undo_button.setEnabled(False)
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))

    def build_plans(self):
        note = QLabel("创建计划会保存当前任务清单及输入哈希；冻结后只读。复制可生成独立草稿。时间窗口、必做标记及求解记录关联将在后续批次接入。")
        note.setWordWrap(True)
        self.layout.addWidget(note)
        bar = QHBoxLayout()
        self.plan_name = QLineEdit()
        self.plan_name.setPlaceholderText("巡检计划名称")
        bar.addWidget(self.plan_name, 1)
        self.plan_button = QPushButton("创建任务快照")
        self.freeze_button = QPushButton("冻结选中计划")
        self.copy_plan_button = QPushButton("复制选中计划")
        for button in (self.plan_button, self.freeze_button, self.copy_plan_button):
            bar.addWidget(button)
        self.layout.addLayout(bar)
        self.plan_table = read_only_table()
        self.plan_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.layout.addWidget(self.plan_table, 1)
        self.plan_button.clicked.connect(lambda: self.save_plan("create"))
        self.freeze_button.clicked.connect(lambda: self.save_plan("freeze"))
        self.copy_plan_button.clicked.connect(lambda: self.save_plan("copy"))

    def save_plan(self, action):
        if self.context.project is None:
            return
        try:
            project = deepcopy(self.context.project)
            plans = project.setdefault("inspection_plans", [])
            if action == "create":
                if not self.plan_name.text().strip():
                    raise ValueError("请填写巡检计划名称")
                if not project.get("tasks"):
                    raise ValueError("请先生成并保存任务集")
                plan = {"id": uuid4().hex, "name": self.plan_name.text().strip(), "status": "draft", "tasks": deepcopy(project["tasks"]), "task_count": len(project["tasks"]), "input_hash": project.get("input_hash", "")}
                plans.append(plan)
            else:
                row = self.plan_table.currentRow()
                if row < 0:
                    raise ValueError("请先选择计划")
                plan = plans[row]
                if action == "freeze":
                    plan["status"] = "frozen"
                else:
                    copied = deepcopy(plan)
                    copied.update(id=uuid4().hex, name=plan["name"] + " 副本", status="draft")
                    plans.append(copied)
            self.context.save_project(project)
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))

    def build_import(self):
        description = QLabel("导入完整 JSON 项目。文件会先解析并检查结构、重复编号和外键；全部通过后才写入工作空间。失败不覆盖现有数据。CSV 字段映射向导尚未接入。")
        description.setWordWrap(True)
        self.layout.addWidget(description)
        bar = QHBoxLayout()
        self.import_button = QPushButton("导入 JSON 项目…")
        self.export_button = QPushButton("导出当前项目…")
        bar.addWidget(self.import_button)
        bar.addWidget(self.export_button)
        bar.addStretch()
        self.layout.addLayout(bar)
        self.import_status = QLabel("请选择项目 JSON 文件。")
        self.import_status.setWordWrap(True)
        self.layout.addWidget(self.import_status)
        self.layout.addStretch()
        self.import_button.clicked.connect(self.choose_import)
        self.export_button.clicked.connect(self.choose_export)

    def choose_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入项目", "", "JSON 项目 (*.json)")
        if path:
            self.import_project(Path(path))

    def import_project(self, path):
        try:
            project = self.context.repository.import_project(Path(path))
            self.context.set_project(project)
            self.import_status.setText(f"已导入：{project['name']}\n{path}")
        except (ValueError, OSError, RuntimeError) as exc:
            self.import_status.setText(f"导入失败，未提交：{exc}")
            self.context.report_error(str(exc))

    def choose_export(self):
        if self.context.project is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出当前项目", "project.json", "JSON 项目 (*.json)")
        if path:
            self.export_project(Path(path))

    def export_project(self, path):
        if self.context.project is None:
            return
        try:
            output = self.context.repository.export_project(self.context.project["project_id"], Path(path))
            self.import_status.setText(f"已导出：{output}")
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))

    def build_config(self):
        self.config_fields = {}
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        groups = {
            "cost_config": [("vehicle_fixed_yuan", "车辆固定费用（元）"), ("drone_fixed_yuan", "无人机固定费用（元）"), ("vehicle_per_km_yuan", "车辆里程费用（元/km）"), ("drone_per_km_yuan", "无人机里程费用（元/km）"), ("energy_per_kwh_yuan", "能源单价（元/kWh）"), ("battery_swap_yuan", "换电费用（元/次）"), ("waiting_per_min_yuan", "等待费用（元/min）")],
            "safety_config": [("minimum_soc", "最低安全 SOC（0–100%）"), ("swap_duration_min", "换电时长（min）")],
        }
        for group, fields in groups.items():
            label = QLabel("成本参数" if group == "cost_config" else "安全与换电规则")
            label.setObjectName("panelTitle")
            form.addRow(label)
            for key, title in fields:
                widget = QLineEdit()
                widget.setPlaceholderText("尚未配置；留空保留未配置状态")
                self.config_fields[f"{group}.{key}"] = widget
                form.addRow(title, widget)
        note = QLabel("空白参数不会自动补零。保存后产生新的项目版本和输入哈希；历史方案快照保持原值。参数含义基于 provisional-1，真实求解器接入时仍需适配。")
        note.setWordWrap(True)
        form.addRow(note)
        scroll.setWidget(body)
        self.layout.addWidget(scroll, 1)
        self.config_save_button = QPushButton("保存成本与安全参数")
        self.config_save_button.setObjectName("primary")
        self.layout.addWidget(self.config_save_button)
        self.config_save_button.clicked.connect(self.save_config)

    def save_config(self):
        if self.context.project is None:
            return
        try:
            project = deepcopy(self.context.project)
            for path, widget in self.config_fields.items():
                group, key = path.split(".")
                raw = widget.text().strip()
                config = project.setdefault(group, {})
                if not raw:
                    config.pop(key, None)
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    raise ValueError(f"{key} 必须是有效数值") from None
                if not math.isfinite(value) or value < 0 or (key == "minimum_soc" and value > 100):
                    raise ValueError(f"{key} 超出允许范围")
                config[key] = value
            self.context.save_project(project)
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))
