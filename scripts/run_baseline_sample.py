"""Run the actual worker on the supplied Xi'an network; persist all assumptions."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QTimer
from vde_inspect.repositories.workspace import WorkspaceRepository
from vde_inspect.services.xian_import import load_xian_archive
from vde_inspect.solver.baseline import normalize_config, prepare_baseline_project
from vde_inspect.solver.manager import BaselineRunManager


def insert(repository, project):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", dir=repository.root, delete=False) as stream:
        path = Path(stream.name)
        json.dump(project, stream, ensure_ascii=False, allow_nan=False)
    try:
        return repository.import_project(path)
    finally:
        path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Research simulation only: actual Xi'an greedy baseline")
    parser.add_argument("--workspace", type=Path, default=Path("build/baseline-demo"))
    parser.add_argument("--teams", type=int, default=4)
    parser.add_argument("--window", type=float, default=240)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    app = QCoreApplication([])
    repository = WorkspaceRepository(args.workspace)
    source = load_xian_archive(root / "samples/xian/cn-xian.zip")
    if not any(p["project_id"] == source["project_id"] for p in repository.list_projects()):
        insert(repository, source)
    depot = next(s["id"] for s in source["stations"] if s["name"] == "钟楼")
    config = normalize_config(dict(depot_station_id=depot, team_count=args.teams, window_min=args.window,
                                   seed=args.seed, assume_service_at_all_stations=True))
    project = insert(repository, prepare_baseline_project(source, config))
    directory = repository.root / "runs" / str(uuid4())
    manager = BaselineRunManager()
    start = time.perf_counter()
    def done(result):
        repository.store_solution(result)
        summary = dict(algorithm_version=result["algorithm_version"], run_id=result["run_id"],
                       solution_id=result["solution_id"], project_id=result["project_id"], input_hash=result["input_hash"],
                       source_mode=result["source_mode"], complete=result["complete"], coverage=result["coverage"],
                       return_time_min=result["return_time_min"], cost_total_yuan=result.get("cost_total_yuan"),
                       cost_partial_yuan=result.get("cost_partial_yuan"), baseline_validation=result["baseline_validation"],
                       config=config, elapsed_seconds=time.perf_counter()-start, run_directory=str(directory))
        (repository.root / "latest-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=True))
        app.quit()
    def failed(message):
        print(json.dumps({"error": message}, ensure_ascii=True), file=sys.stderr)
        app.exit(1)
    manager.finished.connect(done)
    manager.failed.connect(failed)
    manager.cancelled.connect(lambda: app.exit(2))
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(manager.cancel)
    manager.start(project, config, directory)
    timeout.start(120_000)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
