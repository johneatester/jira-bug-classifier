import requests
from requests.auth import HTTPBasicAuth


class JiraClient:
    def __init__(self, base_url, email, api_token):
        self.base_url = base_url.rstrip("/")
        self.auth = HTTPBasicAuth(email, api_token)
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _get(self, path, params=None):
        url = f"{self.base_url}{path}"
        resp = requests.get(url, auth=self.auth, headers=self.headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, body):
        import json
        url = f"{self.base_url}{path}"
        resp = requests.post(url, auth=self.auth, headers=self.headers, data=json.dumps(body), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_issue(self, issue_key):
        return self._get(f"/rest/api/3/issue/{issue_key}")

    def search(self, jql, fields=None, max_results=50, start_at=0):
        body = {
            "jql": jql,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": fields if fields else [
                "summary", "description", "status", "resolution", "reporter",
                "assignee", "components", "labels", "fixVersions", "issuetype",
                "created", "updated", "priority"
            ],
        }
        return self._post("/rest/api/3/search/jql", body)

    def get_new_bugs(self, since_iso, projects=None, issue_types=None):
        """Fetch bug tickets created after since_iso (e.g. '2026-05-20 00:00')."""
        type_clause = ""
        if issue_types:
            types = ", ".join(f'"{t}"' for t in issue_types)
            type_clause = f" AND issuetype in ({types})"
        else:
            type_clause = ' AND issuetype = Bug'

        proj_clause = ""
        if projects:
            keys = ", ".join(f'"{p}"' for p in projects)
            proj_clause = f" AND project in ({keys})"

        jql = f'created > "{since_iso}"{type_clause}{proj_clause} ORDER BY created DESC'
        return self.search(jql, max_results=50)

    def find_related_bugs(self, keywords_text, exclude_key, projects=None, max_results=20):
        """Full-text search for similar existing bugs."""
        import re
        safe = re.sub(r'[^a-zA-Z0-9 ]', ' ', keywords_text)
        safe = " ".join(safe.split()[:8])
        if not safe.strip():
            return {"issues": []}

        proj_clause = ""
        if projects:
            keys = ", ".join(f'"{p}"' for p in projects)
            proj_clause = f" AND project in ({keys})"

        jql = (
            f'text ~ "{safe}" AND issuetype = Bug AND key != "{exclude_key}"'
            f'{proj_clause} ORDER BY created DESC'
        )
        try:
            return self.search(jql, max_results=max_results)
        except Exception:
            return {"issues": []}

    def get_resolved_statuses(self):
        return {"done", "resolved", "closed", "fixed", "won't fix", "wont fix",
                "cannot reproduce", "duplicate", "rejected", "obsolete"}
