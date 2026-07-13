# MailOps Command Center: User Guide

## First-time setup

1. In Google Cloud Console, create an OAuth desktop-app credential with Gmail API access.
2. Save the downloaded credential file as `credentials.json` in the project root. Keep it on your computer only; never upload it to GitHub.
3. Install the required packages:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

4. Start the application:

   ```bash
   ./start.sh
   ```

5. Open `http://127.0.0.1:5001`. The first launch opens Google's authorization flow. After you approve access, the local `token.json` file is created and ignored by Git.

## Daily workflow

1. Select how many inbox messages to load and click **Fetch email**.
2. MailOps suggests a category using portable rules. Uncertain messages stay in the Inbox for manual or AI review.
3. Confirm or change each proposed action from the message menu: keep in Inbox, archive, or move to a Gmail label.
4. Expand a message when you need to inspect its content or attachments. Use the unsubscribe option when it is available.
5. Review all selected actions, then click **Execute classification**. The app marks messages as read before moving or archiving them.

## Recommended Gmail labels

Create any of these labels in Gmail to use the included default rules:

- `Finance` — invoices, receipts, payments, and transactions
- `Operations` — projects, contracts, meetings, and support work
- `People & Education` — training, school, and people-related messages
- `Travel` — flights, hotels, itineraries, and reservations
- `Technology` — software, security, deployment, and product updates

## Optional AI review

If you have a compatible local AI command installed, configure it before starting the application:

```bash
export MAILOPS_AI_COMMAND="claude"
./start.sh
```

AI produces suggestions only for low-confidence messages. You remain responsible for reviewing and confirming every Gmail action.

## Security reminders

- Never upload `credentials.json`, `token.json`, mailbox exports, or runtime caches.
- Never commit real email addresses, customer details, internal domains, or access tokens.
- The application listens only on `127.0.0.1` by default. Do not expose it directly to the public internet without adding authentication and security controls.
