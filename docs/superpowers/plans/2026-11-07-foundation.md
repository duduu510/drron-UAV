# VDE-Inspect foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Deliver an executable desktop foundation and honest data-management loop from the handoff, without invented solver/data results.
**Architecture:** Qt shell reads AppContext. Repository isolates SQLite/immutable files; worker modules own independent adapters and event reconstruction. Parallel workers edit disjoint directories under a provisional contract, parent owns integration.
**Tech Stack:** Python 3.14, PySide6 Qt Widgets, SQLite, pytest, pytest-qt.
**Spec:** ../specs/2026-11-07-foundation-design.md; ../../contracts/foundation.md

## Global Constraints
- Windows native desktop; no Web/Electron/HTTP server.
- Sidebar #111317, primary #1467E8, white surface; 1280×720 minimum.
- No source algorithm and no real Xi'an fixture supplied: display 待真实求解器接入 and empty results.
- Never overwrite immutable solution snapshots. Unknown validation fails closed.
- Parent owns shared docs and app/shell/theme. Workers own only assigned files and tests.

## Review Focus
- Malformed, oversized, foreign-project or duplicate-ID JSON must not alter an existing project/solution.
- Missing coordinates must not invent positions or hide valid topology rows.
- Project switches must clear previous solution and prevent cross-project metrics.
- Changing project/resource inputs must preserve old solution snapshots.
- Incomplete/unknown validation and missing files must not enable publishing or fake playback.

### Task 1: Domain, repository and task splitting
Files: src/vde_inspect/domain/*, repositories/*, services/*; tests/unit/test_repository.py and test_tasks.py.
Interfaces: exactly docs/contracts/foundation.md WorkspaceRepository and generate_tasks(project,max_length_km).
- [ ] Write failing persistence, invalid import rollback, stale revision, duplicate IDs/reference, immutable solution and splitting tests.
- [ ] Run pytest and observe missing behavior.
- [ ] Implement normalized input validation, transactional SQLite, SHA256 snapshots, exports/backup and subdivision preserving physical segment mapping.
- [ ] Run targeted tests; record results and unresolved limits.

### Task 2: Native data maintenance pages
Files: src/vde_inspect/ui/pages/data_pages.py, ui/widgets/*; tests/ui/test_data_pages.py.
Interfaces: DataPage(page_id,title,context,parent=None); context per contract.
- [ ] Write Qt tests for no-project state and real station/line CRUD save.
- [ ] Run tests red, implement P02–P11 form/table pages, task split preview/commit, full JSON import and project export.
- [ ] Reject invalid edits via repository errors, update on context.changed, preserve selection where possible.
- [ ] Run targeted offscreen Qt tests.

### Task 3: Honest solver adapter and deterministic playback
Files: src/vde_inspect/solver/*, simulation/*, report/*; tests/unit/test_solver.py and test_playback.py.
Interfaces: SolverAdapter, UnavailableSolverAdapter, load_fixture, validate_solution, PlaybackEngine per contract.
- [ ] Test missing solver explicit refusal; malformed fixture; deterministic seek; invalid times/SOC; unknown validation can't publish.
- [ ] Observe red tests; implement protocol/offline loader, independent diagnostic scaffold and deterministic event state.
- [ ] Implement CSV/JSON export only from actual solution events, no fictitious runs.
- [ ] Run targeted tests; report exactly which validation categories are supported versus unknown.

### Task 4: Application integration and delivery
Files: pyproject.toml, src/vde_inspect/app.py, ui/shell.py, ui/context.py, ui/theme.py, ui/pages/overview.py, ui/graphics/*, resources/*, scripts/*, README.md; tests/ui/test_shell.py.
- [ ] Write tests for eight module navigation/36 page registry, no fake KPIs, project switching clears solution, working new project/data loop.
- [ ] Observe red; implement QMainWindow/QLockFile, QStandardPaths workspaces, sidebar/topbar/subnav, real dashboard topology, solution import/list/detail/export, playback event table/clock, explicit later-stage pages.
- [ ] Run complete test suite and compileall; fix important issues with regression tests.
- [ ] Capture 1440×900 and 1280×720 Qt screenshots and inspect actual layouts.
- [ ] Run independent review and fix material findings. Save test report and locked dependencies, create launch shortcut script, start native application.

## Deferred / awaiting inputs
Full real-solver invocation, Xi'an regression, verified operational publishing, richer energy/battery validation, experimental suite and no-Python release verification require later stages and missing original datasets/source. Navigation coverage is not functional completion of all 36 pages.
