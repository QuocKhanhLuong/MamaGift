# MamaGift Design System

This document is the design source of truth for MamaGift. Implementation work that changes user-facing UI must follow this file unless an explicit user-approved design decision supersedes it.

MamaGift should feel calm, familiar, editorial, and trustworthy. It is a family administrative assistant, not a generic AI dashboard.

## 1. Design direction

The design language combines two references deliberately:

- **Claude-inspired interaction model**: conversation shell, centered content, restrained chrome, simple sidebar, large composer, prose-first assistant responses, attachment chips, inline source actions.
- **Granola-inspired visual language**: warm neutral canvas, soft surfaces, editorial spacing, low visual noise, readable typography, subtle borders, note/document feeling.

Do not pixel-copy proprietary assets, logos, exact fonts, icons, or branded components. Use the references as product-design direction only.

## 2. Product UX principles

Prioritize in this order:

1. **Source trust before AI polish.** A user must be able to verify an answer against the original document quickly.
2. **Vietnamese-first clarity.** Labels, states, errors, and common actions should be natural Vietnamese.
3. **One obvious next action.** Avoid dense toolbars and dashboard-like button grids.
4. **Calm over flashy.** No decorative gradients, neon AI effects, glassmorphism, KPI tiles, or excessive motion.
5. **Document-first context.** When a document is active, the source remains visually present or one action away.
6. **Progressive disclosure.** Advanced metadata and diagnostics should not compete with the main task.
7. **Low prompt burden.** Common actions must be available as direct controls, not require prompt engineering.
8. **Readable for non-technical users.** Comfortable type size, generous spacing, plain-language states, obvious clickable targets.

## 3. UI foundation

Preferred frontend component stack:

```text
React / TypeScript
  -> Tailwind CSS
  -> shadcn/ui
  -> assistant-ui for chat primitives
  -> MamaGift custom components
```

Use `assistant-ui` or equivalent only for interaction primitives such as thread, message, composer, attachments, scrolling, and streaming. Do not inherit a default visual theme blindly.

Use shadcn/ui for low-level controls such as:

- button;
- dropdown menu;
- tooltip;
- dialog;
- sheet/drawer;
- tabs;
- input;
- textarea;
- command/search palette if later justified.

Use a single restrained icon family such as Lucide.

## 4. Visual tokens

These values are initial implementation tokens, not immutable brand assets. Preserve the relationships even if exact values are refined later.

### Color

```text
--mg-canvas:        #F6F4EF   warm application background
--mg-surface:       #FCFBF8   primary surface
--mg-surface-2:     #F1EEE7   secondary/subtle surface
--mg-text:          #27251F   primary text
--mg-text-muted:    #746F65   secondary text
--mg-border:        #E2DDD3   subtle borders/dividers
--mg-border-strong: #CCC5B8   emphasized separator
--mg-accent:        #B85C3F   warm restrained action accent
--mg-accent-soft:   #F2E2DA   subtle selected/highlight state
--mg-success:       #54765B
--mg-warning:       #9A6B2D
--mg-danger:        #9B4B45
```

Rules:

- Never use pure black for normal text.
- Never make every card white with a visible border.
- Use accent color sparingly for primary actions, selected state, source highlight, and focus.
- Confidence/error states must include text/icon semantics, never color only.

### Radius

```text
small control:     8px
normal control:   10px
composer/card:    14px
large panel:      16px maximum
```

Avoid overly rounded “bubble SaaS” styling.

### Shadows

Use shadows only for floating elements such as composer elevation, dropdowns, dialogs, and temporary overlays. Main layout panels should be separated primarily by spacing and subtle borders.

### Spacing

Use a 4px base scale. Prefer generous vertical rhythm:

```text
4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48
```

Default content gaps should normally be 16–24px, not 8px everywhere.

## 5. Typography

Typography should feel closer to an editorial document tool than an analytics dashboard.

Requirements:

- Vietnamese diacritics must render cleanly.
- Prefer a highly readable sans-serif system stack unless a later design decision approves another web font.
- Body text target: 16–17px desktop, minimum 16px mobile.
- Assistant long-form answers: comfortable line-height around 1.6–1.7.
- Avoid tiny 11–12px metadata except truly secondary technical information.
- Use weight and spacing before adding new colors.

Suggested hierarchy:

```text
Page title:          28–32px / semibold
Section title:       20–24px / semibold
Document title:      18–20px / medium-semibold
Body/chat prose:     16–17px / normal
Control label:       14–15px / medium
Secondary metadata:  13–14px / normal
```

## 6. Application shell

Desktop shell follows the simplicity of Claude rather than a dashboard.

```text
+----------------------+--------------------------------------------------+
| MamaGift             |                                                  |
|                      |                                                  |
| + Cuoc tro chuyen    |                 MAIN WORKSPACE                   |
|                      |                                                  |
| Van ban              |                                                  |
| Gan day              |                                                  |
|                      |                                                  |
| Search               |                                                  |
+----------------------+--------------------------------------------------+
```

Sidebar principles:

- approximately 240–272px desktop;
- collapsible;
- no icon grid dashboard;
- show only high-value navigation;
- document/conversation rows should be text-first;
- use section labels sparingly;
- selected item uses a subtle warm surface rather than a saturated block.

Primary destinations initially:

```text
Tro ly
Van ban
Gan day
```

Do not add Analytics, Admin, Activity, Integrations, Billing, Teams, or other SaaS navigation unless a later phase explicitly requires them.

## 7. Home / assistant empty state

The default assistant screen should resemble a calm Claude-style conversation entry point.

```text
                 Chao me,
           Hom nay me can tim gi?

       +--------------------------------+
       | Hoi ve van ban...              |
       |                                |
       | [paperclip]                 [↑]|
       +--------------------------------+

       [Tom tat van ban] [Tim deadline]
       [Toi can lam gi?]
```

Rules:

- no hero marketing banner;
- no charts;
- no “AI powered” badges;
- no large feature-card grid;
- suggested actions are compact and contextual;
- upload can be invoked through attachment/composer and document area.

## 8. Chat experience contract

### Thread width

Normal conversation content should be centered with a comfortable maximum width around 760–860px.

### User message

Use a restrained visual distinction. A soft surface or compact right-aligned container is acceptable, but avoid messenger-style giant speech bubbles.

### Assistant message

Assistant answers should read like clean prose on the page, not a card for every answer.

Support:

- headings;
- short lists;
- bold emphasis;
- compact tables only when genuinely useful;
- citations/source chips;
- lightweight actions beneath response.

### Composer

The composer is a primary product element.

Requirements:

- sticky/floating near bottom of active conversation;
- large multiline input;
- attachment button;
- obvious send control;
- keyboard submit behavior documented and tested;
- attachment state visible before sending;
- disabled/offline AI state expressed clearly;
- no unnecessary model selector exposed to the family user.

Target shape:

```text
+--------------------------------------------------+
| Hoi ve van ban...                                |
|                                                  |
| [attach]                                   [send]|
+--------------------------------------------------+
```

### Streaming

Streaming must not cause layout jumps. Preserve scroll position when the user has intentionally scrolled upward. Do not animate every token.

## 9. Document workspace

This is MamaGift's core differentiating layout.

Desktop target:

```text
+---------------+--------------------------------+----------------------+
| DOCUMENTS     |                                | TRO LY               |
|               |         ORIGINAL PDF           |                      |
| Search        |                                | Tom tat              |
|               |                                |                      |
| Hom nay       |                                | Deadline             |
| - Cong van... |                                |                      |
| - Ke hoach... |                                | Viec can lam         |
|               |                                |                      |
| Thang nay     |                                | Nguon: Trang 3       |
|               |                                |                      |
|               |                                | [Hoi them........]   |
+---------------+--------------------------------+----------------------+
```

Desktop proportions are guidelines:

- left document rail: 220–260px;
- center PDF/source pane: flexible and dominant;
- right assistant pane: 360–440px;

The center source pane must remain the dominant evidence surface.

### Panel behavior

- Left and right panels may collapse.
- PDF pane should expand when either panel collapses.
- Panel resizing may be added only if it remains simple and testable.
- Do not create overlapping floating panels on normal desktop widths.

## 10. PDF/source interaction

Source verification is first-class.

When an answer cites a source:

```text
Han hoan thanh: 25/08/2026

Cong van 142 · Trang 3
[Di toi nguon]
```

Activating the citation must:

1. focus/open the correct document;
2. navigate to the correct page;
3. highlight the source block or bounding region when available;
4. preserve enough surrounding context to verify the claim.

Highlighting should use a subtle warm accent, not opaque marker colors that hide text.

Never render a citation that cannot be resolved to known document/page/block provenance.

## 11. Document list/archive

Archive UI is a document library, not a data table by default.

Preferred row/card information:

```text
Cong van 142/SGDDT
Ve viec ...
14/08/2026 · So Giao duc va Dao tao
[Da xu ly]
```

Useful filters may include:

- date;
- issuer;
- document type;
- processing/review status.

Do not expose parser/model internals in the normal archive view.

## 12. Processing and confidence states

User-facing processing states should use plain Vietnamese language.

Preferred examples:

```text
Dang tai len
Dang doc van ban
Can kiem tra
San sang
Khong doc duoc van ban
Tro ly AI tam thoi khong ket noi
```

Avoid exposing internal terms such as `OCR_WORKER_PENDING`, `canonicalization`, `embedding`, or provider names.

Low-confidence critical fields should be reviewable inline:

```text
Han: 25/08/2026   Can kiem tra
                  [Dung] [Sua]
```

Corrections must feel like normal editing, not dataset annotation work.

## 13. Common-action design

For a selected document, surface a small number of direct actions:

```text
Tom tat
Toi can lam gi?
Co deadline nao?
Doi tuong ap dung?
```

These actions generate the same grounded-answer path as manually entered questions. They are not separate ungrounded summarization shortcuts.

Do not add more than roughly 4–6 visible suggestions at once.

## 14. Responsive behavior

### Desktop >= 1200px

Use the full three-pane document workspace when a document is active.

### Tablet 768–1199px

Prefer two panes:

```text
PDF/source + assistant
```

Document library becomes a drawer/sheet.

### Mobile < 768px

Never squeeze three columns.

Use a single active surface with clear transitions:

```text
Document
Chat
Details
```

The user must be able to switch between answer and source in one tap. Preserve page/citation context when switching.

Composer must remain usable above the virtual keyboard.

## 15. Accessibility

Minimum requirements:

- keyboard-accessible controls;
- visible focus state;
- semantic headings;
- form labels/accessible names;
- sufficient contrast;
- 44px-ish touch targets for important mobile actions;
- status not conveyed only by color;
- reduced-motion friendly behavior;
- PDF source jump has an accessible text alternative.

## 16. Motion

Motion should communicate state, not decorate.

Allowed:

- subtle panel transition;
- short dropdown/dialog transitions;
- processing indicator;
- source-highlight focus transition.

Avoid:

- continuous glowing AI effects;
- animated gradients;
- parallax;
- bouncing cards;
- token-by-token flourish effects.

## 17. Custom MamaGift components

Expected product-specific components include:

```text
DocumentViewer
DocumentRail
DocumentRow
DocumentMetadata
DocumentStatus
CitationChip
CitationPreview
SourceHighlight
ConfidenceField
CorrectionControl
DeadlineCard
ActionItem
DocumentAttachment
AssistantThread
AssistantComposer
QuickQuestionActions
HomeAINodeStatus
```

Do not create all components up front. Add them only in the phase that requires them.

## 18. Prohibited patterns

Codex/design agents must not introduce these without explicit approval:

- purple/blue AI gradients;
- glassmorphism;
- large dashboard KPI cards;
- excessive boxed cards;
- chatbot bubbles for every assistant paragraph;
- model/provider selectors for normal users;
- tiny dense enterprise tables as the default document library;
- more than one primary CTA competing in the same local context;
- decorative illustrations that displace functional content;
- source/citation information hidden behind multiple menus;
- desktop layouts with overlapping panels;
- prompt-engineering instructions shown to the family user.

## 19. Design implementation gates

A UI phase is not complete merely because screenshots look attractive.

For every major flow verify:

### Functional

- primary task can be completed without terminal/developer tooling;
- loading, empty, error, offline, and success states exist;
- source verification path works;
- responsive state works.

### Visual

- follows MamaGift tokens;
- whitespace and hierarchy remain calm;
- no prohibited pattern is introduced;
- chat feels Claude-inspired without copying proprietary branding;
- surfaces feel Granola-inspired/editorial rather than SaaS-dashboard-like.

### Accessibility

- keyboard path works;
- focus visible;
- controls named;
- mobile touch targets viable;
- status semantics not color-only.

### Regression

Important flows should have browser screenshots or visual-regression coverage once the UI stabilizes enough for that test to be valuable.

## 20. Design diagrams and flow handoff

Before substantial Phase 3 or Phase 4 UI implementation, a design agent may create detailed interaction diagrams/wireframes.

Store approved design artifacts under:

```text
docs/design/
```

Suggested files:

```text
docs/design/01_INFORMATION_ARCHITECTURE.md
docs/design/02_DOCUMENT_FLOW.md
docs/design/03_CHAT_FLOW.md
docs/design/04_RESPONSIVE_STATES.md
```

A design diagram becomes implementation-authoritative only after user review/approval. When an approved flow conflicts with this document, update this document or record the explicit design decision before implementation rather than silently diverging.

Every approved flow should specify at least:

- entry state;
- primary user action;
- success state;
- loading state;
- error state;
- back/navigation behavior;
- source/provenance behavior where applicable;
- desktop/tablet/mobile behavior.

## 21. Phase-specific expectations

### Phase 0

Only establish UI foundation, tokens, and minimal health screen. Do not build the final chat shell prematurely.

### Phase 3

Implement application shell, archive, upload/status, document workspace, verification/correction flows according to this design system.

### Phase 4

Add the Claude-inspired assistant thread/composer, grounded source chips, quick question actions, and home-node offline states without disrupting Phase 3 source-first document UX.

### Phase 5+

Extend the same shell rather than creating a second unrelated “global chat” product.

## 22. Review checklist

Before approving a frontend PR, answer:

- Does the screen feel like a calm document assistant rather than an admin dashboard?
- Is the main action immediately obvious?
- Can the user verify AI output against the original source quickly?
- Are Vietnamese labels understandable to a non-technical family user?
- Is the visual hierarchy driven by typography and whitespace more than borders/cards?
- Does chat behave like a modern Claude-style assistant without copying branding?
- Does the overall visual tone remain warm/editorial like Granola?
- Are mobile states intentionally designed rather than compressed desktop layouts?
- Are loading/error/offline/low-confidence states designed?
- Did the implementation avoid all prohibited patterns?

If any answer is no, the UI is not yet design-complete.
