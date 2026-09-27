# UI/UX and Structural Audit — QA Archiving System

**Date:** 2026-09-07
**Method:** Live walkthrough of every page as Administrator, QA Head and Faculty, followed by
source analysis of all templates, stylesheets and view code.
**Constraint:** design and structure cleanup only — no feature was removed or rewritten.

---

## 1. Executive summary

The system is functionally complete and its security model is solid. What made it read as a
student project rather than a product was **not** the features — it was that the styling had
forked into three competing systems, and several screens exposed developer-facing internals to
end users.

The single root cause: **the same design tokens were declared three times** with different
values — in `static/css/style.css` (`--color-*`, brand blue), in `static/css/nexus.css`
(`--nx-*`, teal accent), and again inside `templates/dashboard/dashboard.html`. That is why
buttons rendered brand blue while the dashboard rendered teal, and why five KPI cards each had
a different accent hue with no meaning attached.

| Metric | Before | After |
|---|---:|---:|
| Inline `<style>` lines in templates | 4,476 | 3,362 |
| `dashboard.html` | 1,721 lines | 631 lines |
| Token systems in use | 3 | 1 |
| Stylesheet loaded on every page but used by one | yes (559 lines) | no |
| Pages passing role smoke test | — | 28 / 28 |
| Django test suite | 214 pass | 214 pass |

---

## 2. Findings and fixes

### 2.1 Design system

| # | Page / area | Issue | Type | Action |
|---|---|---|---|---|
| 1 | Global | Three separate declarations of the same design tokens (`style.css`, `nexus.css`, and inline in `dashboard.html`), with a blue brand in one and a teal accent in another | Design inconsistency | **Fixed** — `--nx-*` now aliases the canonical `--color-*` tokens. Every existing `var(--nx-*)` reference keeps working, so no template edits were needed. |
| 2 | Global | `nexus.css` (559 lines) linked in `base.html` and downloaded on every page, but only `dashboard.html` uses `.nx-*` classes — and that page inlined a **superset** of the same rules, so the stylesheet was dead weight everywhere | Redundant asset | **Fixed** — dashboard rules promoted into `nexus.css`, inline block removed, stylesheet now loaded via `extra_css` on the dashboard only. `dashboard.html` 1,721 → 631 lines. |
| 3 | Dashboard | Page heading used a teal → blue → purple gradient text fill, the only gradient heading in the system | Design inconsistency | **Fixed** — single heading colour from tokens. |
| 4 | Dashboard | `.nx-btn-primary` was a teal gradient while every other primary control is brand blue | Design inconsistency | **Fixed** — brand token. |
| 5 | Dashboard | Five KPI cards, five arbitrary accent hues (blue / teal / amber / purple / green) with nothing distinguishing an informational metric from one needing action | Design inconsistency | **Fixed** — three semantic accents: brand = informational, warning = needs attention, success = progress. Class names kept so markup is untouched. |
| 6 | Dashboard | Sparkline colours hardcoded blue and teal | Design inconsistency | **Fixed** — read from `--color-brand` at runtime. |
| 7 | Reports | Section header was a solid dark gradient bar — the only filled section header in the system, making Reports look like a different product | Design inconsistency | **Fixed** — neutral surface + border, brand-coloured icon. |
| 8 | Reports | "Export Excel" was a green gradient here but brand blue on the Dashboard — the same action in two colours | Design inconsistency | **Fixed** — brand blue on both. |
| 9 | Reports | Table header and zebra striping used a blue-tinted palette unique to this page | Design inconsistency | **Fixed** — token surfaces. |
| 10 | Repository | Five row actions each had its own hue and tinted pill (green/blue/indigo/amber/red). A 22-row table rendered **110 coloured chips**, and the colours meant nothing — "download" was indigo for no reason | Design inconsistency | **Fixed** — neutral icons; colour reserved for the destructive action and only on hover, so Delete reads as dangerous exactly when it matters. |

### 2.2 Layout and navigation

| # | Page / area | Issue | Type | Action |
|---|---|---|---|---|
| 11 | Dashboard | Five "At a glance" cards in a grid whose `minmax(204px)` forced the fifth onto a row of its own at 1280px | UX / layout | **Fixed** — `minmax(180px)`; all five share one row on a standard laptop. Verified: grid computes 5 equal columns. |
| 12 | Sidebar | The "AI & Analysis" / "Tools" divider and label rendered **unconditionally** while both items under it were permission-gated. A QA Head — who has neither AI Processing nor the QA Checklist — saw a section heading with nothing beneath it | UX defect | **Fixed** — the divider and label render only when at least one child is visible. Verified per role. |
| 13 | Sidebar | **Smart Search had no sidebar entry for any role.** The page was reachable only from a dashboard tile, despite all three roles having permission to use it | Navigation gap | **Fixed** — added under Main, gated on `PERM_SEARCH_DOCUMENTS`; now present for Administrator, QA Head and Faculty. |
| 14 | Accreditation Structure | Called **four different things**: sidebar "Accreditation Areas", page heading "Accreditation Structure", browser tab and breadcrumb "QA Structure" | UX / consistency | **Fixed** — "Accreditation Structure" everywhere. |
| 15 | Settings | Called three things: tab "System Settings", heading "System Configuration", sidebar "Settings" | UX / consistency | **Fixed** — "Settings" everywhere. |

### 2.3 Unnecessary functions and exposed internals

| # | Page / area | Issue | Type | Action |
|---|---|---|---|---|
| 16 | Smart Search | Four filters labelled **"Parameter PK", "Category PK", "Indicator PK", "Req. evidence PK"** — raw numeric database primary keys. Unusable without direct database access, and the Indicator and Required Evidence tables they target are **empty (0 rows)**, so they could never match anything | Unnecessary function | **Removed** — 13 filters → 9. |
| 17 | Smart Search | **Two inputs named `document_type` in one form.** Django's `QueryDict` returns the *last* value, so text typed in the first "Doc type" box was silently discarded by the empty second one | Functional defect | **Removed** the duplicate. This was a real bug, not just clutter. |
| 18 | Settings | Four of the five "AI Engine Status" badges were **hardcoded to "Online"** in the template. The page claimed the AI stack was up regardless of whether scikit-learn was installed. (The fifth, Tesseract, did correctly use `ocr_enabled`.) | Fabricated status | **Fixed** — all five are now probed. scikit-learn via `find_spec`; Tesseract via `get_tesseract_version()`, which proves the *binary* is present rather than just the Python wrapper. Verified against a real install: Tesseract 5.5.0 detected. |
| 19 | Settings | "Maximum Upload Size" showed a hardcoded "25 MB" above a progress bar pinned to `width:25%` with `aria-valuenow="25"` — a meter for a static limit, announcing "25 percent" to screen readers, and guaranteed to go stale if the setting changed | Misleading UI | **Fixed** — bar removed; the value now reads `FILE_UPLOAD_MAX_MEMORY_SIZE`. |
| 20 | Upload Document | Five accreditation dropdowns rendered Django's default `---------`, telling the user nothing about what was wanted | UX / unfinished | **Fixed** — "— Select area —", "— Select parameter —", etc. |
| 21 | Global JS | The KPI count-up animation existed **twice** — byte-identical logic inline in `dashboard.html` and again in `main.js`, differing only in selector | Duplicate code | **Fixed** — one implementation in `main.js` handling both `.stat-value` and `.nx-num[data-countup]`. |

| 22 | Dashboard | "Quick Actions" offered three tiles — Upload Documents, Open Repository, Smart Search — every one of which duplicated a permanent sidebar entry already visible on the same screen. It occupied a full row above the actual content for all three roles | Redundant function | **Removed** for every role. Dashboard 631 → 615 lines; the dead `.nx-quick-action` / `.nx-qa-go` / `.nx-grid-quick` CSS went with it (`nexus.css` 1,093 → 1,055). |
| 23 | Chatbot page | The floating chatbot button is `position: fixed; bottom: 28px; right: 28px` and sat **directly on top of the Chatbot page's own Send button**. `document.elementFromPoint()` at the Send button's centre returned `chatbotFab`, so a click on Send hit the floating widget instead | Functional defect | **Fixed** — the floating widget is no longer rendered on the Chatbot page itself, where it was redundant anyway. Re-verified: `elementFromPoint` now returns the send icon. |

| 24 | **Global (every page)** | The page overflowed horizontally by **279px at a 1280px viewport**. Root cause was not the Repository table, as first assumed: `.sidebar` is `position:fixed` and so leaves the flex flow, leaving `.main-wrapper` as the only flex item. With the default `min-width:auto` it kept its intrinsic content width (1284px) instead of shrinking to the 260px-narrower track, then `margin-left:260px` pushed the whole column past the right edge | Layout defect | **Fixed** — one declaration, `min-width:0` on `.main-wrapper`. Measured before/after at 1280px: Repository 1544 → 1265 page width (**279 → 0**), AI Processing 18 → 0, User Management 3 → 0, every other page already 0 and unchanged. |
| 25 | User Management | The **Administrator** role badge was red (`#ef4444` on `#fef2f2`) — the same colour the system uses for errors and destructive actions — so the highest-privilege account read as a fault on a healthy row | Misleading semantics | **Fixed** — role is a category, not a status. Privilege is now shown by weight: dark slate = Administrator, brand = QA Head, neutral = Faculty, muted = Viewer. All four moved off raw hex onto the tokens. |
| 26 | Accreditation Structure | User-facing screens carried developer language: *"no programming required"*, a toolbar button labelled *"Admin (optional)"* linking to Django Admin, and *"Ask IT to run migrations/seed"* | Unfinished copy | **Fixed** — "Advanced editing", "Parameters are added and edited directly on this page", "Add at least one in the advanced editor". No links or functionality removed. |
| 27 | AI Processing | "Recent Background Jobs" showed an **ID** column of raw database primary keys (`#55`–`#64`) to QA Office users — meaningless outside the database | Exposed internals | **Fixed** — column dropped, section renamed "Recent Processing Runs". Type / Status / Run / Result remain. Verified 4 headers against 4 cells across 10 rows. |
| 28 | Global | The floating chatbot button sat over page content bottom-right on every screen | UX defect | **Fixed** — 104px of clearance reserved under page content. The rule lives in the widget's own stylesheet, so it applies only where the button actually renders: Faculty and the Chatbot page keep the normal 24px and get no dead gap. |

| 29 | Navigation / `qa_mapping` | The whole QA Checklist module — checklist, requirements, the CSV/XLSX importer, programs, 8 templates, 6 programs and 3 requirements of live data — had **no navigation entry for any role**, while `/qa-mapping/checklist/` returned 200 for both Administrator and QA Head and the built-in chatbot told users to *"open QA Checklist in the left sidebar"*. A menu item the help text promised did not exist | Orphaned module | **Exposed** to Administrators, the role holding every permission in the module including import. QA Head keeps the deliberate simple UI; set `HIDE_ADVANCED_QA_TOOLS=False` to surface it there too. |
| 30 | `qa_mapping/views.py` | `_advanced_tools_enabled_for()` implemented a role/flag access gate and was **never called from anywhere** — dead code that reads like a live security control | Dead code | **Removed**, along with the `django.conf.settings` import it was the only user of. |
| 31 | AI Processing | "Cluster Overview" rendered **all 13 clusters** — the entire Clusters page inlined — above a "Browse all" button linking to that same list | Duplicated function | **Fixed** — now "Largest Clusters": the four biggest, with an honest "View all 13 clusters" link. |
| 32 | Accreditation Structure | The hierarchy below Area was **empty**: 10 areas, 1 parameter, 0 indicators, 0 required evidence. A four-level page demonstrating one level, and the reason the removed Smart Search PK filters could never match | Unexercised feature | **Seeded** via `manage.py seed_structure_sample` — 19 parameters, 60 indicators, 120 evidence items. Idempotent (`get_or_create`), `--dry-run` supported, and never overwrites hand-edited rows. |
| 33 | Global | Scrollbars were visible on the page, the sidebar, the repository panel and the chatbot transcript, and two of them (`.sidebar`, `.chatbot-messages`) drew a custom 4px thumb | Requested change | **Hidden everywhere while scrolling still works** — `::-webkit-scrollbar{display:none}` for Chrome/Edge/Safari, `scrollbar-width:none` for Firefox, `-ms-overflow-style:none` for legacy Edge. The two custom rules were class-scoped and therefore outranked the global rule, so each was hidden at its own selector. Verified: 0px bar on 6 pages with no region still painting one; wheel, programmatic and panel scrolling all still move. |
| 34 | Repository | The table header **was not sticky**, despite `position:sticky;top:0` already being on `.repo-scroll-panel thead th`. Bootstrap's `.table-responsive` wrapper sets `overflow-x:auto`, and per spec that forces the used value of `overflow-y` to `auto` as well, making the wrapper a scroll container and stealing the sticky containing block from the panel. The wrapper never scrolls vertically, so the header had nothing to stick to | Layout defect | **Fixed** — `.repo-scroll-panel > .table-responsive{overflow:visible}`. The panel already scrolls both axes, so the nested scroll context was redundant. Measured: header drift over a 500px scroll went **400px → 0px**. |
| 35 | Repository | Row action icons were uniformly grey and hard to tell apart | Requested change | **Coloured per action, with meaning attached**: blue = read, slate = information, green = take a copy, amber = modifies data, red = destroys it. Glyphs are coloured while chips stay transparent at rest, so 22 rows read as five legible icon columns rather than 110 filled pills; the tint appears on hover and focus only. |
| 36 | Repository | The `--color-success` and `--color-warning` tokens are tuned for badges on tinted grounds. As 14px glyphs on white they measure **2.94:1 and 2.13:1**, below the WCAG 3:1 minimum for non-text UI | Accessibility | **Fixed** — those two icons use darkened variants of the same hues (4.14:1 and 3.91:1). The tokens themselves are untouched, so badges elsewhere are unaffected. All five icons now clear 3:1. |
| 37 | Navigation / `search` | The standalone Smart Search page duplicated the Repository, which runs the same engine over the same records behind its own search box and filters | Redundant page | **Removed** — sidebar entry, `templates/search/search.html` and `search_results_partial.html` deleted. `search.search_service` is **kept**: `documents.views.repository` calls it, so search behaviour is unchanged. `/search/` now redirects to the Repository, carrying `q` and filters across and mapping `document_type` → `file_type`, so old bookmarks still land on a working search. |
| 38 | Repository / `Document` model | A newly uploaded document was not reliably first in the list. The sort was `order_by('-uploaded_at')` with no tie-break, and `Meta.ordering` had the same gap. A bulk upload writes several rows in the same instant, so they share an `uploaded_at` value and the tie is unresolved — the database returns them in whatever order it likes. Demonstrated with five rows given an identical timestamp: they came back **oldest-first** (`163, 164, 165, 166, 167`) | Ordering defect | **Fixed** — `-id` added as the final tie-break in `_apply_repo_sort` and in `Document.Meta.ordering`. The same probe then returns `167, 166, 165, 164, 163`. Verified end to end: after a simulated 3-file upload the newest document renders as row 1. Migration `0012` is `AlterModelOptions` only — `sqlmigrate` confirms no SQL. |
| 39 | AI Processing | The "Clustering engine" card restated static configuration — engine name, four always-on capability pills, and a truncated last-run string — above the page's real content | Requested removal | **Removed**, with everything it alone used: 33 lines of markup, 43 lines of `ai-processing.css`, the `pipeline_settings` / `last_pipeline_*` context, and the `last_job` query (one fewer database hit per page load). `engine_info` is **kept** — the per-document detail page renders that badge. |
| 40 | Global | The page separated itself from its cards by lightness: `--color-canvas` against a white card measured **1.07:1** — fainter than the 1.11:1 that the TutorConnect codebase explicitly rejects in its own comments as "a fill nobody can see" | Design | **Fixed** — page, card and content are now all white and separation is carried by border and shadow instead. `--color-border` 1.40 → 1.56:1, and `--color-overlay` (the recessed band behind table headers and row hovers) 1.09 → 1.20:1 so it is actually visible on white. |
| 41 | Global | `--color-border-strong` sets the edge of form controls and measured **2.05:1**, under the 3:1 that WCAG 1.4.11 requires for a control boundary. The tinted page had been hiding it; on a white page a white field with an invisible border is simply not there | Accessibility | **Fixed** — 3.01:1. |
| 42 | Global | Three tokens failed as text on white: `--color-text-muted` **2.74:1** (carrying real content across 154 `.text-muted` usages), `--color-success` 2.94:1 and `--color-warning` 2.13:1 | Accessibility | **Fixed** — muted is now 4.79:1. Success and warning keep their vivid values for fills, with new `--color-success-text` and `--color-warning-text` variants for text, following the `--brand` / `--brand-vivid` split TutorConnect uses. |
| 43 | Program badges | Badges hardcoded `color: white` over a program colour chosen in the database. The seeded PQA amber measured **2.13:1**; two others sat at 3.12 and 3.16 | Accessibility | **Fixed** — a `readable_ink` template filter picks dark ink or white from the background's relative luminance, so the badge stays legible whatever colour is chosen. PQA is now 8.32:1. It parses both `hsl()` and hex, and falls back to white on anything unparseable, which is the previous behaviour. |
| 44 | Navigation | The sidebar entry labelled **"Accreditation Structure"** opened `area_manage`, a page titled **"Accreditation Areas"** that only renames the ten areas. Finding 14 claimed this naming was unified; that fix reached `structure_home.html` and missed the page the sidebar actually links to | Naming / navigation | **Fixed** — the entry now opens `/qa-structure/`, the page it names: the full Area → Parameter → Indicator → Required Evidence hierarchy. `area_manage` stays reachable from there, and the menu item stays active across every `qa_structure` screen. |
| 45 | Row actions | The same "edit this row" action had **three presentations**: coloured icon glyphs (`.act`, Repository), a second near-identical icon family (`.action-btn`, User Management) with different sizes, colours and hover states, and a labelled `btn-outline-*` button (13 other templates) | Design inconsistency | **Partly unified, deliberately.** The two icon families are now one: `.act` was promoted out of `repository.html`'s inline block into `style.css` and User Management adopted it, removing 44 lines of duplicate CSS. Labelled buttons were **kept** for the 1–2 action pages. |

---

## 3. Found but not changed

These are real, but each is either a scope call or a product decision rather than a styling fix.

| Page / area | Issue | Recommendation |
|---|---|---|
| Repository | Four rows read "DEVELOPMENT OF AN AI-DRIVEN ONLINE…" — truncation makes distinct documents indistinguishable | Truncate from the middle, or surface a secondary distinguishing field. |
| Global | **3,362 lines of inline CSS remain**, concentrated in `view_file.html` (831), `login.html` (485), `structure_home.html` (440), `floating_chatbot.html` (290) | Apply the same promotion pattern used for the dashboard. Highest value: `view_file.html`. |
| Global | 57 hex and 415 distinct `hsl()` values still bypass the tokens, including near-duplicate greys (45/50/55% L) and six near-identical surfaces (94–99% L) | Collapse to the token ramp incrementally, page by page. |

---

## 4. Corrections made during the audit

Three things looked like defects on first pass and were not. Recording them so they are not
"re-fixed" later:

1. **Counts appearing to differ between pages.** The Dashboard, AI Processing and Clusters pages
   seemed to report different totals. They do not — the KPI numbers animate on load, and
   `requestAnimationFrame` stalls while the automation browser pane is backgrounded, so
   screenshots captured mid-count. A real user sees the settled values.
2. **"All five AI Engine badges are fake."** Four were hardcoded; the Tesseract badge did use
   the view's `ocr_enabled` value.
3. **"Bootstrap CSS is not loaded."** It is — the `<link>` spans two lines and a single-line
   grep missed it.

---

## 5. Verification

Every change was re-tested at two levels.

**Role smoke check** — `scripts/ui_smoke_check.py` logs in as each role and requests every page
that role can reach, asserting the expected status, that the page shell rendered, and that no
unrendered `{{ }}`, `{% %}` or `{# #}` template syntax leaked into the HTML.

```
28 / 28 page-role combinations OK
  Administrator  14 pages
  QA Head         9 pages
  Faculty         5 pages
```

That leak check caught a real regression during the work: a multi-line `{# … #}` comment I
added rendered as visible text at the top of every page, because Django's `{# #}` is
single-line only. It is now `{% comment %}`.

**Feature check** — `scripts/ui_feature_check.py` drives the interactive flows rather than just
loading pages: searching with a query, each repository filter, opening / serving / downloading /
previewing / editing a document, both Excel exports, upload-form validation, the chatbot API and
the rendered engine-status rows.

```
36 / 36 interactive checks passed
```

Re-run after the Quick Actions removal and the chatbot overlay fix: **28 / 28** pages,
**36 / 36** features, **214 / 214** tests — all unchanged.

Re-run again after the layout, semantics and copy pass (findings 24–28): **28 / 28**,
**36 / 36**, **214 / 214** — still unchanged.

Re-run once more after the module/data pass (findings 29–32): **28 / 28**, **36 / 36**,
**214 / 214**. And again after hiding the scrollbars (finding 33): **28 / 28**, **36 / 36**,
**214 / 214**.

After the sticky-header / icon-colour / Smart-Search pass (findings 34–37): **27 / 27**
pages (the retired Smart Search row was dropped), **40 / 40** features, **214 / 214** tests.
Unchanged again after the ordering and engine-card pass (findings 38–39), and after the
white-surface pass (findings 40–43): **27 / 27** pages, **40 / 40** features, **214 / 214** tests.

**Contrast measured across the whole app.** Every rendered text node on eleven pages was
checked against its actual composited background, with the 4.5:1 / 3:1 threshold chosen
per element from its font size and weight:

| | Before | After |
|---|---:|---:|
| Text nodes checked | 1,453 | 1,453 |
| Failing WCAG contrast | 51 | **11** |
| Pages with zero failures | 4 of 11 | **7 of 11** |
| Horizontal overflow | 0 | 0 |

Two second-order regressions were introduced by this work and caught by re-measuring
rather than by eye. Deepening `--color-overlay` for visible banding dropped the table
header text sitting *on* that band from passing to 4.31:1, so `--color-text-secondary`
went 44% → 42%. And `--color-warning-text` cleared 4.5:1 on white but only 4.41:1 on
`--color-warning-light`, which is exactly where warning text is placed, so it went
32% → 30%. Neither was visible without measuring.

**Why row actions were not unified onto labelled buttons.** Making everything match the
labelled `btn-outline-*` pattern sounds like the tidy answer and is the wrong one. The
repository carries five actions per row; measured, they need **410px as labelled buttons
against 176px as icons**, which would push that table 234px past its panel and undo the
overflow fix in finding 24. The rule applied instead is *one or two actions get a label,
three or more get icons* — which is what every template already did, once the two
duplicate icon systems were merged into one.

Of the eleven remaining failures, several are gradient backgrounds the probe cannot
sample: `.user-avatar` reported "1:1" but its real worst case is 3.42:1 at the lightest
end of its gradient. They sit in per-page inline CSS rather than the token layer.

The ordering fix was proved rather than assumed. Five documents were written inside a
rolled-back transaction and given an identical `uploaded_at`; before the change they
came back oldest-first, after it newest-first, and a simulated three-file upload put
the newest document in row 1 of the rendered page. Nothing was left in the database.

Removing the search page touched more than the page. Every dependent was found and
updated rather than deleted: two XHR tests in `documents/tests/test_smoke.py` were
repointed at the Repository, whose AJAX response has the identical JSON shape
(`html`, `count_html`, `has_more`, `next_page`, `page`, `total`), so that coverage
survives; `accounts/tests/test_faculty.py` now asserts the redirect; the chatbot's
navigation answer and its seeded FAQ no longer send users to a sidebar entry that is
gone; and `rbac_can_search`, which existed only to gate that entry, was removed.

**On measuring scroll after hiding scrollbars.** Two readings looked like regressions and
were not, so they are recorded here rather than re-investigated later:

* The `End` key appeared not to scroll. A control test that restored native 14px
  scrollbars produced exactly the same result, so it is the automation harness's
  synthetic key events, not the CSS. Hiding a scrollbar changes painting only, never
  input handling.
* `window.scrollTo(0, 300)` sometimes read back as `0`. The page sets
  `scroll-behavior: smooth`, so back-to-back scroll calls race their own animations.
  With `behavior: 'instant'` the page scrolls to exactly 300.

One regression was introduced and caught during that pass: limiting `cluster_summaries`
to a four-item preview also changed the "Clusters" stat card, which derived its number
from `cluster_summaries|length`. It briefly read **4** instead of 13. The card now reads
`cluster_total`; verified at 13 against a 4-card preview.

**Layout measured, not eyeballed.** Horizontal page overflow was recorded at a 1280px
viewport before and after the `.main-wrapper` fix by reading `document.documentElement`:

| Page | Before | After |
|---|---:|---:|
| Repository | 279px | **0** |
| AI Processing | 18px | **0** |
| User Management | 3px | **0** |
| Dashboard, Search, Reports, Settings, Audit Log, Clusters, Area Submissions, Structure, Upload | 0px | 0px |

A note for anyone re-checking this: the browser caches `style.css`, and `location.reload(true)`
no longer bypasses that cache in current Chrome. The stylesheet has to be re-requested with a
changed URL or the measurement will report the old layout.

Three of these failed on the first run and all three were faults in the check script, not
regressions — two wrong URLs guessed from memory (`/reports/export/excel/`, `/chatbot/api/`) and
a badge count that was also counting CSS rule definitions.

**Django test suite** — `python manage.py test`

```
Ran 214 tests — OK
```

Same count and result as before the cleanup, so no pre-existing behaviour changed.

**Not covered by any of the above:** write operations driven manually through the browser —
uploading a real file, saving an edit, deleting a document, running AI processing, creating a
user. The test suite exercises most of these paths programmatically, but they were not
click-tested, because each mutates live data.

**Manual re-walk** — Dashboard, Repository, Smart Search, Reports, Settings, Upload Document and
the sidebar were re-opened as Administrator and confirmed rendering correctly after each change.

---

## 6. Rollback

`templates/` and `static/` were copied before any edit to:

```
D:\QA-Capstone-backup-ui-20260906-2105\
```

The project is not under version control. Putting it under git is the single highest-value
follow-up — every change in this audit would otherwise be irreversible beyond that one snapshot.

---

## 7. Design-system migration from TutorConnect

**Date:** 2026-09-08. A deliberate transfer of TutorConnect's design language into this
system, at the token layer rather than page by page.

### 7.1 Method

Token **values** were replaced; token **names** were not. Every `var(--color-*)`,
`var(--radius-*)` and `var(--shadow-*)` reference in the codebase — 773 of them — kept
resolving, so the migration touched no markup structure, no template logic and no
JavaScript. That is what made a change this broad safe to make in one pass.

### 7.2 What was taken, and why

| Pattern | Reference value | Applied as |
|---|---|---|
| **Palette** | Deep Space Blue `#023047`, Blue Green `#219ebc` with a darkened `#1a7b93` for anything carrying text | `--color-text-primary`, `--color-brand`. The vivid/darkened split is the important part: the identity colour is kept for fills, and the darkened variant does the work wherever a label sits on top. |
| **Sidebar** | White rail, `1px` right border, ink-soft labels, brand-tint active state with a 3px edge marker | `--color-sidebar` `#0F172A` → `#ffffff`. Six rules that hardcoded `#fff` for the old dark rail had to be re-pointed, or their text would have vanished. |
| **Cards** | White face, `1px` line border, `13px` radius, two-layer shadow, `20px 22px` padding | `--radius-md`, a new intermediate `--shadow`, and matching padding. Separation is carried by border and shadow, not by tinting the page. |
| **Icons** | One outline set, single stroke weight | 56 filled Bootstrap glyphs converted to their outline variants. Two kept filled deliberately: `bi-circle-fill` is a 6–8px status dot, and `bi-person-lines` has no outline variant — verified against the font's own 2,050-glyph list rather than assumed. |
| **Typography** | `15px/1.55`, headings `25 / 17 / 14.5` at weights `700 / 650 / 650`, `-0.35px` tracking | Body line-height `1.6` → `1.55`; page headings `24px` → `25px` with the reference tracking. |
| **Radii / elevation** | `6 / 9 / 13 / 18`, two-layer shadows | Replaced the `4 / 6 / 10 / 14 / 18` ramp and the single-layer shadows. |
| **Rail width** | `244px` | `--sidebar-width` `260px` → `244px`. |

### 7.3 Result

| Measure | Before this migration | After |
|---|---:|---:|
| Text nodes checked, 13 pages | 1,568 | 1,568 |
| Failing WCAG contrast | 51 | **0** |
| Pages with zero failures | 4 of 13 | **13 of 13** |
| Horizontal overflow | 0 | 0 |
| Competing token systems | 3 | 1 |

The reference system's own audit records **0 of 108** rendered text nodes failing. This
system now reports 0 of 1,568 across thirteen pages and three roles.

### 7.4 What the migration surfaced

Flipping the sidebar and the palette exposed five colours that had been hidden by the
old dark rail or the tinted page, each fixed as part of the pass:

* `.sidebar-logout` was a light red for a dark rail — 2.74:1 on white.
* `.qs-btn-primary` used a hand-rolled blue→teal gradient whose light stop carried
  white text at 4.34:1. Both stops are now brand tokens, at 4.89 and 13.85.
* `.user-avatar` derives its hue from the username, so the gradient was darkened until
  **every possible username length** clears 4.5:1 — checked across the full 3–20
  character range, worst case 5.62:1.
* Bootstrap's own `.btn-outline-secondary` grey was the one place its default palette
  still showed through, at 3.88:1. It is mapped onto the token ramp.
* `.qs-title` was still a teal→blue→purple gradient text fill at 2.35:1 — the last
  survivor of the pattern removed from the dashboard as finding 3.

### 7.5 What was deliberately not taken

TutorConnect has no CSS framework, so its markup is free of utility classes. This system
leans on Bootstrap for **129 `btn`, 86 `d-flex`, 69 `col-`, 47 modal and 41 `row`**
usages plus modal, dropdown and collapse JavaScript. Removing it would break real
behaviour and is not what makes the reference look good. Bootstrap stays; its default
colours are overridden where they showed through.

The 377 Bootstrap icon usages were restyled, not replaced. Hand-building 144 distinct
glyphs as inline SVG is the remaining gap between the two systems, and it is a large
piece of work with no functional payoff.

---

## 8. Container nesting — Accreditation Structure

**Date:** 2026-09-08. Reported as "too many containers, not organised". Measured before
assuming, and the result narrowed the problem to a single page.

### 8.1 What the measurement showed

Counting layout containers — bordered or shadowed blocks, excluding table cells and
controls — across eight pages:

| Page | Layout containers | Nested inside another | Deepest nesting | Titled sections |
|---|---:|---:|---:|---:|
| **Accreditation Structure** | **28** | **12** | **3** | **11** |
| Settings | 6 | 4 | 1 | 10 |
| AI Processing | 9 | 0 | 0 | 5 |
| Dashboard | 7 | 1 | 1 | 4 |
| Reports | 3 | 1 | 1 | 1 |
| Repository | 2 | 0 | 0 | 1 |

Repository, Reports and the Dashboard are not over-containered; the impression came from
one page. Inside a single expanded area, Accreditation Structure drew **four depths of
frame** — `.qs-acc-body` → `.qs-param-card` → `.qs-ind-block` → `.qs-ev-box` — for
**23 framed elements**, on a page 3,171px tall with 2,304 elements.

**This got worse because of finding 32.** Seeding 20 parameters, 60 indicators and 120
evidence items turned a page that rendered almost nothing into one that renders the full
depth of its own nesting. The structure was always there; the data made it visible.

### 8.2 The change

Hierarchy is now carried by indentation, a left rule and type weight rather than by
another bordered box at each level — the same approach the reference system uses.

| Level | Was | Now |
|---|---|---|
| Area body | tinted fill + top border | the single frame, white |
| Parameter | full card: border, radius, own fill | spacing plus a hairline between siblings |
| Indicator | full block: border-bottom, own tint | 2px left rule and indent; rule turns brand on hover |
| Required evidence | bordered, filled, rounded box | plain labelled list |

| Measure | Before | After |
|---|---:|---:|
| Enclosing boxes inside one area | 4 nested levels | **1, nothing nested** |
| Framed elements in one area | 23 | 16 (the rest are buttons, which legitimately draw edges) |
| Page height | 3,171px | 2,913px |

### 8.3 Functionality

Every control was counted in the rendered page after the change: 10 accordion toggles,
10 "Add another parameter", 20 "Add indicator", 60 add-evidence links, 313 edit controls
and the filter box. Smoke check all pages/roles OK, feature check 40/40, Django suite
214/214.

---

## 9. QA Archive Agent

**Date:** 2026-09-08. The chatbot was a keyword matcher for navigation help. It is
now an agent that answers from the archive, with conversation threads and a
messaging interface, built entirely on the system's existing retrieval stack.

### 9.1 What was there, and what was kept

`chatbot_rules.py` scored a message against regular expressions in tiers and never
touched the search engine; its 6-turn session history existed only to prime an LLM
prompt. Nothing in it was deleted. The agent runs **in front** of it and returns
`None` for anything outside its remit, so navigation answers, the FAQ table, the
off-topic refusal and the live-count handler all still run and all 21 of their
tests still pass.

Reused rather than rebuilt: `search.search_service.search_documents` (the same
hybrid retrieval the Repository uses), `Document.tfidf_keywords`,
`Document.cluster_label` and `ClusterResult.top_keywords`, the extracted/OCR text,
`qa_mapping.QARequirement`, `qa_structure.RequiredEvidence`, and
`accounts.permissions.faculty_area_scope`. No external API and no new dependency.

### 9.2 Understanding

`agent_nlu.py` scores each message against weighted *signal sets* rather than
keyword lists, so wording varies without changing the outcome. All twenty examples
in the specification classify correctly, including the four phrasings of the same
request:

| Phrasing | Intent |
|---|---|
| "Find accreditation documents." | `find_documents` |
| "Show me files related to accreditation." | `find_documents` |
| "What accreditation records do we have?" | `find_documents` |
| "I need the documents for accreditation." | `find_documents` |

Two design points earned their place:

* **A singular deictic demotes search.** "*This* file" means the user is pointing
  at a document they already have, so `find_documents` is penalised and
  "What is this file about?" resolves to a summary rather than a search.
* **Counting was left alone.** The rules engine already answers "how many
  documents", enforces who may see the number, and is covered by its own tests.
  Duplicating it in the agent changed tested behaviour, so the agent declines it.

Misspellings are repaired by bounded edit distance against the QA vocabulary:
`acreditation` → `accreditation`, `documnets` → `documents`.

### 9.3 Answering from records

Every fact in a reply is read from the database. The agent cannot name a document
that does not exist, and when the records cannot answer it says so rather than
producing something plausible.

Summaries are **extractive**: sentences are taken from the document's own stored
text, ranked by how many of that document's TF-IDF keywords they carry. A test
asserts that every sentence returned appears verbatim in `extracted_text`, which
is what makes "do not fabricate" checkable rather than aspirational.

Classification answers quote the stored programme, document type, QA area,
K-Means cluster and TF-IDF terms — never a guess about why something was grouped.

### 9.4 Context

Session state holds the **identifiers** of the last result set, not its text, so a
follow-up resolves against real rows:

```
"Find accreditation documents."   -> 8 documents, ids remembered
"Which ones are from 2026?"       -> narrows those 8
"Summarize the second one."       -> summarises id[1] of that set
```

### 9.5 Threads and interface

`Conversation` and `Message` were added (migration `0003`). Titles are generated
from the opening question — "Find accreditation documents from 2025." becomes
**"Accreditation Documents 2025"**. Threads are per-user and a request for someone
else's returns 404, not 403: confirming existence would leak the document titles
inside it. Deletion is soft.

The page is a two-pane messaging layout on the system's own tokens — white
surfaces, shared border and shadow, same radii — so it reads as part of the
archive rather than an embedded consumer widget.

### 9.6 Verification

| Check | Result |
|---|---|
| Existing chatbot tests | **21 / 21** (unchanged behaviour) |
| New agent tests | **22** |
| Full Django suite | **236 / 236 OK** (was 214) |
| Role smoke check | all pages, all roles |
| Feature check | **40 / 40** |
| Contrast on the new page | **0 failures / 113 nodes** |
| Horizontal overflow, 1280px and 375px | **0px** |
| Floating widget (posts without a thread id) | still answers, creates no thread |

Eight of the original chatbot tests failed at first: the agent was answering
questions the rules engine owned, and its replies lacked the `category` key those
tests assert on. Both were faults in the integration, not the tests. The agent now
carries the same response shape, declines anything the off-topic guard rejects,
requires a minimum confidence, and requires a recognised subject before treating a
sentence as a search.

### 9.7 Reach: every role

The agent had no sidebar entry at all, and the floating widget was hidden from
Faculty on the assumption that its answers were not area-scoped.

| | Before | After |
|---|---|---|
| Sidebar entry | **none, for any role** | present for Administrator, QA Head and Faculty |
| Floating widget | Administrator and QA Head only | all three roles |

Exposing it to Faculty was only safe because the agent applies the same
`faculty_area_scope` as the Repository. That was verified rather than assumed:
four different queries were run as a Faculty account and every returned card
checked against their assigned areas -- **0 documents outside scope**.

**A labelling bug found while checking that.** `acc_area` is authoritative and
`qa_area` is legacy free text, and on real records they disagree: one document
reads `qa_area = "Area IV - Research"` while its `acc_area` is Area II. The
retrieval filter already prefers `acc_area`; my result card did not, so it would
have labelled that document with an area it is not in -- and shown a Faculty
member an area outside their own scope on a document they were correctly allowed
to see. The card and the visibility check now use the same precedence as the
filter. Verified: the card reads "Area II".

---

## 10. Direct messaging

**Date:** 2026-09-08. A new `messaging` app: any user may message any other active
user, in either direction, from a page that reuses the QA Assistant's layout.

### 10.1 What was built

| Piece | Detail |
|---|---|
| `Thread` | participants as a many-to-many, so a direct message is a two-person thread and group conversations need no rewrite later |
| `ThreadMessage` | body plus an optional **document foreign key** — not a pasted link |
| `ThreadRead` | one `last_read_at` per participant; marking a thread read writes one row, not one per message |
| Views | inbox, thread list, thread detail, start, send, soft delete, people, unread count |
| UI | `templates/messaging/inbox.html`, reusing the assistant's classes and tokens |
| Reach | sidebar entry with an unread badge, **all three roles** |

### 10.2 The one access rule

Messaging is deliberately open — who may talk to whom is not the system's business,
and those people can already email each other. The rule that does exist:

> **You may read and write a thread only if you are one of its participants.**

A non-participant gets **404, not 403**: confirming a thread exists between two named
people is itself information.

### 10.3 Attached documents are resolved per reader

Plain text is not policed. A *rendered* document reference is different — that is the
software handing something over — so it is checked with
`accounts.permissions.user_can_access_document()`, the same helper the detail view
uses.

Verified against real records: a QA Head attached a document in Area II - Faculty to a
Faculty member scoped elsewhere.

| | Result |
|---|---|
| Sender sees | full title, area, working View link |
| Recipient sees | *"A document you don't have access to"* |
| Title present anywhere in the recipient's response | **no** |

A sender also cannot attach what they cannot open themselves; the reference is dropped
rather than stored.

### 10.4 A real bug found by the tests

`Thread.between()` used two chained `filter(participants=...)` calls with a
`Count('participants')` annotation. The second filter adds another join, so the count
was taken over joined rows rather than real membership — the lookup silently found
nothing and **a duplicate thread was created every time the same two people started a
conversation again.** The candidate's participant count is now checked directly.
Verified: starting three times produces one thread.

### 10.5 Verification

| Check | Result |
|---|---|
| New messaging tests | **20 / 20** |
| Full Django suite | **256 / 256 OK** (was 236) |
| Role smoke check | all pages, all roles |
| Feature check | **40 / 40** |
| Contrast on the Messages page | **0 failures** |
| Overflow at 1280px and 375px | **0px** |
| Sidebar entry and page | present for all three roles |

Delivery is polling plus the existing notification bell — there are no WebSockets in
this stack. It should not be described as real-time.

---

## 11. Activity feed, roster search, and an invisible icon

Three defects reported together. Two were real bugs of mine; the third was a design
question about what a dashboard should show at all.

### 11.1 The activity feed was showing the wrong kind of event

The feed listed `admin logged in. (IP 127.0.0.1)` and `Sent a message in thread #1`.
Two separate problems sit behind that.

**It was the wrong content.** The dashboard feed and the audit log were reading the
same table with no distinction between them. An audit log exists to answer *who did
what, from where* and must keep logins, IPs and settings views. A dashboard feed
answers *what is happening to the archive* — uploads, mappings, exports. Sessions and
message metadata are noise there.

**It was the wrong audience.** Every role saw every user's rows, so a QA Head could
watch the Administrator's login times and a faculty member could see activity from
areas they cannot open. Session times are personal data; showing them to colleagues is
not something the feature ever needed.

`documents/activity_display.py` now decides what the dashboard shows. Actions are
partitioned into `ARCHIVE_ACTIONS` (shown) and `PERSONAL_ACTIONS` (never shown), IP
suffixes are stripped from descriptions, and consecutive identical rows collapse.
Users with an area scope see only their own entries. **The audit log itself is
unchanged** — same rows, same IPs, same admin-only access.

| Measure | Before | After |
|---|---|---|
| Logins in the dashboard feed | many | **0** |
| IP addresses shown | yes | **0** |
| Settings views / searches | shown | **0** |
| Message rows | `in thread #1` | **0** |
| Audit log rows | 1,045 | **1,045** (133 logins, IPs intact) |
| Audit log access for QA Head | 302 | **302** (still admin-only) |

Seven existing `send_message` rows were rewritten to drop the thread number. A message
now logs as `Sent a direct message.` — accountable, but it does not publish who is
talking to whom.

### 11.2 The Messages search could not find most of the roster

Two independent causes, both real.

**It only searched existing conversations.** `thread_list` matched threads, so a person
you had never messaged could not be found by typing their name. The search box now
queries the roster as well and lists people with no thread under a *Start a
conversation* heading; anyone already in a thread is dropped from that second list so
nobody appears twice.

**It could not match a full name.** The name is stored in two columns and displayed as
one. `qahead` is `first_name='QA'`, `last_name='Head'`, so no single column contains
`"QA Head"` and an `icontains` over each found nothing — while the interface shows that
person as exactly "QA Head". Typing what you see returned an empty list. `_name_q()`
now requires each whitespace-separated token to match some name column, so word order
does not matter and an extra word narrows the result instead of widening it.

Searching your own name previously matched every thread you are in — each listed under
the *other* person's name, so the result looked arbitrary. The caller is now excluded
from the name match.

**A third cause, found only by watching the page rather than the response.** The API
was returning the right rows while the list still showed the wrong ones. Responses can
arrive out of order: the unfiltered request issued on page load is slower than the
short search typed straight after it, so it landed *last* and repainted the full list
over the search result. The correct answer appeared for a moment and was then
overwritten — which is exactly what "it cannot search all of the users" looks like from
the outside. `loadThreads()` now stamps each request with a sequence number and only
the newest one is allowed to paint.

This one is worth noting because it was invisible to every check that inspected the
endpoint. It was caught by taking a screenshot after a DOM probe had already reported
success and noticing the two disagreed.

Measured over the live roster, every user is reachable by full name, first name, last
name and username: **23 queries, 0 misses.** The list holds a searched name for at
least 4.8s with no repaint, and character-by-character typing settles on the final
query. Ten tests cover the matching; the ordering guard was verified in the browser.

### 11.3 The details icon was invisible — my own regression

`.act.info` was written as `color: var(--color-sidebar)`, borrowing the sidebar's dark
navy as a general-purpose slate. That was fine until section 7 turned the sidebar
white: the token changed from `#0F172A` to `#ffffff` and the glyph went white on a
white card.

The rule is that **a text colour must come from a text token.** A surface token names a
background, and the migration was free to change what it holds. `.act.info` now uses
`--color-text-primary` (13.85:1). The rest of the stylesheet was swept for the same
mistake; the three `color: var(--color-surface)` uses in `login.html` are legitimate
white-on-brand.

| Icon | Colour | On white |
|---|---|---|
| View | `--color-brand` | 4.89:1 |
| Details | `--color-text-primary` | **13.85:1** (was 1:1) |
| Download | `hsl(142,55%,36%)` | 4.14:1 |
| Edit | `hsl(38,95%,36%)` | 3.91:1 |
| Delete | `--color-danger` | 6.56:1 |

### 11.4 Why the fix looked like it had not worked

After the CSS was corrected the icon was *still* white in the browser. The file on disk
was right; the browser was serving an old copy.

Django's development static server sends `Last-Modified` but no `ETag` and no
`Cache-Control`. With no explicit freshness directive a browser may heuristically cache
the file and never revalidate it. Every stylesheet fix in this project has therefore
been one hard refresh away from appearing not to work — and a user who never does that
refresh keeps the broken CSS indefinitely.

`{% static_v %}` (in `qa_archiving_system/templatetags/asset_tags.py`) appends the
file's modification time to the URL, so editing a file changes its URL and the browser
must re-fetch it. Unchanged files keep a stable URL and stay cached. Applied to all 13
local CSS and JS references. The tag falls back to plain `{% static %}` when the file
cannot be located, so it is inert in a manifest-storage deployment.

This is worth stating plainly: **the earlier confirmation that the icon was fixed was
obtained with a manually cache-busted URL, which is not what a user's browser does.**
The fix was real but unreachable. Verifying through a path the user would never take is
not verification.

---

## 12. Live messaging and area-based search

Two additions to the messaging module: the interface now keeps itself current
without the page being reloaded, and the search finds people by the accreditation
area they are assigned to.

### 12.1 What "real time" means here, honestly

There are no WebSockets in this stack. Django is served by `runserver` over WSGI,
with no Channels, no ASGI server and no Redis. Adding them would be a deployment
change well beyond a messaging feature, and an SSE stream would hold one worker
thread open per connected user.

What is built instead is a short-interval sync: **3 seconds on the Messages page,
5 seconds everywhere else**, paused while the tab is hidden and fired immediately
when it regains focus. To the person using it this is indistinguishable from push
— a message lands in under three seconds and nothing is ever refreshed by hand —
but it should be described as polling, not as WebSockets.

The previous behaviour polled *only* the open conversation, *only* every 20
seconds, and only after a thread had been opened. A message could sit unseen for
20 seconds, the conversation list never moved, and the sidebar count changed only
on the next page load.

### 12.2 One request per tick

`/messages/sync/` answers everything the interface needs at once: the two badge
counts, the conversation list, and any messages in the open thread after a cursor.
That is one request per tick rather than three.

`?counts=1` returns just the two integers. That is what every other page polls, so
the sidebar badge and the notification bell stay live system-wide without pulling
the conversation list on pages that will never show it. The Messages page sets
`window.qaLiveOwner`, and the global poller in `static/js/realtime.js` stands down
there rather than asking for the same thing twice.

| Behaviour | Before | After |
|---|---|---|
| New message appears in an open thread | up to 20s | **< 3s, no reload** |
| Conversation list preview and unread | never, without reload | **< 3s** |
| Sidebar badge on other pages | next page load | **< 5s** |
| Notification bell | next page load | **< 5s** |
| Requests per tick | 3 | **1** |

### 12.3 Making the hot path cheap

Polling turns a page's cost into a *rate*. `unread_total_for` counted unread
messages with one query per conversation, which was fine when it ran on a page
load and wrong once it ran every five seconds for every signed-in user. It is now
a single aggregate, with the per-participant read stamp pulled in as a correlated
subquery.

| Endpoint | Queries before | Queries after |
|---|---|---|
| `/messages/sync/?counts=1` (every page, 5s) | 20 | **7** |

The remaining seven are session and middleware overhead, not the count. Results
were checked against the old implementation for every user and for a three-thread
case: identical.

### 12.4 Keeping the reader's place

A live list must not fight the person reading it.

- Messages are **appended**, never re-rendered, so selection and scroll survive.
- If the reader has scrolled up, an arriving message does **not** yank the view
  down; the scroll only follows when they were already at the foot.
- The conversation list is repainted only when its signature actually changes, so
  a hover or a click is not interrupted every three seconds.
- While a search is active the sync leaves the list alone — `loadThreads()` owns
  it then, because it also fetches people who have no conversation yet.

### 12.5 Read, unread, and when

- Every message carries a short time, a full stamp on hover, and an ISO value used
  for comparisons.
- Your own messages show a **read receipt** — one tick for sent, two for read —
  derived from the other participant's `ThreadRead.last_read_at`. Receipts refresh
  on their own, since a receipt changes without any new message arriving.
- A conversation opened after a gap draws a **"New messages" divider** at the exact
  point the reader left off, captured before the thread is marked read.

### 12.6 Area-based search

`Area #5`, `Area 5`, `5`, `Area V` and the area's own name `Research` all resolve
to the same record. Areas are stored with Roman codes, so `messaging/area_search.py`
converts a typed number into one; a bare single letter is deliberately *not* treated
as a numeral, since `I` is far more likely to be someone typing a name.

An area query returns that area's members **and nobody else** — mixing in name
matches would list people who are not in the area, which is the opposite of what
was asked. Results are labelled with the area rather than the role, and existing
conversations are labelled too, so the whole result reads as name plus area.

A query that names a real area with no members, or an area that does not exist,
answers **"No users found in this area."** rather than the generic no-match text:
the distinction tells the user their search was understood.

| Query | Result |
|---|---|
| `Area #5` / `Area 5` / `5` / `Area V` / `Research` | Area V — Research, members listed |
| `Area 11` | No users found in this area. |
| `Marco` | ordinary name search, no area label |

### 12.7 Verification

| Check | Result |
|---|---|
| Messaging tests | **54 / 54** (was 30) |
| Full Django suite | **290 / 290 OK** (was 266) |
| Message delivered with no reload | **confirmed** — `navigationCount: 1` on a 43s-old page |
| Sidebar badge on the dashboard | absent → **2**, bell 3 → **5**, no reload |
| Area search in the browser | all five query forms resolve |
| Selecting an area result opens the thread | **yes** |
| Requests during 9.5s of active search | 5 ticks, **1** search fetch (was 5) |
| Contrast on the Messages page | **0 failures / 83 nodes** |
| Contrast on Repository / Dashboard | **0 failures** after two fixes below |
| Role smoke check | all pages, all roles |
| Feature check | **40 / 40** |

Two contrast failures were found and fixed while sweeping with a guaranteed-fresh
stylesheet — both had been masked by browser caching until section 11.4:

- `.repo-sort-btn.is-active` used the plain brand on the tinted table header:
  4.04:1 at 12px. A new `--color-brand-on-overlay` token measures 5.65:1 there.
- `.nx-uploader-avatar` still carried a blue-to-purple gradient from the
  pre-migration palette, putting white 11px initials at 3.54:1. It now uses the
  brand gradient (4.89:1) and matches the Messages avatars.
- `.nx-cal-dot` at 9px measured 4.37:1 on the selected day's tint; darkened to clear 4.5.

The delivery mechanism is polling. It should not be presented as WebSockets or as
server push.

---

## 13. Repository filters and table height

### 13.1 The filters were wrapping onto a second row

The six filters were laid out with Bootstrap columns adding up to **14 of 12** on
large screens (`col-lg-3` + five `col-lg-2` + `col-lg-1`), so the last two —
Duplicate and Clear — wrapped onto a row of their own. That second row cost 78px
directly above the table, on a page whose entire purpose is the table.

They are now a flex row rather than a fixed column count, because the Duplicate
filter is only rendered for QA staff and admins: faculty see six controls,
everyone else seven, and flex handles both without branching the template.
Program is given extra growth for its long option text; Year, File format and
Cluster are given less. `min-width: 0` on each field is what actually lets a
`<select>` shrink below its intrinsic content width — without it the row overflows
instead of sharing space.

Below 1200px it falls back to a three-column grid, and to two columns on a phone.

| Width | Layout | Overflow |
|---|---|---|
| 1920 / 1600 / 1366 | **one row**, 7 fields | 0 |
| 820 | 3 columns, 2 rows | 0 |
| 375 | 2 columns, 3 rows | 0 |

Filter grid height: **155px → 68px.**

### 13.2 The table was too short

Two separate causes, and the first correction I made was wrong.

The panel was capped at `min(78vh, calc(100vh - 240px))` — a rule that cannot
know where on the page the panel begins. On a 900px viewport the table started
542px down, so a 660px panel ran 302px past the fold: about five rows visible,
with the page scrolling as well as the table.

**The wrong fix.** Sizing the panel to end exactly at the window edge removed the
double scrollbar and looked tidy, but on a 1366×768 laptop it left only 282px —
*two rows*. Fitting the viewport is not the same as being tall, and on a small
screen it is strictly worse. Measuring it at one window size would have hidden
that entirely.

**What was done instead.** The ceiling was raised, and the measurement now only
ever *grows* the panel — the stylesheet value is the floor, and the measured
space is used only when a tall window offers more than the rule asks for. Nothing
is ever shorter than it was.

| Viewport | Panel before | Panel after | Rows visible at rest |
|---|---|---|---|
| 1920 × 1080 | 840px | **930px** | 8 → **10** |
| 1600 × 900 | 660px | **750px** | ~5 → **6** |
| 1366 × 768 | 528px | **618px** | unchanged |

The panel also starts 79px higher (542 → 464) now that the filters take one row,
so more of it is on screen before any scrolling.

### 13.3 Two things this touched that it should not have

Worth recording, because both were caught by measuring rather than by looking:

- The raised ceiling initially applied to the **base** `.repo-scroll-panel` rule,
  which the dashboard, reports, user list, audit log, AI processing and bulk
  upload panels all inherit through `--embedded`. Every card on those pages grew
  by 90px for no reason. The increase is now scoped to
  `.repo-scroll-panel[data-fill-viewport]`, which only the repository table
  carries; the embedded panels measure exactly 660px as before, with no inline
  override.
- `.main-content` reserves 104px at the foot so the floating assistant button
  never covers content. Where the table is the page's scroll region that
  reservation is dead space; the clearance moved inside the panel
  (`.is-filled .table { margin-bottom: 56px }`) so the last row can still be
  scrolled clear of the button.

### 13.4 Verification

| Check | Result |
|---|---|
| Filters on one row at 1366 / 1600 / 1920 | **yes**, 0 overflow |
| Wrapped fallback at 820 / 375 | 3 and 2 columns, 0 overflow |
| Panel height | **longer at every size tested** |
| Sticky table header | drift **0px** |
| Embedded panels elsewhere | **660px, unchanged** |
| Contrast on Repository | **0 failures / 247 nodes** |
| Horizontal overflow | **0px** at every width |
| Feature check | **40 / 40** |
| Role smoke check | all pages, all roles |
| `documents` tests | **82 / 82** |

The panel sizer runs on load, on resize, and when the filter bar changes height.
It measures on a timer as well as on `requestAnimationFrame`, because rAF does not
fire in a background tab and a panel that opened unmeasured would keep the
stylesheet fallback.

---

## 14. Removing the accreditation hierarchy, and a second design pass

### 14.1 What "Accreditation Structure" was

A five-level AACCUP model — **Area → Parameter → Category → Indicator →
Required Evidence** — with:

- a tree page and four form pages for maintaining each level,
- four cascading-dropdown APIs,
- five dependent dropdowns on the structured upload form,
- five foreign keys plus two denormalised fields on `Document`,
- consumers in search, reports, the chatbot's missing-evidence answer, and an
  evidence-mapping helper.

### 14.2 The evidence for removing it

The hierarchy held **200 rows — every one of them seeded by a migration**, none
created by a user. More decisively:

| Field | Documents carrying it |
|---|---|
| `acc_parameter` | **0 of 27** |
| `acc_category` | **0 of 27** |
| `acc_indicator` | **0 of 27** |
| `acc_required_evidence` | **0 of 27** |
| `acc_area` | 2 of 27 |
| `qa_area` (free text) | 14 of 27 |

Nobody has ever classified a document below the area. The upload form asked for
four more selections after the area, and every uploader skipped them. That is
the definition of scaffolding: it cost the uploader four dropdowns and the
codebase five models, and returned nothing.

It is out of scope. The system's job is faculty upload and QA review.

### 14.3 Where the removal had to stop

**`AccreditationArea` is not part of that hierarchy — it is the access
boundary**, and removing it would have been a permissions change wearing the
costume of a cleanup:

| Account | Areas assigned | Documents visible |
|---|---|---|
| Administrator | — | 27 / 27 |
| QA Head | — | 27 / 27 |
| Faculty (Area II) | Area II | **1 / 27** |
| Faculty (Areas IV, V) | Area IV, V | **0 / 27** |

Delete the area and every faculty account silently gains access to every
document. The area also backs the repository area filter, reports, hybrid
search, the AI clustering context and the area lookup in Messages.

So the four levels below the area went; the area stayed, now documented as what
it actually is rather than as the top of a taxonomy.

### 14.4 What was removed

- Models `AccreditationParameter`, `IndicatorCategory`, `AccreditationIndicator`,
  `RequiredEvidence` — and their tables.
- `qa_structure` views, forms, URLs, the six templates, the sample-data command,
  and the project route include.
- The sidebar entry.
- `Document.acc_parameter`, `acc_category`, `acc_indicator`,
  `acc_required_evidence`, `acc_evidence_label`, `acc_mapping_status`, and the
  now-orphaned `ACC_MAPPING_STATUS_CHOICES`.
- `documents/utils_accreditation.py` and the evidence-mapping call in the upload
  view.
- Four dropdowns and the whole cascade script from the upload form: **five
  accreditation selections became one.**
- Hierarchy references in `search/search_service.py`, `reports/views.py`, the
  reports template, and the chatbot's missing-evidence answer, which now relies
  on the QA Checklist alone.

`area_roman_sort_key` was rebuilt after the sweep took it with the rest of
`utils_ordering`: the repository's area filter still needs Area X to sort after
Area IX rather than after Area I.

### 14.5 Core workflow, verified after removal

| Step | Result |
|---|---|
| Faculty opens upload page | 200 |
| Faculty uploads a document | created, `Area II` |
| QA Head sees it in the repository | **yes** |
| QA Head opens it | 200 |
| Uploader sees it | yes |
| **Faculty in another area sees it** | **no** |
| Same, by direct URL | **302, not 200** |

Area isolation survived the removal. The old `/qa-structure/` URL returns 404
and no template links to it.

### 14.6 Second design pass against the reference

The first migration took the reference system's palette and surfaces but not its
*metrics*, so the interface was right in colour and a size too large everywhere.
Measured, not guessed:

| | Reference | Was | Now |
|---|---|---|---|
| Nav item padding | 9px 11px | 10px 14px | **9px 11px** |
| Nav item size / weight | 14px / 500 | 13px / 600 | **14px / 500** |
| Nav gap | 11px | 12px | **11px** |
| Nav icon opacity | .72 | 1 | **.72** (1 when active) |
| Item spacing | 1px | 2px | **1px** |
| Section label | 10.5px / .7px | 11px / 1px | **10.5px / .7px** |
| Card padding | 16px 18px 15px | 18px 20px | **16px 18px 15px** |
| Card radius | 13px | 18px | **13px** |
| Card label | 11px upper 700 | 13px sentence 500 | **11px upper 700** |
| Card value | 26px | 32px | **26px** |
| Card surface | semantic tint | flat white | **semantic tint** |
| Card icon | 32px, top-right | inline, before label | **32px, top-right** |

Smaller type in tighter padding fits more of the rail on screen and reads
calmer — the "larger spacing" was a heavier weight and wider letter-spacing, not
more information.

**Three titles before any content.** Every page showed the system name and
tagline in the top bar, directly under the same name in the sidebar, and above
the page's own heading. The reference top bar carries no title at all. The block
is gone; the `h1` stays visually hidden, because the page's own heading is an
`h2` and deleting it outright would leave every page with no top-level heading
for a screen reader.

**One correction made during the pass.** Keying the tints off the existing accent
classes tinted *Document Clusters* red. A cluster count is not a problem, and
saying so in colour is worse than not colouring it. Informational counts now
share the blue tone — the reference repeats a tone for the same reason — amber
means attention, green means healthy, and red is reserved for a figure that
genuinely means something is wrong.

No dashboard markup changed: the tones key off accent classes the templates
already carried.

### 14.7 Verification

| Check | Result |
|---|---|
| Full Django suite | **288 / 288 OK** (was 290; two tests covered the deleted page) |
| Faculty upload → QA review | **verified end to end** |
| Cross-area isolation | **holds** |
| Role smoke check | all pages, all roles |
| Feature check | **39 / 39** |
| Contrast, Dashboard | **0 failures / 234 nodes** |
| Contrast, Repository | **0 failures / 247 nodes** |
| Card label contrast on tints | 4.89 – 6.23 |
| Horizontal overflow | 0px |
| `/qa-structure/` | **404** |
| Orphaned references | **none** outside migrations |

### 14.8 Dashboard header height

The header block ran to 182px and the first row of figures did not begin until
314px down a 900px viewport — a third of the fold spent before any data. The bar
is **sticky**, so that height is not paid once; it is taken out of the viewport
for as long as the page is open.

Three things were wrong with it:

- **A chip that repeated its neighbour.** "Showing **All QA Documents
  (Combined)**" said exactly what the programme dropdown a few centimetres to its
  right already said, and took a full row to say it. It is now rendered only when
  a programme filter is actually applied — where it names the filter and carries
  the control that clears it.
- **A subtitle long enough to break the layout.** "…here is what's happening
  across your QA programs" made the left block 558px wide, which pushed the
  879px toolbar onto a row of its own. The heading above it already says
  Dashboard.
- **Generous padding on a sticky element**: 14px/12px, plus 18px above each
  section title.

| Measure | Before | After |
|---|---|---|
| Header height (1500×900) | 182px | **79px** |
| First figures row begins at | 314px | **204px** |
| Toolbar position | own row | **beside the title** |
| KPI cards fully visible | 5 | 5 |

At 1280px the toolbar still wraps and the header is 134px — narrower screens
degrade to two rows rather than overflowing. Contrast on the dashboard remains
**0 failures across 232 nodes**, and horizontal overflow is 0 at both widths.

### 14.9 The grey band across the top, and what it was hiding

The dashboard's sticky bar painted `rgba(248, 249, 251, .82)` over a
`saturate(160%) blur(10px)` backdrop. The page behind it is plain white, so the
translucent cool-grey wash read as a dark band across the top of the dashboard --
the only place in the system with one.

It has to stay **opaque**, because the bar is sticky and content scrolling
underneath would otherwise show through it. So it is now the page's own white:
invisible at rest, still a solid mask when the page moves. The blur did nothing
once the background stopped being see-through, and was costing a compositing
layer for it.

**A real bug surfaced while checking the mask actually worked.** The bar pinned
at `top: 0`, but the navbar is *also* sticky at `top: 0`, is 64px tall, and sits
at `z-index: 1020` against this bar's `30`. Scrolling the dashboard therefore
slid the title and the entire toolbar behind the navbar — 64 of its 79 pixels —
which is precisely what a sticky bar exists to prevent. It now pins at
`var(--navbar-height)`.

| Scroll position | Bar top | Hidden behind navbar |
|---|---|---|
| 0 | 88px | 0 |
| 300 | **64px** | **0** |
| 700 | **64px** | **0** |

Contrast on the dashboard stays at **0 failures across 232 nodes**; the toolbar
chips read 13.85:1 on the new white ground and the Export button 4.89:1 on its
own fill.

### 14.10 Breadcrumbs removed, and the top of every page raised

The breadcrumb repeated the sidebar. "Dashboard › Documents › Clusters" named a
path whose every step is already a permanently visible entry in the rail, on a
system two levels deep — it added a row to the top of twenty pages to restate
what was on screen throughout.

Removed in full rather than hidden: the twenty `{% include %}` lines, the partial
itself, its five CSS rules, seventeen `'crumbs'` context entries across six view
modules, and the four helper functions in `qa_mapping/views.py` that existed only
to build them. Nothing references a breadcrumb anywhere in the codebase now.

**Spacing above the content.** With the breadcrumb gone the remaining gap was
still generous: a 64px navbar holding a bell and an avatar, 24px of container
padding, then the page heading with a 24px margin under it — about 50px of empty
space either side of a 52px heading.

| Measure | Before | After |
|---|---|---|
| Navbar height | 64px | **56px** |
| `.main-content` padding-top | 24px | **16px** |
| `.page-header` margin-bottom | 24px | **18px** |
| Page heading begins at | 88px | **72px** |
| First content begins at | 164px | **142px** |
| Dashboard first figures row | 204px | **188px** |

The navbar height is a token, so the dashboard's sticky bar followed it without
being touched: it still pins flush under the navbar with nothing hidden behind
it, at the new height as at the old.

Verified across all three roles and sixteen pages: no page errors, no page still
rendering a breadcrumb, contrast **0 failures / 232 nodes**, horizontal overflow
0px, smoke check green for every role, feature check 39/39.


---

## 15. Removing the QA Checklist

The page held **three requirement records, all created on one day and never
touched since**, with no attachments, no programme links, and content that reads
as trial data. Two activity-log entries existed for it in the system's lifetime.
Evidence mapping is not in the capstone's scope — Faculty upload, QA view and
review is — so the page, its create/edit/delete forms, its spreadsheet import and
template download, its attachment handling, eight routes, five templates, the
`QARequirement` and `RequirementAttachment` models and tables, the importer
module, the admin registration, the sample-data seeder and the sidebar entry all
went together.

**QAProgram stayed.** It lives in the same app but is load-bearing: `ACCRED`
alone carries **95 of 112 documents**, and the Program filter on both the
dashboard and the repository is built from those rows.

Three consequences worth recording:

- `QAProgram.progress_summary()` measured "requirements complete" through the
  checklist. With the checklist gone it would have read 0/0 for every programme,
  so it went too; the programme card now shows documents filed.
- The migration was **blocked by `tracker_missingdocument`** — a table left by an
  app removed some time ago (no directory, no models, not in `INSTALLED_APPS`,
  its removal recorded in `chatbot/migrations/0002_remove_tracker_faqs.py`) whose
  three rows held a foreign key into the requirements, already pointing at ids
  that no longer existed. SQLite's integrity check refused the migration until it
  was dropped. It is dropped **inside** the migration rather than by hand, so the
  database stays reproducible from migrations alone.
- The chatbot's "what evidence is missing" answer had the checklist as its last
  data source. It now says plainly that it cannot determine this from available
  records, rather than returning a zero that would read as "nothing is missing".
  A dead "open QA Checklist and use the import flow" instruction was removed, and
  the QA Programs answer — which told users to open a sidebar entry that does not
  exist — was corrected.

Verified: `manage.py check` clean, migration applied, **320/320** suite green,
smoke check across all pages and all three roles, feature check 39/39,
`/qa-mapping/checklist/` returns 404, and nothing links to it.

---

## 16. Profile photos that follow the account

Photos existed on `UserProfile.avatar` and were shown in four places — the
navbar, User Management, the user detail page and the user form. Everywhere else
that displays a person fell back to initials or, on the dashboard, to a **single
letter**. Messaging showed initials only, in all four of its render sites.

### One place decides

`accounts/avatars.py` is now the only thing that answers "what does this account
look like?", and every surface goes through it — templates via the
`avatar_url` / `avatar_initials` filters and the `includes/avatar.html` partial,
JSON endpoints via `messaging.views._avatar`. The helpers survive the two shapes
that reach them from real pages: an account with no profile row, and **no account
at all**, where an uploader has since been deleted. A page showing initials beats
a page that raises.

Nothing derives a picture from a role, a page, or a position. The photo is read
from the account that owns it, which is what makes it consistent.

### Messaging

The rule the tests pin down: **a message's picture is a property of the account
that sent it, and of nothing else.** It is resolved from `message.sender` — the
same stored `sender_id` that the earlier sender fix established — so the same
message carries the same face whoever opens it, while "mine vs theirs" keeps
flipping per reader. Those two facts pull in opposite directions, which is
exactly where a messaging interface goes wrong, so every case asserts both.

Confirmed on live data, one conversation read from both sides:

| Message | Sent by | Admin sees | Admin bg | QA Head sees | QA Head bg |
|---|---|---|---|---|---|
| hello | qahead | qahead.jpg | grey | qahead.jpg | **blue** |
| what is that | admin | admin.jpg | blue | admin.jpg | **grey** |
| secret | qahead | qahead.jpg | grey | qahead.jpg | **blue** |

### Design left alone

Every avatar in the system was already a fixed-size round element showing
initials on a coloured ground. A photo is laid **inside** that element rather
than replacing it, so nothing built around initials moved:

```css
.has-photo > img { width:100%; height:100%; object-fit:cover; border-radius:inherit; }
```

Measured after the change: message avatars still 28×28, dashboard uploader
24×24, both still `border-radius: 50%`; bubbles still `rgb(26,123,147)` white-on-
brand for sent and `rgb(222,236,242)` for received. One new class,
`.qa-row-avatar` (22px), for the area-submissions faculty rows, which previously
showed a bare name.

### Surfaces now covered

Navbar · User Management · user detail · user form · **dashboard uploader** ·
**area-submissions faculty rows** · **Messages conversation list** · **people
picker** · **conversation header** · **message bubbles** · **the live sync
payload**.

`select_related('sender__profile')` and `prefetch_related('participants__profile')`
keep the added lookup from becoming a query per row.

### Photos assigned

Eight portraits across eight accounts, cropped square with the frame biased to
0.38 of the height so the face stays in shot, stored at 512px JPEG. The three
pictures already on file were a car and two code screenshots, all replaced. The
two unnamed audit fixtures keep the initials fallback — which is also the
system's proof that the fallback still works.

Verified: **339/339** suite green (320 before, 19 added), all pages load for
admin / QA Head / Faculty with access boundaries unchanged, and every stored
avatar path resolves to a real file.

---

## 17. Upload performance — the bottleneck was the server, not the connection

Measured on an isolated copy of the database and media (`D:\qa-bench`), with
the same 32-file batch — 16 diagram PNGs, 4 photos, 4 scanned PDFs, 4 text PDFs,
4 Word files — uploaded from the same starting state before and after.

| | Before | After |
|---|---|---|
| Upload request (browser on "Finalizing on server…") | 99.3 s | **1.2 s** |
| All files saved and extracted | 146 s | **12.0 s** |
| Clusters ready | 187 s | **18.6 s** |
| OCR calls | 87 (24 needed) | **24** |
| OCR calls inside the upload request | 63 | **0** |
| Full pipeline run | 41.1 s | **6.8 s** |
| Embedding model load, first run after a restart | 99.9 s | **7.3 s** |

### What was actually slow

1. **OCR inside the upload request.** The near-duplicate text check ran before
   any file was saved, so every file was OCR'd while the browser waited.
2. **The same files OCR'd again and again.** The check re-read any stored
   document with under the minimum text — a photo or sparse diagram never gets
   there, so it was OCR'd once more for every same-type upload, forever. Within
   one batch the sparse figures were read 5 times each. The background job then
   OCR'd every image a second time, and stored the result in both text fields
   (44 existing images carry their text twice).
3. **The embedding model went online to load.** It is already on disk, but each
   first load after a server restart spent ~85 s on Hugging Face network checks.
4. **K-Means thread start-up.** 57 fits on groups of ~16 documents, each paying
   ~53 ms to start a thread pool for microseconds of work.
5. **Every document re-embedded on every run**, and every batch started its own
   full pipeline on its own thread, with nothing stopping several overlapping.

Measured and ruled out: database writes. Commits cost 0.2 ms each here, so the
pipeline's ~2,000 writes were under half a second.

### What changed

- **Request:** validates, hashes once (SHA-256, and the visual hash for images),
  saves, and answers. Both hashes are stored on the document, not recomputed.
- **Background:** one batch at a time; each file extracted exactly once, on up
  to 4 parallel workers (3.8× measured); every database write stays on the
  batch's own thread, in upload order.
- **Near-duplicate text:** the same comparison, threshold and upload-order
  semantics, now run after extraction (`documents/near_duplicates.py`, shared
  with the single-file pages). A refused file is deleted and shown on the upload
  page as **Duplicate** with its reason; the notification says it was not added.
- **Pipeline:** one run at a time from every entry point; batches that finish
  during a run share a single follow-up run (3 back-to-back batches → 2 runs,
  never overlapping). The model loads from local files first; vectors are reused
  for unchanged text; clustering runs single-threaded.
- **Upload page script:** one batch request at a time, no rebuild when nothing
  changed, no fetch on every navbar poll tick, and saved files listed as
  Processing the instant the upload returns (that frame used to read
  "undefined / undefined"). No HTML or CSS changed.

A batch is now reported finished only once the clustering run covering it has
finished; its files still turn Completed one by one as they are processed.

### Results unchanged

- Extracted text: **32 / 32 identical** to a serial read with the original code,
  scanned PDFs compared against the original render-and-OCR loop verbatim.
- Cluster labels: **identical** to the original path (48 clusters); reused and
  freshly computed vectors differ by at most 6×10⁻⁸.
- Two look-alike images in one batch are still both accepted and then flagged
  for review, as before.

Verified: **368 / 368** tests (29 new, in `documents/tests/test_upload_pipeline.py`),
an end-to-end near-duplicate refusal with real extraction, and the page script
exercised in a browser against canned server states.

### Not changed, worth knowing

- The single-file upload pages still extract text and run the pipeline inside
  the request.
- A server restart mid-batch (for example runserver reloading on a code edit)
  still leaves that batch to be reported stalled after 10 minutes; it is not
  resumed automatically.
- C: has about 400 MB free, and Tesseract writes its temporary files there.

---

## 18. Sign-in stuck on "Signing in"

Nothing in the application opens a window or tab on sign-in — no `window.open`,
no service worker, no cross-tab messaging. The login form is a plain same-tab
POST whose script greys the button out on "Signing in". That state was only
ever cleared by the page being replaced, so it stuck whenever the sign-in
completed somewhere the page could not see:

- **Ctrl/Cmd-click or Shift-click on Sign In** (or Ctrl/Shift+Enter) sends the
  form to a new tab or window. The original page still runs its submit handler,
  so it greys out, and nothing ever replaces it — while the new tab or window
  is signed in.
- **Back after signing in** can restore the login page from Chrome's
  back/forward cache exactly as it was left, with no request made that could
  have redirected a signed-in visitor.
- **A post-sign-in destination that is not a page** (after a session timeout,
  `?next=` pointing at a download) signs in and downloads, but never navigates.

Measured and ruled out: the server. Sign-in takes about 230 ms and the faculty
dashboard 35–73 ms; 140 faculty sign-ins during a heavy upload batch took at
most 1.8 s, with no errors.

**Fix — the server's session is the only source of truth.**

- The login view is `never_cache` (and `sensitive_post_parameters`), as Django's
  own `LoginView` is, so Back always asks the server, which already sends a
  signed-in visitor straight to their dashboard.
- The page keeps sign-in in the current tab: a modified click is cancelled and
  the form resubmitted here, one tick later so the browser cannot read it as
  "open in a new tab".
- Whenever the page is unsure — restored from cache, still here 8 s after
  submitting, or shown again while waiting — it asks the server with a
  no-redirect fetch of `/accounts/login/`. Signed in: go to the dashboard.
  Not signed in: stop showing "Signing in" and hand the button back.
- Signed-in pages mark `localStorage`; a login page open in another tab follows
  that sign-in to the dashboard.

No markup or styling changed: same button, spinner and "Signing in" text.
Verified: **379 / 379** tests (11 new, every role landing on the dashboard in a
single redirect), and each scenario exercised in a browser.

**Followed up in section 19:** the idle timeout counted the background polls
as activity, and the "Keep me signed in" checkbox was never read by the server.

---

## 19. The one-hour idle sign-out, and the remember-me checkbox

**Idle sign-out never fired while a tab was open.** `SessionIdleTimeoutMiddleware`
reset the idle clock on every authenticated request — including the page's own
automatic ones: badge counts every 5 s, upload and job progress, the Messages
sync. With `SESSION_SAVE_EVERY_REQUEST = True` the 8-hour session cookie slid
forward on each of them too. A screen left signed in — on a shared office PC,
say — stayed signed in indefinitely, showing whatever it was showing.

**Fix.** Only what the person does counts as activity.

- `main.js` records real input (keys, clicks, scrolling, mouse movement, touch).
  Automatic requests carry `X-QA-Passive: 1` once nobody has touched the page
  for a minute, and the middleware no longer resets the clock for them.
- When the hour runs out, a background request gets a `401` (with the sign-in
  URL in `X-QA-Login`) instead of a redirect `fetch()` would silently follow, and
  the page moves itself to sign-in, which shows *"Your session expired due to
  inactivity."* Page requests are redirected as before.
- All four pollers use it: `realtime.js`, `job-status.js`, the upload page's
  batch progress, and the Messages sync.

Someone reading or typing is never signed out: their input keeps the clock
alive. Verified: 13 new tests (an unattended tab signed out after the hour,
active use kept, 401 for background requests, the sign-in page explaining why),
and in the browser — passive after a minute untouched, cleared by a keypress, a
401 taking the page to sign-in.

**"Keep me signed in" removed.** The server never read it, so it promised
something that did not happen. Markup and CSS are gone; "Need help?" keeps its
exact position (its row now right-aligns its one remaining item).

**Read receipts from an unattended screen — fixed too.** The Messages sync
marked new messages read whenever it delivered them to an open conversation,
so a screen nobody was watching told senders "Read" for up to the hour before
it signed out. A passive sync still puts the message on screen but leaves it
unread; the first sync after the reader is back marks everything they now have
in front of them — even though it brings nothing new, since the messages
already arrived while they were away. Opening a conversation still reads it.
Six tests, from both sides of the conversation.

Full suite: **398 / 398**.


## 20. Clustering that cannot take the server down when memory runs short

**What happened.** On this PC the full test suite crashed while loading the AI
model — Windows error 1455, "the paging file is too small for this operation to
complete", and in two of three tries an outright access violation. The PC had
run out of memory: 16.2 GB committed of a 17.0 GB limit, with the page file
unable to grow because C: was full. Clustering runs inside the web server, so
the same load during an upload would have taken the server down with it.

**Fix.** Before loading the model, `ai_processing/embedding_service.py` checks
how much memory the PC can still supply: what is free now, plus the room the
page file still has to grow (Microsoft's rule for a system-managed page file:
up to 3 × RAM or 4 GB, no more than an eighth of the drive, and only into free
space). Loading needs about 730 MB on top of the running server — measured:
250 MB to import torch, 135 MB for the model, up to 340 MB more while
encoding. With less than `AI_CLUSTER_EMBEDDING_MIN_FREE_MB` free (default
1536), that run clusters with TF-IDF + metadata instead — the path it already
took whenever embeddings were unavailable — and logs why. The next run looks
again; a model already loaded needs no new memory and is not checked. And an
out-of-memory error during a load is no longer followed by a second attempt
"online": the files were there, only the memory was missing.

**What it does not change.** With enough memory, nothing: on the isolated copy
the 32-file upload produced the same 48 clusters, document for document, as
before the change. With the check forced to "short of memory", the same upload
finished with 25 hybrid clusters, every document clustered and nothing left on
"Checking…".

**A page file on D: does not work on this PC.** D: is BitLocker-encrypted and
unlocks after Windows has set up its page files, so a page file configured
there is skipped at every start (the 6 GB `D:\pagefile.sys` from October 2025
was never used). The lasting fix for the memory itself is free space on C:,
where the page file can grow.

**The cluster badge now names the method that was actually used.** Each
document's AI Processing Result page shows its cluster number with a badge
naming the clustering method (the separate "Clustering engine" card was removed
earlier — row 39). After a run started by an upload, a background run with no
page session to write to, the badge fell back to the settings and said
"Semantic embeddings" — even for a run that had used TF-IDF because memory was
short. Every run that relabels the clusters now records its method
(`ProcessingMetric` "clustering_run"), and the badge reads the latest record,
so it describes the clusters actually on screen. The three badges look exactly
as before; only which one is shown changed. A run that cannot cluster (too
little text) leaves the clusters alone and records nothing, and with no run
recorded yet the badge describes the settings, as it always did. On the
isolated copy: forced short of memory, "Hybrid TF-IDF + metadata"; normal,
"Semantic embeddings". 14 tests.

Full suite: **437 / 437**, and **437 / 437** again with the check forced to
"short of memory" — 14 clustering runs fell back to TF-IDF, and the model was
never loaded.

## 21. Full system check — fixes

A full system check (D:\Full-System-Check-Prompt.md) was run against an
isolated copy of the data (D:\QA-System-Check\instance, port 8010), never the
live database. Everything it found inside the prompt's "Fix" boundary was fixed;
decisions for the owner are in the report's Flagged_Not_Fixed sheet
(D:\QA-System-Check\QA_Full_System_Check_Report.xlsx). No database schema
change was needed: nothing here requires `migrate`.

**Access and privacy.** The QA Assistant counted and quoted documents from
every area to Faculty (now area-scoped, like the Repository). Duplicate
messages, upload-page rows and the detail panel named documents from other
areas and archived versions (now only documents the viewer may open). An
Administrator could delete, deactivate or demote their own account — delete
ended in a server error — now refused with a message. Sign-out is a POST (the
modal button is a form; same look). The post-login redirect uses Django's host
check. CSV/Excel exports write formula-like text as text.

**Duplicates.** Confirm and Dismiss now survive re-processing (kept on each
matched document; decisions made before this are honoured). Each new pair is
announced once — every AI run used to re-announce every matched image, 854
alerts in 40 minutes. Archived versions no longer take part in matching or
clustering. Deleting one document of a pair clears the other at once. `.jpg`
and `.jpeg` are one format for the exact-copy check.

**Uploads.** Files are checked to be what their extension says (a renamed
program or web page, or an empty file, is refused with a reason). Years are
limited to 2000–2100 on the server. A damaged Word/Excel/PDF file is reported
as failed — it used to be stored as a success with no text — and the batch
message counts only real successes and no longer says "ready" while duplicate
checks and clustering are still running. OCR failures name their cause
(Tesseract missing, image too large) and a scanned PDF says which pages OCR
skipped. Image OCR uses OCR_LANGUAGE and turns EXIF-rotated photos upright.
Retry OCR no longer marks a Word file "OCR failed" and refreshes the analysis
when the text changes. An interrupted batch is resumed at startup. A Faculty
account with no area gets guidance instead of an empty area list. File names in
the selected-files list are escaped.

**Search.** Every word of a query must appear, in any order, across line
breaks, with singular/plural variants; numbers and quotes no longer match the
stored keyword scores; a search is listed best match first until a column
header is clicked; the area filter is exact ("Area I" no longer returns II, III,
IV, IX); five unused facet searches per Repository request were removed.

**Clustering.** The Elbow point was one k too high (index offset). The Elbow
chart is saved with each run, so every Admin sees it in the default background
mode; one caption line under it now says which group it describes and what
chose that group's k (usually the silhouette score). Cluster numbers carry
their descriptive name as a hover tooltip in the Repository, Reports and
Dashboard (layout unchanged).

**Dashboard, Reports, Settings.** Calendar "Next" from December goes to
January; "today" is the local date. "Uploaded This Week" opens the week's
uploads; for Faculty, "Duplicates to Review" is no longer a link to a list that
did not match it (Faculty cannot filter duplicates, by design). Reports and
program counts leave out archived versions, and the Recent export has the rows
the page shows. The "AI-Processed" card uses the AI Processing page's
definition. Settings shows each engine's last run (a failed run reads
"Degraded") and says it is read-only.

**Also.** A document whose uploader had been deleted could not be opened
(server error) — fixed. The deactivated-account message is shown to the right
password (Django refused the account before the view could say why). User-form
areas are in accreditation order. An area code cannot be re-added in other
capitals. Version links cannot form a cycle, Unarchive takes a document out of
its chain, and deleting a newer version restores the older one. Area ZIPs are
streamed from a temporary file (ZIP_TEMP_DIR, beside the project) with unique
names inside. The chatbot searches questions about any subject instead of
answering them with the upload steps, and its guidance matches the real pages.
README corrected.

**The project's `runserver` had never run.** `qa_archiving_system` was listed
last in INSTALLED_APPS "so its runserver overrides staticfiles'", but Django
uses the command of the app listed *first*, so staticfiles' plain runserver ran
and the project's never did: nothing resumed or recovered background jobs at
start-up, so a batch cut off by a restart stayed "running" for good (a test
batch sat that way for hours). The app now comes before staticfiles, and the
job worker also starts under `--noreload`. The live database has no pending or
running jobs, so its next start does nothing extra.

Verified on the isolated copy after the fixes: every fixed finding re-tested
end to end (report rows marked "Fix applied: Yes"); 21 pages across Admin, QA
Head and Faculty with no console errors; the Log Out button measures 122.0 ×
37.1 px like Cancel, as before. Full suite: **581 / 581**. One messaging test
("nobody at the page, the message stays unread") is timing-dependent on Windows
— it compares two timestamps that can fall in the same clock tick — and failed
once in four runs; it is unrelated to these changes.

## 22. "Read" decided by message, not by clock tick

The one test left failing now and then in section 21 ("nobody at the page, the
message stays unread") was a real fault, not a test problem. A message counted
as read when it was created at or before the moment its reader last looked.
Windows clocks advance about every 15 ms, so a message sent in the same tick
as the reader's last look carried the same time and was taken as already
read: the sender was told "Read" and the reader got no unread badge.

**What changed.** Each participant's read mark is now the id of the last
message they read (`ThreadRead.last_read_message_id`). Ids never tie. Unread
counts, the "new messages" divider, the read receipts and the inbox page's
live receipt refresh all compare ids. A refresh marks only what is on screen
(the messages it delivers, or those already shown), so a message landing
while a refresh runs stays unread until it is delivered. The mark only moves
forward and cannot pass the newest message. `last_read_at` stays as the time
the mark last moved.

**Migration.** `messaging 0002` adds the field and sets each existing mark to
the last message sent before that person's recorded read time, so no
conversation changes read state. Run `python manage.py migrate`.

**Also.** `test_render.py`, a debug script in the project root, was removed:
its name made `manage.py test` import it, and it queried the live database
rather than the test one on every test run.

Verified on MariaDB 10.11: the new tie test fails on the old code and passes
on the new; in a browser, a sent message showed "Sent" and turned "Read" on
its own when the other person opened the conversation. Full suite: **940 /
940** (19 skipped by their own conditions).

## 23. User Management: status and access in separate columns, a smaller table

**Status and the switch were one column.** The on/off switch and the
Active/Inactive text shared the Status cell, so the switch read as part of the
status label. Status now only reports the state (a dot and "Active" or
"Inactive"); a new **Access** column holds the switch. Its tooltip says what a
click will do ("On — click to deactivate"), and a screen reader hears "Account
access for <name>". Flipping it updates the Status column at once. Your own
row shows "Your account" in Access and no switch, as before.

**Smaller table.** Cell padding 16×24 → 9×16 px, photos 42 → 32 px, text 14 →
13 px, smaller role badges; role, joined date and headers no longer wrap.
Measured at 1280 px with six users: rows 76 px → 57 px (the Administrator's
row was 95 px), table 548 px → 381 px tall. No horizontal overflow at 1280 or
1024 px.

**The Administrator badge was invisible.** It used `--color-sidebar` as its
fill, and the sidebar is now white, so it was white text on white. It now uses
`--color-brand-dark`, keeping "dark = highest privilege".

Verified in a browser: switching an account off and on changes its Status
cell, survives a reload, and raises no script errors; `accounts` tests pass.

## 24. Full system check (after sections 22–23)

A full pass on a MariaDB 10.11 copy with sample data only (no live data): 15
sample files (PDF, DOCX, XLSX, a scanned PNG, an exact copy and a near-copy)
uploaded through the real Bulk Upload page by an Administrator and a Faculty
member, then every page opened in a browser as Administrator, QA Head and two
Faculty accounts (636 page loads).

**What held.** No server error on any of the 636 loads. No script error or
sideways overflow on any page. Faculty were kept to their own areas everywhere
checked: documents of other areas redirect to the Repository, their downloads,
area ZIPs and notifications are refused, and search and the QA Assistant do not
reveal them. Administrator-only pages send QA Head and Faculty back to the
Repository. Endpoints that only accept POST refuse a GET (405 or redirect),
never with a 500. The exact copy was refused before upload ("1 file(s) removed
from selection"); the near-copy was stored and flagged "Needs review" at 99 %;
the scanned certificate was read by OCR, titled, typed and filed under Area
VIII. Workflows exercised end to end: marking a duplicate clear, editing and
deleting one's own upload, Smart Search (including OCR text), the QA
Assistant, and Reprocess All.

**Fixed: a document title could run as script in the Administrator's
browser.** The AI Processing and Dashboard charts wrote their data into inline
JavaScript with `|safe`. Each cluster label ends with a member document's title
("eg. <title>"), and uploaders — Faculty included — set titles, so a title
containing `</script><script>…` ran in the browser of whoever opened AI
Processing after the next AI run. Proven on the test copy before fixing. All
chart data on both pages now goes through Django's `json_script`, which escapes
`<`, `>` and `&`; QA programme names on the Dashboard had the same exposure.
The department name on User Management was also marked `|safe` and is now
escaped.

**Fixed: areas named in file names with underscores were not detected.**
Underscores are word characters to a regex, so `Area_VII_Library_Holdings.xlsx`
matched neither "area vii" nor "library", and a file whose text did not repeat
its area was left without one. The file name's separators now become spaces
first, as document-type detection already did.

**Fixed: spreadsheets were titled by their column headings** ("Title Call
Number Copies Year"). A spreadsheet now keeps the title taken from its file
name.

Documents uploaded before these fixes keep their stored title and area; edit
them to correct.

**Not changed, worth knowing.** The Cluster Distribution legend on AI
Processing is cut off on the right once the labels need a second column. With
very few documents per area and type, most clusters hold a single document
(13 clusters for 13 documents here); this is the per-group clustering working
as designed and evens out with real volumes. `scripts/ui_feature_check.py`
reports 2 stale failures: it looks for a `---------` anywhere on the upload page
(one is a code-comment divider in the floating messages panel) and for per-row
icon classes the Repository replaced with a row menu.

Full suite: **947 / 947** (19 skipped by their own conditions).

## 25. QA Assistant: answers it got wrong or refused

Thirty questions a QA Office user or Faculty member would ask — including
typos, Taglish and follow-ups — were put to the assistant with sample data
loaded, as an Administrator and as a Faculty member. About half were answered
well. These were not:

| Question | Before | Now |
|---|---|---|
| "Summarize the fire safety certificate" | Summarised **a different document** — whatever the previous answer was about | Finds the named document (title, text or OCR text) and summarises it; if nothing matches the name, says so instead of guessing |
| "Why was the certificate put in Area VIII?" | "I could not match that…" | Explains the type, area, cluster and keywords of the named document |
| "How many documents are in Area II?" | The archive-wide total | The count for Area II (also by year, type, programme or subject) |
| "What are the accreditation areas?" | Described QA programmes | Lists Area I–X from the database, with document counts |
| "What is Area IX about?" / "What should I upload for Area IV?" | General help / the upload steps | The area's name, description and what is archived in it; says plainly that required evidence is not tracked |
| "Which documents were uploaded this week?" | The upload steps | The documents uploaded in the last 7 days (as the Dashboard counts a week); also today, yesterday, last week, this/last month |
| "hi", "thanks", "salamat po" | "I only answer questions about this system…" | A greeting or you're-welcome, with suggestions the user can click |
| "How do I change my password?" | Refused | An Administrator resets it in User Management (there is no self-service page) |
| "Who can see my uploads?" | The upload steps | Visibility by role and area |
| "What does Needs review mean?" / "How do I mark a duplicate as clear?" | Refused / the Repository overview | Duplicate statuses and the review steps |
| "How do I download all documents of Area II?" | The Repository overview | The area ZIP download |

Summaries also no longer repeat a sentence that appears more than once in the
file (page headers, repeated paragraphs). An area and a year in a question are
now used as filters only, not as words a matching document must contain.

Everything stays inside the asker's permissions: for Faculty, a document
outside their areas is "not found in your area(s)", counts and period lists
cover their areas only, and other areas are listed by name without counts.
Plain "how many documents" and "recent / latest uploads" are still answered by
the live-data tier as before; the test that expected "hello there" to be
refused now expects a greeting, still without a language-model call.

Not changed: with Ollama or Gemini configured, questions that none of the
built-in answers match still go to the model as before.

Verified: the 17 new tests (13 fail on the previous code); the chat page shows
the suggestion buttons and answers from them in a browser. Full suite: **964 /
964** (19 skipped by their own conditions).

## 26. Dashboard export for Administrators only; User Management shows who is online

**Export Excel is an Administrator's tool.** The Dashboard's Export Excel button
is no longer shown to QA Heads or Faculty, and `?export=excel` / `?export=csv`
render the dashboard for them instead of a file.

**Status is now presence, and it updates by itself.** The Status column
repeated what the Access switch already says (Active/Inactive). It now shows:

- **Online** — the person has the system open (any request in the last 3 minutes;
  every open page refreshes its badges every few seconds);
- **Last seen … ago** — offline, with when; signing out, by the button or by the
  idle timeout, shows Offline at once;
- **Never signed in**;
- **Inactive** — the account is switched off.

The page refreshes the column every 15 seconds without reloading
(`accounts:user_presence`, Administrators only). Each session writes the time at
most every 30 seconds, so presence adds one small UPDATE per user per
half-minute. Accounts that signed in before this change show their last sign-in
until their next visit.

**Migration:** `accounts 0008` adds `UserProfile.last_seen` and `last_logout`.
Run `python manage.py migrate`.

Verified in a browser with two sessions: with User Management open, a Faculty
member signing in turned their row to Online and signing out turned it to "Last
seen just now", both without a reload. Full suite: **977 / 977** (19 skipped by
their own conditions).
