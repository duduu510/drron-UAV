# provisional-1 公共接口

这是本批次暂定契约，原包没有正式 schema。后续真实算法格式通过适配器转换，不覆盖历史快照。

## Project (plain JSON dict)
project_id: str; name: nonempty str; revision: int; input_hash: sha256; schema_version: "provisional-1".
Arrays default []: lines, stations, segments, tasks, depots, vehicle_models, drone_models, vehicles, drones, batteries.
Objects default {}: cost_config, safety_config.
Entity key: id (unique within collection). Line: id,name,color. Station: id,name,line_id,x,y,service_allowed(bool). Segment: id,line_id,start_station_id,end_station_id,length_km>0,direction("forward"|"reverse"|"both"). Depot: id,name,station_id. Models: id,name; vehicle adds capacity,battery_count,range_km; drone adds endurance_min. Vehicle/Drone: id,model_id,depot_id. Battery: id,name,quantity,compatible_models(list).
Task: id,physical_task_id,segment_id,direction,length_km,start_node_id,end_node_id,start_service_allowed,end_service_allowed. Splitting preserves total length per direction; virtual nodes cannot provide service. generate_tasks(project,max_length_km) pure function returns list; project not mutated. No preloaded physical device instances or invented projects.

## WorkspaceRepository
from vde_inspect.repositories.workspace import WorkspaceRepository
WorkspaceRepository(root: pathlib.Path)
list_projects() -> list[dict]; create_project(name: str) -> dict; get_project(project_id: str) -> dict; save_project(project: dict) -> dict
import_project(path: Path) -> dict; export_project(project_id: str,path: Path) -> Path
list_solutions(project_id: str) -> list[dict]; store_solution(payload: dict) -> dict; load_solution(solution_id: str) -> dict
backup(destination: Path) -> Path; close() -> None
export_solution(solution_id: str,path: Path) -> Path exports the entire verified immutable envelope and rejects workspace database/solution storage destinations.
Validation errors: ValueError; duplicate immutable solution: FileExistsError. Atomic DB transactions. Each method opens its own short-lived connection (thread-safe access without shared connection).

## AppContext (root-owned)
QObject changed Signal(), message Signal(str). repository: WorkspaceRepository; project: dict|None; solution: dict|None.
set_project(project: dict|None) -> None clears selected solution and emits changed.
save_project(project: dict) -> None saves through repository, sets returned project, emits changed.
set_solution(solution: dict|None) -> None validates belongs to current project, emits changed.
report_error(message: str) -> None emits message.

## DataPage (UI worker)
from vde_inspect.ui.pages.data_pages import DataPage
DataPage(page_id: str,title: str,context: AppContext,parent=None) -> QWidget.
Pages P02–P11 implement the corresponding editable data collections and task generation. P06 imports/exports projects. Others root-owned. All read context.project dynamically on changed. Errors call context.report_error.

## Offline solution / solver (solver worker)
SolverAdapter Protocol with available: bool; reason: str; solve(request: dict) -> dict. UnavailableSolverAdapter available False; solve raises RuntimeError with 待真实求解器接入.
load_fixture(path: Path) -> dict checks run_id,solution_id,project_id,input_hash,source_mode in precomputed/solver/simulation,minute time values and SOC bounds; immutable IDs preserved. No bundled fake fixture.
validate_solution(solution: dict,project: dict) -> dict: passed bool, publishable bool (false until all full checks implemented), checks list, violations list. Treat unknown checks as unknown; never label incomplete validation as passed.
PlaybackEngine(events: list[dict]); seek(t: float)->dict device_id -> state. Pure deterministic; events use event_id,device_id,event_type,start_min,end_min,soc_start,soc_end,from_node_id,to_node_id. Reject negative/inverted times, invalid SOC or duplicate IDs; no geometry interpolation when coordinates absent.

Canonical envelope array: schedule_events. Legacy events accepted at import; both fields must agree if both present. get_solution_events(solution) validates/detaches the chosen array; loader normalizes to schedule_events. Missing event arrays reject rather than silently becoming an empty schedule. Historical chart data never enters this envelope.

Direction candidates sharing physical_task_id represent alternative orientations of one physical inspection task; full operational validation must require exactly one permitted orientation per physical group.

AppContext now also exposes notice Signal(str), notify(message) for nonmodal background errors, and lock_inputs(bool). During an active run save_project/set_project reject before writing; source and project controls stay read-only. A solution with a different input_hash cannot be mixed into edited current geometry.
