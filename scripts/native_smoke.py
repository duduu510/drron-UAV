"""Exercise the real native UI -> QProcess -> repository path on real inputs."""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vde_inspect.repositories.workspace import WorkspaceRepository
from vde_inspect.services.xian_import import load_xian_archive
from vde_inspect.ui.context import AppContext
from vde_inspect.ui.shell import MainWindow, import_project_dict
from vde_inspect.ui.theme import apply_theme

root = Path(__file__).resolve().parents[1]
app = QApplication([])
apply_theme(app)
repo = WorkspaceRepository(root / "build/native-e2e")
source = load_xian_archive(root / "samples/xian/cn-xian.zip")
existing = {p['project_id'] for p in repo.list_projects()}
if source['project_id'] not in existing:
    import_project_dict(repo, source)
context = AppContext(repo)
context.set_project(repo.get_project(source['project_id']))
source_hash = context.project['input_hash']
window = MainWindow(context)
window.navigate('P12')
window.show()
page = window.stack.currentWidget()
def fail(message):
    print(str(message), file=sys.stderr)
    app.exit(1)
def done(result):
    try:
        assert context.solution['solution_id'] == result['solution_id']
        assert not context.inputs_locked
        assert repo.get_project(source['project_id'])['input_hash'] == source_hash
        assert context.project['project_id'] != source['project_id']
        screenshot = root / 'build/screenshots/native-baseline-e2e.png'
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(screenshot))
        repo.export_solution(result['solution_id'], root / 'build/native-e2e/last-solution.json')
        print(json.dumps({'native_ui_to_process_to_saved_solution':True,'source_unchanged':True,
                          'inputs_unlocked':True,'complete':result['complete'],'coverage':result['coverage'],
                          'solution_id':result['solution_id']}, ensure_ascii=True))
        window.close()
        app.quit()
    except Exception as error:
        fail(error)
page.manager.finished.connect(done)
page.manager.failed.connect(fail)
page.consent.setChecked(True)
page.start_button.click()
assert page.manager.running
assert context.inputs_locked
window.navigate('P03')
assert not window.stack.currentWidget().isEnabled()
try:
    context.save_project(dict(context.project, name='should-not-save'))
    raise AssertionError('Live inputs were editable')
except ValueError:
    pass
window.navigate('P12')
QTimer.singleShot(30_000, lambda: fail('Native smoke timed out'))
raise SystemExit(app.exec())
