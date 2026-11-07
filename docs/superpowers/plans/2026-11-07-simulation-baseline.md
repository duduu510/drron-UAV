# Current-network simulation baseline Implementation Plan

> **For agentic workers:** Use subagent-driven-development; root coordinates three disjoint implementation tasks with independent final review.

**Goal:** Produce real reproducible simulation results from the supplied current network without claiming original GRASP or operational feasibility.
**Architecture:** Immutable simulation experiment project → QProcess actual greedy algorithm → independent conservative-model checker → saved solution and native playback.
**Tech Stack:** Existing Python/PySide6/SQLite; stdlib graph shortest paths, deterministic seeded construction.
**Spec:** ../../contracts/baseline.md (user chose the current-data baseline).

## Global Constraints
- Canonical schedule_events; physical_task_id covers each physical task once, alternative orientations aren't separate mandatory tasks.
- Explicit editable research assumptions and opt-in station-service assumption. Real source untouched.
- Simulated road distances use rail-network shortest-distance proxy, never passenger travel times; source_mode simulation.
- Incomplete has only cost_partial_yuan; no complete cost or operational publishing.
- Progress is emitted by actual subprocess; cancelled result never accepted. All files retain actual run/solution/input identities.

## Review Focus
- Return reserves, final SOC and battery stock must constrain every accepted sortie.
- Same seed/prepared inputs reproduce schedule; run IDs can differ intentionally.
- Disconnected network, invalid parameters or all tasks infeasible produce errors/diagnostics, not a fake full solution.
- Context changes/cancellation must not save result under a different project or accept a late worker.
- Independent checker must catch mutated coverage, time/SOC/service/cost, beyond algorithm self-report.

### Task 1: Baseline algorithm
Files: solver/baseline.py; tests/unit/test_baseline.py. Consumes domain/project and services/tasks. Produces normalize_config,prepare_baseline_project,solve_baseline exactly baseline.md.
- [ ] Write hand-calculated tiny-graph failing tests for deterministic events, grouped coverage, battery/window/return limits and partial-cost semantics.
- [ ] Implement graph cache, explicit simulation-project clone and conservative greedy station-return scheduling.
- [ ] Run unit tests, actual Xi’an smoke, report records and assumptions.

### Task 2: Actual process and independent checker
Files: solver/worker.py,manager.py,baseline_validator.py; tests unit/UI. Consumes Task1 project/config/result. Produces BaselineRunManager + checked solution output.
- [ ] Write mutation tests and real QProcess completion/cancel tests.
- [ ] Implement JSONL actual progress, durable request/log/state/result, bounded cancel/kill and fail-closed independent checking.
- [ ] Run targeted tests and crash/cancel cases, retaining actual evidence.

### Task 3: Native UI and integration
Files: ui/pages/baseline_page.py; tests/ui/test_baseline_page.py; root changes ui/shell.py,overview.py,README/docs.
- [ ] Test explicit consent/preflight/source preservation and finished/partial result path.
- [ ] Implement scrollable assumption forms, actual run counters/logs, save result and link to playback; one shared page for P12/P13.
- [ ] Run all tests, native screenshots, real Xi’an experiment and independent review. Record what assumptions/results mean and what remains unsupported.
