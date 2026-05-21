#!/usr/bin/env python3
"""
Jira Bug Classification and Slack Reporting Bot
================================================
Monitors newly created Jira bug tickets and classifies each one as:
  - Duplicate Bug
  - Regression Bug
  - Newly Introduced Bug
  - Needs Manual Review

Then posts the result to a designated Slack channel.

Usage:
  python bot.py                              # Check new bugs since last run
  python bot.py --ticket IOSX-123            # Classify a specific ticket
  python bot.py --since "2026-05-20 00:00"   # Check since a specific time
  python bot.py --watch                      # Continuous polling mode
  python bot.py --dry-run                    # Run without posting to Slack
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from jira_client import JiraClient
from classifier import classify
from slack_reporter import post_to_slack
from text_utils import extract_description, extract_search_keywords, build_jql_text_clause

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
LOG_PATH = os.path.join(BASE_DIR, "classifications.log")


# ── Config ───────────────────────────────────────────────────────────────────
def load_config():
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    # GitHub Actions secrets override config file values
    if os.environ.get("JIRA_API_TOKEN"):
        config["jira"]["api_token"] = os.environ["JIRA_API_TOKEN"]
    if os.environ.get("SLACK_WEBHOOK_URL"):
        config["slack"]["webhook_url"] = os.environ["SLACK_WEBHOOK_URL"]
        config["slack"]["enabled"] = True

    return config


# ── State ────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"last_run": None, "processed_keys": []}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


# ── Logging ──────────────────────────────────────────────────────────────────
def log_result(result):
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(result) + "\n")


# ── Core: classify one ticket ─────────────────────────────────────────────────
def process_ticket(jira, config, issue, dry_run=False):
    fields = issue.get("fields", {})
    key = issue["key"]
    summary = fields.get("summary", "(no title)")
    reporter_obj = fields.get("reporter") or {}
    reporter = reporter_obj.get("displayName", "Unknown")

    print(f"\n{'─'*60}")
    print(f"  Ticket  : {key}")
    print(f"  Title   : {summary}")
    print(f"  Reporter: {reporter}")
    print(f"  Classifying...")

    # Build search text from summary + description
    desc_text = extract_description(fields)
    full_text = f"{summary} {desc_text}"
    search_keywords = extract_search_keywords(full_text)
    jql_text = build_jql_text_clause(search_keywords) or summary[:60]

    # Find related existing bugs
    bot_cfg = config.get("bot", {})
    jira_cfg = config.get("jira", {})
    related_raw = jira.find_related_bugs(
        jql_text,
        exclude_key=key,
        projects=jira_cfg.get("projects"),
        max_results=bot_cfg.get("max_related_tickets", 5) * 3,
    )
    candidates = related_raw.get("issues", [])

    # Classify
    result_cls = classify(
        issue,
        candidates,
        threshold_high=bot_cfg.get("similarity_threshold_high", 0.65),
        threshold_low=bot_cfg.get("similarity_threshold_low", 0.35),
    )

    # Build full result
    base_url = jira_cfg.get("base_url", "")
    result = {
        "ticket_id": key,
        "title": summary,
        "reported_by": reporter,
        "classification": result_cls["type"],
        "confidence": result_cls["confidence"],
        "reasoning": result_cls["reasoning"],
        "related_tickets": result_cls["related_tickets"],
        "suggested_action": result_cls["suggested_action"],
        "jira_url": f"{base_url}/browse/{key}",
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Print to console
    print(f"\n  ┌─ CLASSIFICATION RESULT ───────────────────────────────")
    print(f"  │  Ticket         : {result['ticket_id']}")
    print(f"  │  Title          : {result['title']}")
    print(f"  │  Reported By    : {result['reported_by']}")
    print(f"  │  Classification : {result['classification']}")
    print(f"  │  Confidence     : {result['confidence']}")
    print(f"  │  Reasoning      : {result['reasoning']}")
    print(f"  │  Related Tickets: {', '.join(result['related_tickets']) or 'None'}")
    print(f"  │  Suggested Action: {result['suggested_action']}")
    print(f"  └───────────────────────────────────────────────────────")

    # Log to file
    log_result(result)

    # Post to Slack
    if not dry_run:
        slack_cfg = config.get("slack", {})
        if slack_cfg.get("enabled", False):
            post_to_slack(slack_cfg.get("webhook_url", ""), result)
        else:
            print("  [Slack] Slack disabled in config — skipping.")
    else:
        print("  [Dry Run] Slack post skipped.")

    return result


# ── Run modes ─────────────────────────────────────────────────────────────────
def run_once(jira, config, since_iso, state, dry_run=False):
    """Fetch and classify all new bugs since since_iso."""
    jira_cfg = config.get("jira", {})
    print(f"\nFetching new bugs since {since_iso}...")

    data = jira.get_new_bugs(
        since_iso,
        projects=jira_cfg.get("projects"),
        issue_types=jira_cfg.get("bug_issue_types"),
    )
    issues = data.get("issues", [])
    total = data.get("total", 0)
    print(f"Found {total} new bug(s).")

    processed = state.get("processed_keys", [])
    results = []

    for issue in issues:
        key = issue["key"]
        if key in processed:
            print(f"  Skipping {key} (already processed).")
            continue
        result = process_ticket(jira, config, issue, dry_run=dry_run)
        results.append(result)
        processed.append(key)

    # Update state
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["processed_keys"] = processed[-500:]  # Keep last 500 keys
    save_state(state)

    return results


def run_single_ticket(jira, config, ticket_key, dry_run=False):
    """Classify one specific Jira ticket by key."""
    issue = jira.get_issue(ticket_key)
    return process_ticket(jira, config, issue, dry_run=dry_run)


def run_watch(jira, config, dry_run=False):
    """Continuously poll Jira for new bugs."""
    poll_minutes = config.get("bot", {}).get("poll_interval_minutes", 15)
    print(f"\nWatch mode — polling every {poll_minutes} minute(s). Press Ctrl+C to stop.")

    while True:
        state = load_state()
        if state.get("last_run"):
            since = state["last_run"]
        else:
            lookback = config.get("bot", {}).get("lookback_hours", 24)
            since_dt = datetime.now(timezone.utc) - timedelta(hours=lookback)
            since = since_dt.strftime("%Y-%m-%d %H:%M")

        run_once(jira, config, since, state, dry_run=dry_run)
        print(f"\nNext poll in {poll_minutes} minute(s)...")
        time.sleep(poll_minutes * 60)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Jira Bug Classification Bot")
    parser.add_argument("--ticket", help="Classify a specific Jira ticket (e.g. IOSX-123)")
    parser.add_argument("--since", help="Check bugs created since this time (e.g. '2026-05-20 00:00')")
    parser.add_argument("--watch", action="store_true", help="Continuously poll for new bugs")
    parser.add_argument("--dry-run", action="store_true", help="Run without posting to Slack")
    args = parser.parse_args()

    config = load_config()
    jira_cfg = config.get("jira", {})
    jira = JiraClient(
        base_url=jira_cfg["base_url"],
        email=jira_cfg["email"],
        api_token=jira_cfg["api_token"],
    )

    print("=" * 60)
    print("  Jira Bug Classification Bot")
    print("=" * 60)

    if args.ticket:
        run_single_ticket(jira, config, args.ticket.upper(), dry_run=args.dry_run)

    elif args.watch:
        run_watch(jira, config, dry_run=args.dry_run)

    else:
        state = load_state()

        if args.since:
            since = args.since
        elif state.get("last_run"):
            since = state["last_run"]
        else:
            lookback = config.get("bot", {}).get("lookback_hours", 24)
            since_dt = datetime.now(timezone.utc) - timedelta(hours=lookback)
            since = since_dt.strftime("%Y-%m-%d %H:%M")

        run_once(jira, config, since, state, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
