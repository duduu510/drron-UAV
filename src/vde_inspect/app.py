"""Windows-native application entry; no HTTP service or embedded browser."""
import argparse
import json
import logging
from pathlib import Path
import sys
from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from vde_inspect.repositories.workspace import WorkspaceRepository
from vde_inspect.ui.context import AppContext
from vde_inspect.ui.shell import MainWindow, import_project_dict
from vde_inspect.ui.theme import apply_theme


def load_latest_result(context):
    path = context.repository.root / "latest-summary.json"
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("此工作空间没有可打开的基线试跑摘要。")
    summary = json.loads(path.read_text(encoding="utf-8"))
    project = context.repository.get_project(summary["project_id"])
    solution = context.repository.load_solution(summary["solution_id"])
    if solution["project_id"] != project["project_id"]:
        raise ValueError("试跑摘要的项目与方案不一致。")
    context.set_project(project)
    context.set_solution(solution)


def main(argv=None):
    parser = argparse.ArgumentParser(description="VDE-Inspect 桌面巡检调度工作空间")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--import-xian", type=Path)
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--size", default="1440x900")
    parser.add_argument("--open-latest-result", action="store_true")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("VDEInspect")
    app.setApplicationName("VDE-Inspect")
    apply_theme(app)
    workspace = args.workspace or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=workspace / "application.log", encoding="utf-8", level=logging.INFO)
    lock = QLockFile(str(workspace / "application.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "VDE-Inspect", "此工作空间已在另一个窗口打开。")
        return 1
    try:
        repository = WorkspaceRepository(workspace)
        context = AppContext(repository)
        project_root = Path(__file__).resolve().parents[2]
        sample = project_root / "samples" / "xian" / "cn-xian.zip"
        incoming = args.import_xian or (sample if sample.is_file() and not repository.list_projects() else None)
        if incoming:
            from vde_inspect.services.xian_import import load_xian_archive
            data = load_xian_archive(incoming)
            if not any(p["project_id"] == data["project_id"] for p in repository.list_projects()):
                import_project_dict(repository, data)
        projects = repository.list_projects()
        if projects: context.set_project(projects[0])
        if args.open_latest_result: load_latest_result(context)
        historical = None
        archive = args.historical or project_root / "samples" / "xian" / "historical-charts.zip"
        if archive.is_file():
            from vde_inspect.report.historical import load_historical_archive
            try: historical = load_historical_archive(archive)
            except (ValueError, OSError): logging.exception("Historical archive rejected")
        window = MainWindow(context, historical)
        if args.open_latest_result: window.navigate("P12")
        width, height = map(int, args.size.split("x"))
        window.resize(width, height)
        window.show()
        if args.screenshot:
            def capture():
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(args.screenshot)): raise RuntimeError("Screenshot could not be saved")
                app.quit()
            QTimer.singleShot(600, capture)
        return app.exec()
    except Exception as error:
        logging.exception("Application startup failed")
        QMessageBox.critical(None, "启动失败", str(error))
        return 1
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
