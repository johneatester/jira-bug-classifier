# Jira Bug Classification Bot

Monitors newly created Jira bug tickets and automatically classifies each one as:

- **Duplicate Bug** — same issue already exists in Jira
- **Regression Bug** — previously fixed issue that has reappeared
- **Newly Introduced Bug** — no prior matching ticket found
- **Needs Manual Review** — unclear or low confidence

Posts results to a designated Slack channel.

---

## Setup

### 1. Install dependencies
```bash
cd jirabugsclassification
pip install -r requirements.txt
```

### 2. Configure Slack

Open `config.json` and update the Slack section:

```json
"slack": {
  "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
  "channel": "#qa-bug-triage",
  "enabled": true
}
```

To get a Slack webhook URL: Slack → Your App → Incoming Webhooks → Add New Webhook.

### 3. (Optional) Adjust settings

```json
"bot": {
  "poll_interval_minutes": 15,       // How often to poll in watch mode
  "lookback_hours": 24,              // How far back to look on first run
  "max_related_tickets": 5,          // Max related tickets to show
  "similarity_threshold_high": 0.65, // Score >= this → strong match
  "similarity_threshold_low": 0.35   // Score >= this → partial match
}
```

---

## Usage

### Check new bugs since last run
```bash
python bot.py
```

### Classify a specific ticket
```bash
python bot.py --ticket IOSX-956
```

### Check bugs since a specific time
```bash
python bot.py --since "2026-05-20 00:00"
```

### Watch mode (continuous polling)
```bash
python bot.py --watch
```

### Dry run (no Slack posting)
```bash
python bot.py --dry-run
python bot.py --ticket DROID-400 --dry-run
```

---

## Output

### Console
```
────────────────────────────────────────────────────────────
  Ticket  : IOSX-957
  Title   : Login button disabled after network error
  Reporter: Jane Smith
  Classifying...

  ┌─ CLASSIFICATION RESULT ───────────────────────────────
  │  Ticket         : IOSX-957
  │  Title          : Login button disabled after network error
  │  Reported By    : Jane Smith
  │  Classification : Regression Bug
  │  Confidence     : High
  │  Reasoning      : Strongly matches IOSX-792 which was previously resolved...
  │  Related Tickets: IOSX-792, IOSX-803
  │  Suggested Action: Tag as regression. Link to IOSX-792. Escalate to dev.
  └───────────────────────────────────────────────────────
```

### Slack Message
```
New Jira Bug Classification

Ticket: IOSX-957
Title: Login button disabled after network error
Reported By: Jane Smith
Classification: ⚠️ Regression Bug
Confidence: 🟢 High
Reasoning: Strongly matches IOSX-792 (previously resolved)...
Related Tickets: IOSX-792, IOSX-803
Suggested Action: Tag as regression. Link to IOSX-792.
```

### Log file
All results are appended to `classifications.log` (one JSON object per line).

---

## Files

| File | Purpose |
|---|---|
| `bot.py` | Main entry point and run modes |
| `classifier.py` | Classification logic (duplicate / regression / new / review) |
| `jira_client.py` | Jira REST API v3 wrapper |
| `slack_reporter.py` | Slack webhook posting with Block Kit formatting |
| `text_utils.py` | Text similarity, ADF extraction, tokenization |
| `config.json` | Credentials and settings |
| `state.json` | Auto-generated — tracks last run and processed tickets |
| `classifications.log` | Auto-generated — full classification history |

---

## Classification Logic

```
New bug ticket created
        │
        ▼
Search Jira for related historical bugs
        │
        ▼
Score similarity (title + description + components + labels)
        │
        ├── score >= 0.65 AND ticket is resolved → REGRESSION BUG
        │
        ├── score >= 0.65 AND ticket is open     → DUPLICATE BUG
        │
        ├── score 0.35–0.65                      → NEEDS MANUAL REVIEW
        │
        └── score < 0.35                         → NEWLY INTRODUCED BUG
```

**Similarity scoring:**
- 50% — Jaccard token overlap (keyword matching)
- 30% — Sequence similarity (difflib)
- 10% — Component match bonus
- 10% — Label match bonus
