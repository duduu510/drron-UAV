"""Capture real native UI states for review; writes only to build/qa-workspace."""
from pathlib import Path
from PySide6.QtWidgets import QApplication
from vde_inspect.repositories.workspace import WorkspaceRepository
from vde_inspect.ui.context import AppContext
from vde_inspect.ui.shell import MainWindow
from vde_inspect.ui.theme import apply_theme
from vde_inspect.report.historical import load_historical_archive

root = Path(__file__).resolve().parents[1]
app = QApplication([])
apply_theme(app)
repo = WorkspaceRepository(root / "build" / "qa-workspace")
context = AppContext(repo)
projects = repo.list_projects()
if projects:
    context.set_project(projects[0])
historical = load_historical_archive(root / "samples/xian/historical-charts.zip")
window = MainWindow(context, historical)
window.show()
for key in ("P01", "P03", "P04", "P27"):
    window.navigate(key)
    app.processEvents()
    destination = root / "build/screenshots" / f"{key}-1440.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(destination))
window.close()
