from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen, QBrush, QPainter
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGraphicsView, QGraphicsScene, QGraphicsItem, QSizePolicy


def panel(title):
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    label = QLabel(title)
    label.setObjectName("panelTitle")
    layout.addWidget(label)
    return widget, layout


class NetworkView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_data = QGraphicsScene(self)
        self.setScene(self.scene_data)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#F5F8FC"))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(190)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def set_project(self, project):
        scene = self.scene_data
        scene.clear()
        stations = {s["id"]: s for s in (project or {}).get("stations", []) if s.get("x") is not None and s.get("y") is not None}
        if not stations:
            item = scene.addText("尚无线网坐标\n导入真实线网后在此显示拓扑")
            item.setDefaultTextColor(QColor("#64748B"))
        else:
            for segment in project.get("segments", []):
                start, end = stations.get(segment.get("start_station_id")), stations.get(segment.get("end_station_id"))
                if start and end:
                    pen = QPen(QColor("#1467E8"), 1.8)
                    pen.setCosmetic(True)
                    line = scene.addLine(start["x"], start["y"], end["x"], end["y"], pen)
                    line.setToolTip(f"{segment['id']}\n{start['name']} — {end['name']}\n{segment.get('length_km', '—')} km")
            for station in stations.values():
                dot = scene.addEllipse(-2.5, -2.5, 5, 5, QPen(QColor("#1467E8"), 1), QBrush(QColor("white")))
                dot.setPos(station["x"], station["y"])
                dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                dot.setToolTip(f"{station['name']}\n{station['id']}\n保障许可：{'允许' if station.get('service_allowed') else '未配置 / 禁止'}")
        self.fit_scene()

    def fit_scene(self):
        bounds = self.scene_data.itemsBoundingRect().adjusted(-18, -18, 18, 18)
        self.scene_data.setSceneRect(bounds)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_scene()


class Dashboard(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 20)
        layout.setSpacing(16)
        title = QLabel("综合驾驶舱")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.subtitle = QLabel("新建项目或导入线网，开始建立巡检任务。")
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        cards = QHBoxLayout()
        self.metric_values = []
        for caption in ["区间覆盖", "启用车辆", "启用无人机", "方案成本（元）", "最晚返场（min）"]:
            card, inside = panel(caption)
            value = QLabel("—")
            value.setObjectName("metricValue")
            inside.addWidget(value)
            self.metric_values.append(value)
            cards.addWidget(card)
        layout.addLayout(cards)
        middle = QHBoxLayout()
        map_card, map_layout = panel("地铁线网与任务分布")
        self.map = NetworkView()
        map_layout.addWidget(self.map, 1)
        note = QLabel("拓扑视图 · 仅使用导入坐标；设备轨迹需真实方案事件")
        note.setObjectName("muted")
        note.setWordWrap(True)
        map_layout.addWidget(note)
        middle.addWidget(map_card, 7)
        card, right = panel("项目数据摘要")
        self.inventory = QLabel()
        self.inventory.setWordWrap(True)
        right.addWidget(self.inventory)
        right.addStretch()
        self.source_note = QLabel("尚未选择方案，指标不填入示例值。")
        self.source_note.setObjectName("muted")
        self.source_note.setWordWrap(True)
        right.addWidget(self.source_note)
        middle.addWidget(card, 3)
        layout.addLayout(middle, 1)
        card, bottom = panel("当前工作提示")
        self.next_step = QLabel()
        self.next_step.setWordWrap(True)
        bottom.addWidget(self.next_step)
        layout.addWidget(card)
        context.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        project, solution = self.context.project, self.context.solution
        self.subtitle.setText(f"当前项目：{project['name']}    项目版本：{project['revision']}" if project else "新建项目或导入线网，开始建立巡检任务。")
        p = project or {}
        task_count = len({task.get("physical_task_id", task["id"]) for task in p.get("tasks", [])})
        rows = [("已导入线路", len(p.get("lines", []))), ("站点", len(p.get("stations", []))), ("原始区间", len(p.get("segments", []))), ("物理子任务", task_count), ("已配置车场", len(p.get("depots", [])))]
        self.inventory.setText("\n\n".join(f"{title}    {count}" for title, count in rows))
        values = ["—"]*5
        if solution:
            coverage = solution.get("coverage", {})
            completed_intervals = coverage.get("completed_intervals", coverage.get("original_intervals_completed"))
            if completed_intervals is not None and "original_intervals" in coverage:
                values[0] = f"{completed_intervals} / {coverage['original_intervals']}"
            for index, key in [(1, "vehicles"), (2, "drones")]:
                if isinstance(solution.get(key), list): values[index] = str(len(solution[key]))
            if solution.get("cost_total_yuan") is not None: values[3] = f"{solution['cost_total_yuan']:,.2f}"
            if solution.get("return_time_min") is not None: values[4] = f"{solution['return_time_min']:.2f}"
        for label, value in zip(self.metric_values, values): label.setText(value)
        self.map.set_project(project)
        self.source_note.setText(f"方案：{solution['solution_id']}\n数据来源：{solution.get('provenance_label', solution.get('source_mode', '未确认'))}\n导入指标尚未通过完整独立校验。" if solution else "尚未选择方案，指标不填入示例值。")
        self.next_step.setText("可在「智能调度」运行新的仿真基线，先确认其中的研究假设。原 GRASP 求解器尚未接入；历史实验数据单独展示，不与当前项目结果混用。")
