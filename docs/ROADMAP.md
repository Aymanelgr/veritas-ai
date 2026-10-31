# Veritas AI roadmap

Status: work in progress. This list describes continuing work, not release promises.

## Current foundation

- Local document reading, OCR, structured extraction, matching, verification, and RAG.
- React dashboard, reviewer decisions, n8n notification templates.
- Authentication, viewer/reviewer/admin roles, organization scoping, and audit events.
- Alembic migrations and background processing through Redis/RQ.
- Recent work on document identity, ambiguous matches, corrected links, locale parsing,
  processing reliability, and multilingual evaluation is included in the source.

## Next priorities

1. Verify the latest changes against the full backend suite and the example scenarios.
2. Expand labelled English, French, and Arabic evaluation sets, including OCR failures,
   ambiguous references, document revisions, and cumulative partial invoicing.
3. Record reproducible evaluation results with dataset sizes and model versions.
4. Improve review and correction flows based on actual usage.
5. Lock and document a tested Python dependency set for repeatable installation.
6. Validate a deployment target with HTTPS, backups, and operational monitoring before
   offering a public hosted service.

## Release readiness

- Backend tests and frontend build pass in CI.
- Installation works from a clean checkout.
- Database migrations preserve existing data.
- Documentation matches the implemented behavior.
- No credentials, private uploads, or local runtime data are committed.
