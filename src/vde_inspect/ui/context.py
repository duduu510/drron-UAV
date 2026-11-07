from copy import deepcopy
from PySide6.QtCore import QObject, Signal


class AppContext(QObject):
    changed = Signal()
    message = Signal(str)
    notice = Signal(str)

    def __init__(self, repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.project = None
        self.solution = None
        self.inputs_locked = False

    def set_project(self, project):
        if self.inputs_locked:
            raise ValueError("计算运行中，输入项目已冻结；请等待结束或取消后再切换。")
        self.project = deepcopy(project)
        self.solution = None
        self.changed.emit()

    def save_project(self, project):
        if self.inputs_locked:
            raise ValueError("计算运行中，不能修改冻结的实验输入；请先取消或等待计算结束。")
        self.set_project(self.repository.save_project(project))

    def lock_inputs(self, locked):
        self.inputs_locked = bool(locked)

    def set_solution(self, solution):
        if solution is not None and (self.project is None or solution.get("project_id") != self.project["project_id"]):
            raise ValueError("方案不属于当前项目，请先选择对应项目。")
        if solution is not None and solution.get("input_hash") is not None and solution["input_hash"] != self.project["input_hash"]:
            raise ValueError("此方案对应历史输入，不能与已修改的当前线网混用。请先恢复对应冻结输入或导出历史方案。")
        self.solution = deepcopy(solution)
        self.changed.emit()

    def report_error(self, message):
        self.message.emit(str(message))

    def notify(self, message):
        """Nonmodal background-task notification; details stay in the run log."""
        self.notice.emit(str(message))
