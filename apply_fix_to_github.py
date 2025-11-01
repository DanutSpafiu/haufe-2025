# apply_fix_to_github.py
import os
import hmac
import hashlib
import requests
from typing import Dict

def create_pr_with_fix(
    repo: str,
    branch: str,
    file_path: str,
    old_code: str,
    new_code: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> Dict:
    """
    Creates a new branch, commits the fix, and opens a PR.
    Uses GITHUB_TOKEN (built-in in GitHub Actions & Streamlit Cloud).
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not found in environment")

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    base_url = f"https://api.github.com/repos/{repo}"

    # 1. Get default branch SHA
    r = requests.get(f"{base_url}/git/refs/heads/main", headers=headers)
    r.raise_for_status()
    main_sha = r.json()["object"]["sha"]

    # 2. Create new branch
    r = requests.post(
        f"{base_url}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": main_sha},
    )
    if r.status_code != 201:
        raise Exception(f"Failed to create branch: {r.text}")

    # 3. Get current file content (to get blob SHA)
    r = requests.get(f"{base_url}/contents/{file_path}", headers=headers, params={"ref": "main"})
    r.raise_for_status()
    content = r.json()
    old_content = requests.get(content["download_url"]).text

    if old_code not in old_content:
        raise ValueError("Original code snippet not found in file. Cannot apply fix safely.")

    # 4. Update file
    new_content = old_content.replace(old_code, new_code, 1)  # Replace first occurrence
    new_content_b64 = requests.post(
        "https://api.github.com/markdown",
        headers=headers,
        json={"text": new_content, "mode": "gfm"},
    ).text  # Just encode

    import base64
    content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

    r = requests.put(
        f"{base_url}/contents/{file_path}",
        headers=headers,
        json={
            "message": commit_message,
            "content": content_b64,
            "sha": content["sha"],
            "branch": branch,
        },
    )
    r.raise_for_status()

    # 5. Create PR
    r = requests.post(
        f"{base_url}/pulls",
        headers=headers,
        json={
            "title": pr_title,
            "head": branch,
            "base": "main",
            "body": pr_body,
        },
    )
    r.raise_for_status()
    return r.json()