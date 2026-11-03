# Cache capacity units implementation plan

**Goal:** Add MiB/GiB/TiB selectors to per-node and bulk capacity fields.
**Architecture:** Keep capacity stored and submitted in MiB. Store an optional display unit per row, defaulting to MiB for existing drafts; unit changes never alter capacity.
**Tech Stack:** React, TypeScript, Vitest.
**Spec:** User-approved conversation: numeric input plus unit dropdown, conversion without changing actual capacity, unchanged MiB backend API.

## Constraints and review focus
- Preserve default capacity and existing drafts/configuration profiles.
- Allow fractional GiB/TiB only when conversion produces positive integral MiB; reject non-finite/unsafe values.
- Bulk apply copies capacity and display unit; confirmation shows the selected unit.
- Preserve unrelated working changes; build only the scoped committed snapshot.

## Task: Capacity unit input
- [ ] Add failing component/flow tests for 1024 MiB -> 1 GiB -> 0.0009765625 TiB without changing the payload, editing 1.5 GiB -> 1536 MiB, bulk apply, and legacy draft defaults.
- [ ] Add CapacityInput.tsx accepting canonical MiB value, display unit and change callbacks; provide accessible numeric input and unit select.
- [ ] Extend guidedCacheModel.ts with optional capacityUnit and safe integral MiB validation; keep cache_size_mb unchanged.
- [ ] Use CapacityInput in GuidedCacheFlow.tsx for bulk and individual rows; preserve unit in drafts and bulk apply, display it in confirmation; add scoped layout CSS.
- [ ] Run guided frontend tests and TypeScript/build checks; review the scoped diff.
- [ ] Commit scoped files, deploy the web image, verify page/assets availability and report the commit.

**Execution:** Recommended: sequential implementation in this session; no parallel implementation needed for this small shared-component change.
