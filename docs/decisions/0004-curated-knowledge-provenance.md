# ADR 0004: Curated agricultural knowledge with row-level provenance

Status: Accepted (Phase 3a)
Date: 2026-11-08

## Context
The rule-based suitability engine (Phase 4) and the assistant (Phase 7) depend on
crop requirements (temperature, pH, season windows, land type). Wrong values here
directly produce wrong advice for farmers. Values typed from memory (human or LLM)
cannot be audited.

## Decision
1. All curated knowledge lives in `data/reference/*.csv` (tracked in git, UTF-8 with BOM).
2. Every row has `source_id` (must exist in `sources.csv`), `source_locator`
   (page/table/section), `status` (`todo` | `draft` | `verified`), `verified_by`,
   `verified_on`.
3. Downstream code must load data through `verified_only()`. Draft and todo rows
   never reach users.
4. `scripts/validate_reference.py` and `tests/test_reference_knowledge.py` enforce
   schema, units, plausible ranges, value order and provenance.
5. Species-level global sources (FAO ECOCROP) are used only for absolute limits;
   optimum ranges and calendars come from BARI/BRRI.
6. `crop_id` means crop + season system (e.g. aman_rice vs boro_rice), because the
   same species has different requirements and calendars per system.

## Consequences
- Slower to fill, but every value is traceable to a page.
- The engine will report "insufficient verified knowledge" instead of guessing
  when a needed row is not verified.
- Edition changes in source handbooks require re-verification (record edition in
  `sources.csv`).
