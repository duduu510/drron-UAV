from pathlib import Path
import json
import tempfile
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLabel, QLineEdit, QComboBox, QPushButton, QStackedWidget, QInputDialog, QFileDialog, QMessageBox
from vde_inspect.ui.pages.overview import Dashboard
from vde_inspect.ui.pages.data_pages import DataPage
from vde_inspect.ui.pages.workflow import InfoPage, SolverPage, SolutionPage, PlaybackPage
from vde_inspect.ui.pages.analysis import HistoricalAnalysisPage

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
MODULES = ["M01", "M02", "M03", "M04", "M05", "M06", "M07", "SYS"]
MODULE_NAMES = ["综合驾驶舱", "巡检任务", "设备与能源", "智能调度", "方案管理", "仿真回放", "实验分析", "系统设置"]


def import_project_dict(repository, data):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", dir=repository.root, delete=False) as stream:
        path = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
    try:
        return repository.import_project(path)
    finally:
        path.unlink(missing_ok=True)


class MainWindow(QMainWindow):
    def __init__(self, context, historical=None):
        super().__init__()
        self.context = context
        self.historical = historical
        self.current_page_id = "P01"
        self.pages = {}
        self._baseline_page = None
        self._closing_after_run = False
        with (RESOURCES / "page_registry.json").open(encoding="utf-8") as file:
            self.groups = json.load(file)
        self.registry = {entry.split(" ", 1)[0]: (module, entry.split(" ", 1)[1]) for module, entries in self.groups.items() for entry in entries}
        self.setWindowTitle("VDE-Inspect · 车机能巡检系统")
        self.setMinimumSize(1280, 720)
        self.resize(1440, 900)
        root = QWidget()
        self.setCentralWidget(root)
        whole = QHBoxLayout(root)
        whole.setContentsMargins(0, 0, 0, 0)
        whole.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(16, 24, 16, 18)
        brand = QLabel("车机能巡检系统")
        brand.setObjectName("brand")
        left.addWidget(brand)
        sub = QLabel("VDE-Inspect")
        sub.setObjectName("brandSub")
        left.addWidget(sub)
        left.addSpacing(24)
        self.module_list = QListWidget()
        self.module_list.setObjectName("moduleNav")
        self.module_list.addItems(MODULE_NAMES)
        self.module_list.currentRowChanged.connect(self.select_module)
        left.addWidget(self.module_list, 1)
        foot = QLabel("本地桌面工作空间\n0.1.0 · 首批开发版")
        foot.setObjectName("sidebarFoot")
        left.addWidget(foot)
        whole.addWidget(sidebar)
        content = QWidget()
        content.setObjectName("contentRoot")
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        top = QWidget()
        top.setObjectName("topbar")
        top.setMinimumHeight(64)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(24, 10, 24, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索页面、任务或设备 ID")
        self.search.setMaximumWidth(280)
        self.search.returnPressed.connect(self.search_records)
        top_layout.addWidget(self.search, 1)
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(210)
        self.project_combo.setMaximumWidth(280)
        self.project_combo.currentIndexChanged.connect(self.select_project)
        top_layout.addWidget(self.project_combo, 1)
        self.new_button = QPushButton("新建项目")
        self.new_button.clicked.connect(self.new_project)
        top_layout.addWidget(self.new_button)
        self.import_button = QPushButton("导入西安线网")
        self.import_button.clicked.connect(self.import_xian)
        top_layout.addWidget(self.import_button)
        badge = QLabel("本地离线模式")
        badge.setObjectName("badge")
        top_layout.addWidget(badge)
        right.addWidget(top)
        subrow = QHBoxLayout()
        subrow.setContentsMargins(24, 10, 24, 0)
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("muted")
        subrow.addWidget(self.breadcrumb)
        subrow.addStretch()
        self.page_combo = QComboBox()
        self.page_combo.setMinimumWidth(250)
        self.page_combo.currentIndexChanged.connect(self.select_subpage)
        subrow.addWidget(self.page_combo)
        right.addLayout(subrow)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        whole.addWidget(content, 1)
        self.dashboard = Dashboard(context)
        self.pages["P01"] = self.dashboard
        self.stack.addWidget(self.dashboard)
        context.changed.connect(self.refresh_context)
        context.message.connect(self.show_error)
        context.notice.connect(lambda message: self.statusBar().showMessage(message, 15000))
        self.refresh_context()
        self.navigate("P01")

    def select_module(self, index):
        if index >= 0:
            self.navigate(self.groups[MODULES[index]][0].split(" ", 1)[0])

    def select_subpage(self, index):
        key = self.page_combo.itemData(index)
        if key: self.navigate(key)

    def navigate(self, page_id):
        module, title = self.registry[page_id]
        index = MODULES.index(module)
        self.module_list.blockSignals(True)
        self.module_list.setCurrentRow(index)
        self.module_list.blockSignals(False)
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for entry in self.groups[module]:
            key, name = entry.split(" ", 1)
            self.page_combo.addItem(name, key)
        self.page_combo.setCurrentIndex(self.page_combo.findData(page_id))
        self.page_combo.blockSignals(False)
        if page_id not in self.pages:
            page = self.make_page(page_id, title)
            self.pages[page_id] = page
            if self.stack.indexOf(page) < 0:
                self.stack.addWidget(page)
        self.stack.setCurrentWidget(self.pages[page_id])
        self.breadcrumb.setText(f"{MODULE_NAMES[index]} / {title}")
        self.current_page_id = page_id
        self.sync_run_controls()

    def make_page(self, key, title):
        number = int(key[1:])
        if 2 <= number <= 11: return DataPage(key, title, self.context)
        if 12 <= number <= 13:
            if self._baseline_page is None:
                from vde_inspect.ui.pages.baseline_page import BaselinePage
                self._baseline_page = BaselinePage(self.context)
                self._baseline_page.start_button.clicked.connect(self.sync_run_controls)
                manager = self._baseline_page.manager
                manager.progress.connect(self.sync_run_controls)
                for signal in (manager.finished, manager.failed, manager.cancelled):
                    signal.connect(self.sync_run_controls)
                    signal.connect(self.finish_close)
            return self._baseline_page
        if 14 <= number <= 20: return SolutionPage(title, self.context)
        if 21 <= number <= 26: return PlaybackPage(title, self.context)
        if 27 <= number <= 31: return HistoricalAnalysisPage(self.historical)
        if key == "P32": return SolutionPage(title, self.context)
        if key == "P34": return self.workspace_page()
        if key == "P36":
            return InfoPage(title, "VDE-Inspect 0.1.0\n\n使用流程：新建或导入项目 → 维护站点区间 → 分段生成任务 → 配置设备与合法服务站 → 接入求解器 → 导入并校验方案。\n\n历史实验资料独立展示，不能作为当前项目结果。首批版本尚未完成真实求解、全套运营约束校验和无Python安装机验收。\n\n界面与范围来自用户交接包；西安原始线网来自用户提供的 cn-xian 数据包，原文件来源和估算口径保留在项目 source_metadata。")
        return InfoPage(title, "此页面属于后续开发阶段。当前可通过顶部切换项目，并在工作空间页面导出备份；未实现的功能不会显示为已完成。")

    def refresh_context(self):
        current = self.context.project
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("请选择项目", None)
        for project in self.context.repository.list_projects():
            self.project_combo.addItem(project["name"], project["project_id"])
        self.project_combo.setCurrentIndex(max(0, self.project_combo.findData(current["project_id"] if current else None)))
        self.project_combo.blockSignals(False)
        self.statusBar().showMessage(f"工作空间：{self.context.repository.root}")
        self.sync_run_controls()

    def sync_run_controls(self, *args):
        running = bool(self._baseline_page and self._baseline_page.manager.running)
        self.context.lock_inputs(running)
        for widget in (self.project_combo, self.new_button, self.import_button):
            widget.setEnabled(not running)
        for key, page in self.pages.items():
            if "P02" <= key <= "P11":
                page.setEnabled(not running)

    def closeEvent(self, event):
        if self._baseline_page and self._baseline_page.manager.running:
            self._closing_after_run = True
            event.ignore()
            self._baseline_page.manager.cancel()
            self.statusBar().showMessage("正在终止计算并保存运行记录，随后关闭窗口。")
        else:
            super().closeEvent(event)

    def finish_close(self, *args):
        if self._closing_after_run and not self._baseline_page.manager.running:
            QTimer.singleShot(0, self.close)

    def select_project(self, index):
        project_id = self.project_combo.itemData(index)
        try: self.context.set_project(self.context.repository.get_project(project_id) if project_id else None)
        except ValueError as error: self.context.report_error(str(error))

    def new_project(self):
        name, ok = QInputDialog.getText(self, "新建巡检项目", "项目名称")
        if ok:
            try: self.context.set_project(self.context.repository.create_project(name))
            except ValueError as error: self.context.report_error(str(error))

    def import_xian(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 cn-xian 线网数据", "", "ZIP (*.zip)")
        if path:
            from vde_inspect.services.xian_import import load_xian_archive
            try: self.context.set_project(import_project_dict(self.context.repository, load_xian_archive(Path(path))))
            except (ValueError, OSError, KeyError) as error: self.context.report_error(str(error))

    def show_error(self, message):
        self.statusBar().showMessage(message, 15000)
        QMessageBox.warning(self, "无法完成操作", message)

    def search_records(self):
        text = self.search.text().strip()
        if not text: return
        for key, (_, title) in self.registry.items():
            if text == key or text in title:
                self.navigate(key)
                return
        project = self.context.project or {}
        for collection, page in [("tasks", "P04"), ("stations", "P03"), ("segments", "P03"), ("vehicles", "P09"), ("drones", "P09")]:
            matches = [r for r in project.get(collection, []) if text.casefold() in (str(r.get("id", "")) + " " + str(r.get("name", ""))).casefold()]
            if matches:
                self.navigate(page)
                self.statusBar().showMessage(f"找到 {len(matches)} 条匹配记录；已打开对应数据页。", 12000)
                return
        self.statusBar().showMessage("当前项目和页面中未找到匹配记录。", 10000)

    def workspace_page(self):
        page = InfoPage("工作空间与备份", f"当前数据目录：\n{self.context.repository.root}\n\n项目保存在 SQLite 中；方案文件独立存储并校验哈希。备份包含数据库、方案文件与 SHA256 清单。恢复和迁移向导在后续版本实现。")
        button = QPushButton("导出工作空间备份")
        page.layout().insertWidget(2, button)
        def backup():
            path, _ = QFileDialog.getSaveFileName(self, "保存备份", "vde-inspect-backup.zip", "ZIP (*.zip)")
            if path:
                try:
                    self.context.repository.backup(Path(path))
                    self.statusBar().showMessage("备份已保存：" + path, 10000)
                except (OSError, ValueError) as error: self.context.report_error(str(error))
        button.clicked.connect(backup)
        return page
