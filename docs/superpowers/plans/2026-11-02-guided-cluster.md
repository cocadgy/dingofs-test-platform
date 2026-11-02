# Guided Cluster Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users register an existing cluster through Start, adding its execution machine first when needed.

**Architecture:** Reuse `DiscoverClusters` and its existing backend operations. Extend the guided route and machine form with a continuation callback; pass the newly created machine ID into discovery for automatic selection.

**Tech Stack:** React, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-02-guided-cluster-design.md`

## Global Constraints

- Do not create a remote cluster or bypass discovery authentication and binding confirmation.
- Preserve unrelated changes in the dirty checkout; commit only this feature's hunks.
- Continue the existing password-only guided machine registration.

## Review Focus

- No machine exists: the add-machine branch remains accessible.
- New machine appears after creation and is selected with its SSH user.
- A failed machine submission does not advance the cluster step.
- Discovery import conflicts keep the existing binding confirmation.
- Leaving the wizard does not store an SSH password.

---

### Task 1: Machine continuation and discovery preselection

**Files:** `frontend/src/features/getting-started/GuidedMachineForm.tsx`, `frontend/src/features/clusters/DiscoverClusters.tsx`, adjacent tests.

**Interfaces:** `GuidedMachineForm({onCreated?:(id:string)=>void})`; `DiscoverClusters({initialMachineId?:string,onAddMachine?:()=>void})`.

- [ ] Write failing tests for the continuation button and discovered machine preselection.
- [ ] Verify RED with focused Vitest commands.
- [ ] Implement optional props without changing existing callers.
- [ ] Verify GREEN with focused tests.

### Task 2: Guided cluster routes and flow

**Files:** `frontend/src/features/getting-started/GettingStartedPage.tsx`, `frontend/src/App.tsx`, `frontend/src/features/getting-started/*.test.tsx`.

**Interfaces:** `#/start/cluster`, `#/start/cluster/machine`; existing `DiscoverClusters` performs remote discovery and import.

- [ ] Write failing navigation and flow tests.
- [ ] Verify RED.
- [ ] Wire chooser, nested machine route, discovery, successful import state and return paths.
- [ ] Verify GREEN, full frontend test suite, and production build.

### Task 3: Handoff

**Files:** `docs/GUIDED_START_ACCEPTANCE.md`, design and plan.

- [ ] Document cluster workflow and boundaries.
- [ ] Commit only scoped changes, build web image from committed snapshot, deploy web container, verify HTTP and bundled route labels.
