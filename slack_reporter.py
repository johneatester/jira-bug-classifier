import json
import requests

CLASSIFICATION_EMOJI = {
    "Duplicate Bug": ":twisted_rightwards_arrows:",
    "Regression Bug": ":warning:",
    "Newly Introduced Bug": ":beetle:",
    "Needs Manual Review": ":mag:",
}

CONFIDENCE_EMOJI = {
    "High": ":green_circle:",
    "Medium": ":yellow_circle:",
    "Low": ":red_circle:",
}


def build_slack_message(result):
    """Build a Slack Block Kit message from a classification result."""
    ticket_id = result["ticket_id"]
    title = result["title"]
    reporter = result["reported_by"]
    cls = result["classification"]
    confidence = result["confidence"]
    reasoning = result["reasoning"]
    related = result["related_tickets"]
    action = result["suggested_action"]
    jira_url = result.get("jira_url", "")

    cls_emoji = CLASSIFICATION_EMOJI.get(cls, ":white_circle:")
    conf_emoji = CONFIDENCE_EMOJI.get(confidence, ":white_circle:")

    related_str = ", ".join(related) if related else "None"
    ticket_link = f"<{jira_url}|{ticket_id}>" if jira_url else ticket_id

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "New Jira Bug Classification",
                "emoji": True
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Ticket:*\n{ticket_link}"},
                {"type": "mrkdwn", "text": f"*Reported By:*\n{reporter}"},
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Title:*\n{title}"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Classification:*\n{cls_emoji}  {cls}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{conf_emoji}  {confidence}"},
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reasoning:*\n{reasoning}"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Related Tickets:*\n{related_str}"},
                {"type": "mrkdwn", "text": f"*Suggested Action:*\n{action}"},
            ]
        },
        {"type": "divider"},
    ]

    return {"blocks": blocks, "text": f"[{cls}] {ticket_id}: {title}"}


def post_to_slack(webhook_url, result):
    """Post a classification result to Slack via webhook. Returns True on success."""
    if not webhook_url or webhook_url == "YOUR_SLACK_WEBHOOK_URL_HERE":
        print("  [Slack] Webhook not configured — skipping Slack post.")
        return False

    message = build_slack_message(result)
    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(message),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"  [Slack] Posted classification for {result['ticket_id']}")
            return True
        else:
            print(f"  [Slack] Failed ({resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        print(f"  [Slack] Error posting to Slack: {e}")
        return False
