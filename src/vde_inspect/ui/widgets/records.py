"""Native table and explicit save/cancel record maintenance."""
from copy import deepcopy
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class RecordEditor(QWidget):
    def __init__(self, collection, columns, context, parent=None):
        super().__init__(parent)
        self.collection, self.columns, self.context = collection, columns, context
        self.selected_id = None
        self.fields = {}
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索编号、名称或属性…")
        self.search.textChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        split = QSplitter()
        layout.addWidget(split, 1)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([c[1] for c in columns])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.select_record)
        split.addWidget(self.table)
        panel = QWidget()
        right = QVBoxLayout(panel)
        self.form_title = QLabel("新增记录")
        self.form_title.setObjectName("panelTitle")
        right.addWidget(self.form_title)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, label, kind in columns:
            if kind == "bool":
                widget = QCheckBox("允许")
            elif isinstance(kind, tuple):
                widget = QComboBox()
                widget.addItems(kind)
            elif kind in ("float", "int", "optional_float"):
                widget = QLineEdit()
                widget.setPlaceholderText("可留空" if kind == "optional_float" else "请输入数值")
            else:
                widget = QLineEdit()
                if kind == "list":
                    widget.setPlaceholderText("多个型号 ID 用逗号分隔")
            widget.setObjectName(f"{collection}_{key}")
            self.fields[key] = widget
            form.addRow(label, widget)
        right.addLayout(form)
        self.hint = QLabel("填写后保存；选择表格行可编辑。删除前会检查引用。")
        self.hint.setWordWrap(True)
        right.addWidget(self.hint)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存记录")
        self.save_button.setObjectName("primary")
        self.cancel_button = QPushButton("取消 / 新增")
        self.delete_button = QPushButton("删除")
        for button in (self.save_button, self.cancel_button, self.delete_button):
            actions.addWidget(button)
        right.addLayout(actions)
        right.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(290)
        split.addWidget(scroll)
        split.setSizes([650, 350])
        self.save_button.clicked.connect(self.save_record)
        self.cancel_button.clicked.connect(self.clear_form)
        self.delete_button.clicked.connect(self.delete_record)
        context.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        project = self.context.project
        records = (project or {}).get(self.collection, [])
        self.table.blockSignals(True)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            for col, (key, _, _) in enumerate(self.columns):
                value = record.get(key, "")
                display = "、".join(map(str, value)) if isinstance(value, list) else str(value)
                if isinstance(value, bool):
                    display = "允许" if value else "禁止"
                item = QTableWidgetItem(display)
                item.setData(Qt.ItemDataRole.UserRole, record.get("id"))
                self.table.setItem(row, col, item)
        self.table.clearSelection()
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.save_button.setEnabled(project is not None)
        self.clear_form()
        self.filter_rows()

    def filter_rows(self):
        query = self.search.text().casefold()
        for row in range(self.table.rowCount()):
            text = " ".join(self.table.item(row, col).text() for col in range(self.table.columnCount()))
            self.table.setRowHidden(row, query not in text.casefold())

    def clear_form(self):
        self.selected_id = None
        self.table.clearSelection()
        self.form_title.setText("新增记录" if self.context.project else "请先新建或选择项目")
        for key, _, kind in self.columns:
            widget = self.fields[key]
            widget.setEnabled(self.context.project is not None)
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
            else:
                widget.setText("#1467E8" if key == "color" else "")
        self.delete_button.setEnabled(False)

    def select_record(self):
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return
        identity = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        record = next((r for r in self.context.project.get(self.collection, []) if r["id"] == identity), None)
        if not record:
            return
        self.selected_id = identity
        self.form_title.setText(f"编辑 {identity}")
        for key, _, kind in self.columns:
            widget, value = self.fields[key], record.get(key, "")
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
            else:
                widget.setText(", ".join(map(str, value)) if isinstance(value, list) else str(value) if value is not None else "")
        self.fields["id"].setEnabled(False)
        self.delete_button.setEnabled(True)

    def read_record(self):
        records = self.context.project.get(self.collection, [])
        record = deepcopy(next((r for r in records if r["id"] == self.selected_id), {}))
        for key, label, kind in self.columns:
            widget = self.fields[key]
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentText()
            else:
                value = widget.text().strip()
                if kind == "optional_float" and not value:
                    record.pop(key, None)
                    continue
                if kind in ("float", "int", "optional_float"):
                    try:
                        value = int(value) if kind == "int" else float(value)
                    except ValueError:
                        raise ValueError(f"{label}必须是有效数值") from None
                    if not math.isfinite(value):
                        raise ValueError(f"{label}必须是有限数值")
                    if key not in ("x", "y") and value < 0:
                        raise ValueError(f"{label}不能为负数")
                    if key in ("length_km", "range_km", "endurance_min") and value <= 0:
                        raise ValueError(f"{label}必须大于零")
                elif kind == "list":
                    value = [v.strip() for v in value.replace("，", ",").split(",") if v.strip()]
            if key in ("id", "name") and not value:
                raise ValueError(f"请填写{label}")
            record[key] = value
        if self.selected_id is None and any(r["id"] == record["id"] for r in records):
            raise ValueError(f"编号 {record['id']} 已存在，请使用其他编号")
        foreign = {"line_id": "lines", "station_id": "stations", "start_station_id": "stations", "end_station_id": "stations", "depot_id": "depots"}
        if self.collection in ("vehicles", "drones"):
            foreign["model_id"] = "vehicle_models" if self.collection == "vehicles" else "drone_models"
        for key, target in foreign.items():
            if key in record and record[key] not in {r["id"] for r in self.context.project.get(target, [])}:
                raise ValueError(f"{key} 引用不存在的编号：{record[key]}")
        if self.collection == "batteries":
            known = {r["id"] for name in ("vehicle_models", "drone_models") for r in self.context.project.get(name, [])}
            if set(record["compatible_models"]) - known:
                raise ValueError("兼容列表包含不存在的型号 ID")
        return record

    def save_record(self):
        if self.context.project is None:
            return
        try:
            record = self.read_record()
            project = deepcopy(self.context.project)
            records = project.setdefault(self.collection, [])
            if self.selected_id is None:
                records.append(record)
            else:
                index = next(i for i, r in enumerate(records) if r["id"] == self.selected_id)
                records[index] = record
            self.context.save_project(project)
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))

    def delete_record(self):
        if self.selected_id is None:
            return
        try:
            relations = {
                "lines": [("stations", "line_id"), ("segments", "line_id")],
                "stations": [("segments", "start_station_id"), ("segments", "end_station_id"), ("depots", "station_id")],
                "segments": [("tasks", "segment_id")],
                "depots": [("vehicles", "depot_id"), ("drones", "depot_id")],
                "vehicle_models": [("vehicles", "model_id")],
                "drone_models": [("drones", "model_id")],
            }
            for collection, key in relations.get(self.collection, []):
                if any(r.get(key) == self.selected_id for r in self.context.project.get(collection, [])):
                    raise ValueError(f"无法删除：{collection} 仍引用 {self.selected_id}")
            if self.collection in ("vehicle_models", "drone_models") and any(self.selected_id in r.get("compatible_models", []) for r in self.context.project.get("batteries", [])):
                raise ValueError("无法删除：电池兼容列表仍引用此型号")
            if QMessageBox.question(self, "删除记录", f"确认删除 {self.selected_id}？") != QMessageBox.StandardButton.Yes:
                return
            project = deepcopy(self.context.project)
            project[self.collection] = [r for r in project.get(self.collection, []) if r["id"] != self.selected_id]
            self.context.save_project(project)
        except (ValueError, OSError, RuntimeError) as exc:
            self.context.report_error(str(exc))
