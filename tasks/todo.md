## Phase 1 - Talent Intelligence UX

- [x] Add normalized API response envelopes for `/api/*` and `/v1/*` JSON routes.
- [x] Add shared query parsing and validation helpers.
- [x] Add request correlation ids (`request_id`) in API responses.
- [x] Add lightweight TTL caches for summary/autocomplete/salary-insights endpoints.

## Phase 1 - Studio Surface

- [x] Add minimal studio intake endpoint (`POST /studio-contact`) reusing existing contact storage.
- [ ] Add `/studio` page route + template wiring for B2B package surface.

## Hooks for Automation & AI

- [x] Add `GET /api/share-search` to create canonical share links.
- [x] Add `GET /api/salary/compare` to compare salary baselines across two regions.
- [ ] Add optional prefilled “ask about this salary” UI hook in salary templates.

## API Reliability and Dev Experience

- [x] Consolidate duplicated jobs listing logic into one shared service path.
- [x] Add versioned endpoint wrappers: `/v1/jobs`, `/v1/salary`.
- [ ] Add live integration smoke tests in CI once pytest is available in environment.
