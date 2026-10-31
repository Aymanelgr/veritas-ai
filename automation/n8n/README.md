# Alerts, reminders and email intake

Veritas decides **what** to send and records every alert; n8n only **delivers** it and reports
back. Nothing is emailed until an administrator chooses "Send" in **Settings** *and* SMTP is
configured in n8n.

| Workflow | Trigger | What it does |
|---|---|---|
| `review_needed.json` | Veritas posts to the webhook when new open findings appear | Inbox message; email in send mode; reports delivery status |
| `review_reminder.json` | Every day at 9:00 (or "Run now") | Asks Veritas for findings waiting more than a day; inbox message per organization; email in send mode |

## Set up

1. In `.env`: a long random `AUTOMATION_TOKEN`, `N8N_WEBHOOK_URL=http://localhost:5678/webhook/veritas-review`,
   and `DASHBOARD_URL`. When the API runs in Docker, also `VERITAS_API_FROM_N8N=http://api:8000`.
2. `python scripts/setup_n8n.py` imports and activates both workflows, filling in the token and URLs
   (the templates in Git contain placeholders only). It briefly restarts the n8n container.
3. In Veritas, open **Settings** (admins): add recipients, keep **Preview**, press **Send a test alert**,
   and check **Recent alerts**.
4. To really send email: in n8n, add SMTP credentials to the node "Email (add SMTP credentials,
   then enable)" in both workflows and enable it; then choose **Send** in Veritas Settings.

## Safety

- **Both directions are authenticated** with `AUTOMATION_TOKEN`: Veritas sends it to the webhook (the
  workflow ignores requests without it), and n8n sends it to the Veritas API.
- **Preview is the default.** In preview mode n8n reports what it *would* have emailed; nothing is sent.
- **No duplicates.** Each finding is alerted once (by fingerprint); each reminder is prepared at most
  once per organization per day, so retries and manual runs do not repeat messages.
- **Honest delivery status.** "sent" is recorded only when the SMTP server accepted the email. A disabled
  or unconfigured email node is reported as "skipped", and errors as "failed" with the reason.
- **No document content leaves Veritas.** Emails carry a short summary and a link that requires sign-in;
  files are never attached.
- A failed notification never fails document processing.

## Email intake (optional)

`python scripts/mail_intake.py` imports invoices and orders attached to emails. It is off until you run it:

```bash
python scripts/mail_intake.py --eml-dir path/to/saved-emails          # dry run on .eml files
python scripts/mail_intake.py --eml-dir path/to/saved-emails --apply  # import them
python scripts/mail_intake.py --imap                                  # dry run on the mailbox
python scripts/mail_intake.py --imap --apply                          # import from the mailbox
```

Settings in `.env`: `INTAKE_ORGANIZATION_ID`, `INTAKE_UPLOADER_EMAIL` (a reviewer or admin, recorded as
the uploader), optionally `INTAKE_ALLOWED_SENDERS`, and for a mailbox `INTAKE_IMAP_HOST`,
`INTAKE_IMAP_USER`, `INTAKE_IMAP_PASSWORD` (`INTAKE_IMAP_PORT`, `INTAKE_IMAP_FOLDER`,
`INTAKE_IMAP_SINCE_DAYS` have defaults).

- The mailbox is opened **read-only** and never changed. Start with a dry run.
- Each email is imported once (by Message-ID); an attachment already received (same SHA-256) is linked
  to the existing document instead of being stored again.
- Attachments get the same content checks and limits as uploads. The email body is never acted on.
- Sender, subject, date and attachment identity are kept in the `email_intake` table and the audit history.
- Run it on a schedule with Windows Task Scheduler, cron, or an n8n "Execute Command" node.
