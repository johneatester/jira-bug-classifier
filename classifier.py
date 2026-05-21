from text_utils import (
    extract_description, compute_similarity, extract_search_keywords, build_jql_text_clause
)


RESOLVED_STATUSES = {
    "done", "resolved", "closed", "fixed", "won't fix", "wont fix",
    "cannot reproduce", "duplicate", "rejected", "obsolete"
}


def _flatten_ticket(fields):
    """Combine all comparable text fields into one searchable string."""
    parts = []
    parts.append(fields.get("summary") or "")
    parts.append(extract_description(fields))
    for comp in fields.get("components") or []:
        parts.append(comp.get("name", "") if isinstance(comp, dict) else str(comp))
    for label in fields.get("labels") or []:
        parts.append(label)
    return " ".join(p for p in parts if p).strip()


def _get_components(fields):
    comps = fields.get("components") or []
    return [c.get("name", "") for c in comps if isinstance(c, dict)]


def _get_labels(fields):
    return fields.get("labels") or []


def _is_resolved(fields):
    status_name = (fields.get("status") or {}).get("name", "").lower()
    resolution_name = ((fields.get("resolution") or {}).get("name", "") or "").lower()
    return status_name in RESOLVED_STATUSES or resolution_name in RESOLVED_STATUSES


def score_candidates(new_fields, candidates):
    """
    Score each candidate against the new ticket.
    Returns list of dicts sorted by score descending.
    """
    new_text = _flatten_ticket(new_fields)
    new_comps = _get_components(new_fields)
    new_labels = _get_labels(new_fields)

    scored = []
    for issue in candidates:
        f = issue.get("fields", {})
        cand_text = _flatten_ticket(f)
        cand_comps = _get_components(f)
        cand_labels = _get_labels(f)

        score = compute_similarity(new_text, cand_text, new_comps, cand_comps, new_labels, cand_labels)
        scored.append({
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", "Unknown"),
            "resolution": ((f.get("resolution") or {}).get("name", "") or ""),
            "score": round(score, 3),
            "is_resolved": _is_resolved(f),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def classify(new_issue, candidates, threshold_high=0.65, threshold_low=0.35):
    """
    Classify a new bug ticket.

    Returns a dict:
      type, confidence, reasoning, related_tickets, suggested_action
    """
    fields = new_issue.get("fields", {})
    new_summary = fields.get("summary", "")

    scored = score_candidates(fields, candidates)
    best = scored[0] if scored else None
    top_related = [s["key"] for s in scored[:3] if s["score"] >= threshold_low]

    # ── No candidates found ──────────────────────────────────────────────────
    if not best or best["score"] < threshold_low:
        return {
            "type": "Newly Introduced Bug",
            "confidence": "High" if (not best or best["score"] < 0.15) else "Medium",
            "reasoning": (
                "No sufficiently similar tickets found in Jira history. "
                "This appears to be a failure unique to the current build or feature."
            ),
            "related_tickets": top_related,
            "suggested_action": "Count as new failure — triage and assign priority.",
        }

    # ── Medium match → Needs Manual Review ──────────────────────────────────
    if threshold_low <= best["score"] < threshold_high:
        return {
            "type": "Needs Manual Review",
            "confidence": "Medium",
            "reasoning": (
                f"Partial match found with {best['key']} "
                f"(similarity {best['score']:.0%}, status: {best['status']}). "
                "Not confident enough to classify as duplicate or regression without human review."
            ),
            "related_tickets": top_related,
            "suggested_action": (
                f"Assign to QA lead for manual comparison with {best['key']}."
            ),
        }

    # ── Strong match ─────────────────────────────────────────────────────────
    confidence = "High" if best["score"] >= 0.80 else "Medium"

    if best["is_resolved"]:
        res_label = best["resolution"] or best["status"]
        return {
            "type": "Regression Bug",
            "confidence": confidence,
            "reasoning": (
                f"Strongly matches {best['key']} ({best['summary'][:80]}...) "
                f"which was previously {res_label}. "
                f"The same issue appears to have reappeared (similarity {best['score']:.0%})."
            ),
            "related_tickets": top_related,
            "suggested_action": (
                f"Tag as regression. Link to {best['key']}. "
                "Escalate to the dev team responsible for the most recent fix."
            ),
        }
    else:
        return {
            "type": "Duplicate Bug",
            "confidence": confidence,
            "reasoning": (
                f"Strongly matches existing open ticket {best['key']} "
                f"({best['summary'][:80]}...) "
                f"with status '{best['status']}' (similarity {best['score']:.0%}). "
                "The issue is already being tracked."
            ),
            "related_tickets": top_related,
            "suggested_action": (
                f"Close as duplicate of {best['key']}. "
                "Add a link and notify the reporter."
            ),
        }
