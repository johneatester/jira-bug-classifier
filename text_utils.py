import re
import difflib

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "was", "are", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall", "can",
    "not", "no", "nor", "so", "yet", "both", "either", "neither",
    "as", "if", "than", "then", "when", "where", "while", "after",
    "before", "during", "into", "through", "that", "this", "these",
    "those", "there", "their", "they", "them", "we", "our", "us",
    "i", "my", "me", "you", "your", "he", "she", "his", "her",
    "up", "out", "about", "over", "also", "just", "because",
}


def extract_text_from_adf(node):
    """Recursively extract plain text from Atlassian Document Format."""
    if node is None:
        return ""
    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return " "
    text = ""
    for child in node.get("content", []):
        text += extract_text_from_adf(child)
    if node_type in ("paragraph", "heading", "listItem", "bulletList", "orderedList", "blockquote"):
        text += " "
    return text


def extract_description(fields):
    """Extract plain text from a Jira issue's description field (ADF or plain string)."""
    desc = fields.get("description")
    if desc is None:
        return ""
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return extract_text_from_adf(desc)
    return ""


def tokenize(text):
    """Lowercase, strip punctuation, remove stop words, return token set."""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    return {t for t in tokens if t not in STOP_WORDS and len(t) > 2}


def jaccard(set1, set2):
    if not set1 or not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)


def sequence_similarity(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower()[:500], b.lower()[:500]).ratio()


def compute_similarity(new_ticket_text, candidate_text, new_components, cand_components, new_labels, cand_labels):
    """
    Returns a float 0.0–1.0 representing how similar two bug tickets are.
    Weighted: 50% Jaccard token overlap, 30% sequence similarity, 20% metadata match.
    """
    new_tokens = tokenize(new_ticket_text)
    cand_tokens = tokenize(candidate_text)

    jac = jaccard(new_tokens, cand_tokens)
    seq = sequence_similarity(new_ticket_text, candidate_text)

    # Component overlap bonus
    comp_bonus = 0.0
    if new_components and cand_components:
        nc = {c.lower() for c in new_components}
        cc = {c.lower() for c in cand_components}
        if nc & cc:
            comp_bonus = 0.15

    # Label overlap bonus
    label_bonus = 0.0
    if new_labels and cand_labels:
        nl = {l.lower() for l in new_labels}
        cl = {l.lower() for l in cand_labels}
        if nl & cl:
            label_bonus = 0.1

    raw = (0.50 * jac) + (0.30 * seq) + (0.10 * comp_bonus) + (0.10 * label_bonus)
    return min(raw, 1.0)


def extract_search_keywords(text, max_keywords=8):
    """Pull top keywords from text for use in a JQL text search."""
    tokens = list(tokenize(text))
    # Sort by length descending (longer = more specific)
    tokens.sort(key=len, reverse=True)
    return tokens[:max_keywords]


def build_jql_text_clause(keywords):
    """Build a safe JQL text~ clause from keywords."""
    safe = [re.sub(r'[^a-z0-9 ]', '', k) for k in keywords if len(k) > 2]
    safe = [k for k in safe if k]
    if not safe:
        return None
    return " ".join(safe[:6])
