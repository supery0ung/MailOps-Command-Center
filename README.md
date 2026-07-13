# MailOps Command Center

A privacy-first Gmail operations dashboard for triaging inbox messages, applying labels, archiving low-priority mail, reviewing attachments, and optionally using an AI CLI for ambiguous messages.

This public edition contains no mailbox data, OAuth tokens, personal contact rules, account identifiers, or prior Git history.

## What it does

- Retrieves a configurable batch of Gmail inbox messages.
- Suggests portable categories: **Finance**, **Operations**, **People & Education**, **Travel**, and **Technology**.
- Lets you review, relabel, archive, mark read, star, unsubscribe, and download attachments in one interface.
- Sends only uncertain messages to an optional local AI command for a second opinion.

## Quick start

1. Create a Google Cloud OAuth **Desktop app** credential with Gmail access, then save the downloaded file as `credentials.json` in the project root. Never commit this file.
2. Install the dependencies:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   ./start.sh
   ```

4. Open [http://127.0.0.1:5001](http://127.0.0.1:5001). On first use, complete the Google authorization flow; the generated `token.json` stays local and is ignored by Git.
5. In Gmail, create any of the suggested label names that you want the classifier to use: `Finance`, `Operations`, `People & Education`, `Travel`, and `Technology`.
6. Click **Fetch email**, review the suggestions, then click **Execute classification** only after confirming the actions.

## Optional AI review

For low-confidence messages, the app can call a local AI CLI. Install and authenticate your preferred compatible command, then set the command in the environment before starting the app:

```bash
export MAILOPS_AI_COMMAND="claude"
./start.sh
```

If no compatible command is configured, continue using the rules and manual review; Gmail actions are never performed automatically.

## Privacy and security

- `credentials.json`, `token.json`, runtime caches, and local environment files are ignored by Git.
- Do not paste access tokens, mailbox exports, customer lists, or real addresses into source files or issue trackers.
- Run this dashboard locally. It binds to `127.0.0.1` by default.
- Review every proposed action before execution; mailbox changes are made with your own Google authorization.

## Project structure

```text
MailOps-Command-Center/
├── web_app.py          Flask application and API routes
├── classifier.py       Portable classification rules
├── gmail_wrapper.py    Gmail API integration
├── lib/                Authentication and Gmail helper modules
├── static/             Browser behavior and styling
├── templates/          HTML template
└── start.sh            Local launcher (port 5001)
```

## Customizing rules

Edit `classifier.py` to add organization-specific categories or keywords. Keep account-specific addresses and personal information in an untracked local configuration file rather than committing them to the repository.

## License

Add a license that fits your intended use before distributing this project.
