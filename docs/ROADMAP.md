# Veritas AI roadmap

Status: work in progress. This list describes continuing work, not release promises.

## Current foundation

- Local document reading, OCR, structured extraction, matching, verification, and RAG.
- React dashboard, reviewer decisions, n8n notification templates.
- Authentication, viewer/reviewer/admin roles, organization scoping, and audit events.
- Alembic migrations and background processing through Redis/RQ.
- Document identity (duplicates vs declared revisions), validated and ambiguous matches, audited link
  corrections, partial and cumulative invoicing, locale-aware numbers/dates/currencies, reviewer
  corrections, idempotent reprocessing, and stage timings.
- Item alignment uses product codes, then refuses pairs whose stated sizes/models differ (M12 vs M10,
  HP-200 vs HP-300) before using embeddings.
- Review interface: problems first, guided upload with overrides, stage progress, match confirmation and
  manual linking, field and line corrections with reasons, explanations with missing-evidence guidance,
  supplier message drafts (never sent), what-if simulation, transaction timeline.
- Assistant: saved private conversations, follow-ups, document scope, exact database answers for
  counts and statuses, cited document answers.
- Alerts: off / preview / send modes, once-only delivery, daily reminders, delivery status reported by
  n8n, authenticated in both directions; optional read-only email intake.

## Next priorities

1. Run the n8n workflows end to end in a local n8n (import with `scripts/setup_n8n.py`), first in
   preview mode, then with a test SMTP server.
2. Expand labelled English, French, and Arabic evaluation sets, including OCR failures,
   ambiguous references, document revisions, and cumulative partial invoicing.
3. Record reproducible evaluation results with dataset sizes and model versions.
4. Known matching limit: embeddings rate some different products as similar ("2.5 ton forklift" vs
   "2.5 ton pallet truck"); only product codes rule this out. Consider a reviewer-maintained synonym list.
5. Highlight evidence on the page image (needs OCR box coordinates stored per value).
6. Goods-receipt matching (ordered vs received vs invoiced).
7. Lock and document a tested Python dependency set for repeatable installation.
8. Validate a deployment target with HTTPS, backups, and operational monitoring before
   offering a public hosted service.

## Release readiness

- Backend tests and frontend build pass in CI.
- Installation works from a clean checkout.
- Database migrations preserve existing data.
- Documentation matches the implemented behavior.
- No credentials, private uploads, or local runtime data are committed.
