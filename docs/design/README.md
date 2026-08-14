# MamaGift Design Handoff

This directory stores user-reviewed interaction diagrams, wireflows, information architecture, and responsive-state documentation used by implementation agents.

`docs/10_DESIGN_SYSTEM.md` remains the global visual/interaction contract. Files here refine concrete product flows.

## Suggested handoff files

```text
01_INFORMATION_ARCHITECTURE.md
02_DOCUMENT_FLOW.md
03_CHAT_FLOW.md
04_RESPONSIVE_STATES.md
```

A design diagram is not implementation-authoritative until the user has reviewed and approved it.

For each approved flow, document:

- entry point;
- user intent;
- primary action;
- success state;
- loading state;
- empty state where relevant;
- error/offline state;
- back/navigation behavior;
- source/citation behavior;
- desktop/tablet/mobile layout;
- components introduced or reused;
- accessibility considerations;
- unresolved design questions.

## Review rule

Before implementation, compare every approved diagram against:

- `docs/10_DESIGN_SYSTEM.md`;
- the active phase in `docs/04_PHASE_PLAN.md`;
- data/API capabilities in `docs/08_API_AND_DATA_CONTRACTS.md`.

If a flow needs behavior that belongs to a later phase, keep the visual placeholder only when necessary and do not silently implement the future subsystem.

If an approved design changes a global design rule, update `docs/10_DESIGN_SYSTEM.md` or record the explicit design decision before coding.
