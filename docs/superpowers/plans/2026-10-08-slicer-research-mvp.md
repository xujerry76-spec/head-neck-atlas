# Slicer Research MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver an installable Slicer scripted module for local head/neck CT segmentation, slice labels, correction and reproducible research packages.

**Architecture:** Reuse Slicer MRML/rendering/Segment Editor and the TotalSegmentator extension's result importer. Run model inference in a separate PythonSlicer process with Qt polling. Keep geometry, layout and transactional bundle validation independent of Slicer for fast deterministic tests.

**Tech Stack:** Python, NumPy, PythonQt, VTK, Slicer, TotalSegmentator.

**Spec:** docs/superpowers/specs/2026-10-08-slicer-research-mvp-design.md

## Global Constraints

- Windows local desktop, single case, CT only; no model training.
- Tasks: head_glands_cavities and head_muscles; six initial structures.
- Automatic and corrected segmentations are distinct nodes and files.
- Moving text never modifies anatomy; slice anchors derive from current masks.
- Explicit download consent in product UI; record actual versions, unavailable metadata explicitly.
- Validate geometry and transactional save before reporting success.

## Review Focus

- Oblique slices and nonidentity transforms: project in physical coordinates; reject transformed input until hardened.
- Scene close during inference: cancel child and discard stale results.
- Switching CT with existing segmentation: reset case state, never reuse old masks.
- Corrupt or path-traversing package manifests: reject before scene mutation.
- Empty/overlapping segments: preserve labels and report counts without silently losing overlaps.

## Task 1: Geometry and label placement

Files: HeadNeckAtlas/AtlasLib/geometry.py, catalog.py; tests/test_geometry.py.
Interface: sample_slice(mask_kji, ijk_to_ras, xy_to_ras, width, height), interior_anchor(mask_yx), layout_labels(items, width, height, offsets), volume_ml(mask, ijk_to_ras).

- [x] Write tests for oblique sampling, RAS direction, empty regions, anchors inside a nonconvex largest component, label bounds/crowding and physical volume.
- [x] Run `python -m unittest discover -s tests -v`; confirm missing implementation fails.
- [x] Implement affine validation, nearest-neighbor slice sampling, interior anchor and label layout using NumPy and standard library.
- [x] Run full tests; expect all geometry tests pass.

## Task 2: Transactional research packages and inference contract

Files: AtlasLib/bundle.py, inference.py, worker.py; tests/test_bundle.py, test_inference.py.
Interfaces: write_bundle(destination, producer), validate_bundle(path), build_request(input_path, output_path, task, device, allow_download), run_worker(request_path).

- [x] Add tests for partial writes, no overwrite, checksums, traversal, invalid device/task, unsupported downloads and inference failure status.
- [x] Run tests and observe expected failures.
- [x] Implement staging directory, content hashes, atomic directory publication and explicit worker request/response contract. Preflight uses installed class_map and weight registry; block missing weights without permission.
- [x] Run full suite; expect package and worker contract tests pass.

## Task 3: Slicer integration and UI

Files: HeadNeckAtlas.py, AtlasLib/slicer_bridge.py, overlay.py; tests/slicer_smoke.py; CMakeLists.txt files, extension descriptor.
Interfaces: AtlasSession selects/validates volume, imports task results, copies corrected node, exports/loads package; SliceOverlay owns slice event observers; QProcess invokes worker with no MRML mutation in child.

- [x] Write executable Slicer smoke test for synthetic CT, scene save/reload, correction isolation, label display, missing extension and scene lifecycle.
- [x] Run inside actual Slicer when available; distinguish environment failure from test failure.
- [x] Implement module selectors, tasks/devices, progress/log/cancel, structure list, editor action, overlay drag and bundle actions. Observe mask edits and scene close; retain automatic snapshot for export.
- [x] Run unit suite and Slicer smoke; record environment limitations accurately.

## Task 4: Packaging, documentation and final verification

Files: README.md, scripts/start-slicer.ps1, docs/validation.md; build/HeadNeckAtlas.zip.

- [x] Document installation through Additional module paths, model installation and explicit download option, case workflow, test commands and real-case acceptance.
- [x] Compile Python sources, run unit suite, inspect bundle output and build a clean ZIP without patient data or upstream downloads.
- [x] Review code against Review Focus and fix substantive issues with regression tests.
- [x] Record tested versions and pending real-case tests; never claim clinical or model accuracy validation from synthetic data.

## Execution decisions

User instructed continuing through completion; implement inline in current workspace on codex/slicer-research-mvp. The repository has no baseline commit, so linked worktree creation is inapplicable; protect work using a feature branch. Git metadata writes require sandbox escalation. Read-only interface reference is cached in ignored .research. Use standard-library unittest because pytest is not installed.

## Validation status
Software tasks completed. Real model inference, GPU execution, real-case accuracy and CMake packaging remain unverified; see docs/validation.md.
