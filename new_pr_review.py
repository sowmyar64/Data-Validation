from __future__ import annotations
import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

# CONFIGURATION
GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_ORG = os.environ.get("GITHUB_ORG")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
FAIL_ON_VIOLATIONS = os.environ.get("FAIL_ON_VIOLATIONS", "false").lower() in ("1", "true", "yes")
STALE_DAYS_FOR_DEPENDABOT = int(os.environ.get("STALE_DAYS_FOR_DEPENDABOT", "14"))
DEDUP_FILE = os.environ.get("DEDUPE_FILE", ".pr_reporter_state.json")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))

# logging
LOG_FILE = os.environ.get("PR_REPORTER_LOG", "pr_reporter.log")
LOG_LEVEL = logging.INFO

if not GITHUB_TOKEN or not GITHUB_ORG:
    print("ERROR: Please set GITHUB_TOKEN and GITHUB_ORG environment variables.", file=sys.stderr)
    sys.exit(2)

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "pr-review-reporter/1.0",
}

# logging
logger = logging.getLogger("pr_reporter")
logger.setLevel(LOG_LEVEL)
fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)

fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3)
fh.setFormatter(fmt)
logger.addHandler(fh)


# Simple retry decorator for network calls
def with_retries(max_attempts: int = 3, initial_delay: float = 0.5, backoff: float = 2.0):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except requests.RequestException as e:
                    last_exc = e
                    logger.debug("HTTP attempt %d/%d failed: %s", attempt, max_attempts, e)
                    if attempt == max_attempts:
                        logger.debug("giving up after %d attempts", attempt)
                        raise
                    time.sleep(delay)
                    delay *= backoff
            raise last_exc
        return wrapper
    return deco


@with_retries()
def http_get(url: str, headers: Dict[str, str], params: Dict[str, Any] = None, timeout: int = 30) -> requests.Response:
    return requests.get(url, headers=headers, params=params, timeout=timeout)


@with_retries()
def http_post(url: str, headers: Dict[str, str], json_body: Any = None, timeout: int = 30) -> requests.Response:
    return requests.post(url, headers=headers, json=json_body, timeout=timeout)


# GET wrapper with pagination handling for GitHub REST endpoints
def gh_get(url: str, params: Dict[str, Any] = None, allow_404: bool = False) -> Any:
    h = dict(HEADERS)
    params = params or {}
    params.setdefault("per_page", 100)
    page = 1
    aggregated: List[Any] = []
    while True:
        params["page"] = page
        r = http_get(url, headers=h, params=params)
        if r.status_code == 404 and allow_404:
            return []
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            aggregated.extend(data)
        else:
            return data
        link = r.headers.get("Link", "")
        if 'rel="next"' not in link:
            break
        page += 1
        time.sleep(0.05)
    return aggregated


def gh_post_graphql(query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    r = http_post(GITHUB_GRAPHQL, headers=HEADERS, json_body={"query": query, "variables": variables})
    r.raise_for_status()
    return r.json()


def post_slack(text: str) -> None:

    if not SLACK_WEBHOOK:
        print(text)
        return
    payload = {"text": text}
    try:
        r = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Slack message posted.")
    except Exception as e:
        logger.exception("Failed to post Slack message: %s", e)


# Try org listing
def list_org_repos(org: str) -> List[Dict[str, Any]]:
    logger.info("Listing repositories for target=%s", org)
    url_org = f"{GITHUB_API}/orgs/{org}/repos"
    repos = gh_get(url_org, params={"type": "all"})
    # exclude archived/disabled repos
    repos = [r for r in repos if not r.get("archived") and not r.get("disabled")]
    logger.info("Found %d active repos", len(repos))
    return repos


def list_open_prs(owner: str, repo: str) -> List[Dict[str, Any]]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    return gh_get(url, params={"state": "open", "sort": "created", "direction": "desc"})


def get_pr_reviews(owner: str, repo: str, number: int) -> List[Dict[str, Any]]:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}/reviews"
    return gh_get(url, params={})


def get_pr_object(owner: str, repo: str, number: int) -> Dict[str, Any]:
    return gh_get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{number}")


# Return True if all threads resolved, False if any unresolved, None on error
def get_pr_threads_resolved(owner: str, repo: str, number: int) -> Optional[bool]:
    query = """
    query($owner:String!,$name:String!,$number:Int!,$first:Int!){
      repository(owner:$owner,name:$name){
        pullRequest(number:$number){
          reviewThreads(first:$first){
            totalCount
            nodes { isResolved }
          }
        }
      }
    }
    """
    try:
        resp = gh_post_graphql(query, {"owner": owner, "name": repo, "number": number, "first": 100})
        pr = resp.get("data", {}).get("repository", {}).get("pullRequest")
        if pr is None:
            logger.debug("GraphQL returned no PR for %s/%s #%d", owner, repo, number)
            return None
        threads = pr.get("reviewThreads", {})
        nodes = threads.get("nodes", [])
        if not nodes:
            return True
        any_unresolved = any(node.get("isResolved") is False for node in nodes)
        return not any_unresolved
    except Exception as e:
        logger.warning("GraphQL error for %s/%s #%d: %s", owner, repo, number, e)
        return None


# Analyze a single PR and return a summary dict with warnings/notes
def analyze_pr(owner: str, repo: str, pr: Dict[str, Any]) -> Dict[str, Any]:
    number = pr["number"]
    title = pr.get("title", "")
    author = pr.get("user", {}).get("login", "")
    logger.debug("Analyzing PR %s/%s #%d", owner, repo, number)

    summary = {
        "repo": f"{owner}/{repo}",
        "number": number,
        "title": title,
        "url": pr.get("html_url"),
        "author": author,
        "created_at": pr.get("created_at"),
        "warnings": [],
        "notes": [],
    }

    # reviews (dedupe to most recent per reviewer)
    try:
        reviews = get_pr_reviews(owner, repo, number)
    except Exception as e:
        logger.exception("Failed to fetch reviews for %s/%s #%d", owner, repo, number)
        reviews = []
        summary["warnings"].append("Could not fetch reviews (API error)")

    latest_by_user: Dict[str, Dict[str, Any]] = {}
    for r in reviews:
        user = (r.get("user") or {}).get("login")
        if not user:
            continue
        prev = latest_by_user.get(user)
        if prev is None or (r.get("submitted_at") or "") > (prev.get("submitted_at") or ""):
            latest_by_user[user] = r

    approvals = [r for r in latest_by_user.values() if r.get("state") == "APPROVED"]
    changes = [r for r in latest_by_user.values() if r.get("state") == "CHANGES_REQUESTED"]

    if not approvals:
        summary["warnings"].append("No approvals yet.")
    else:
        summary["notes"].append(f"Approvals: {len(approvals)}")

    if changes:
        summary["warnings"].append(f"{len(changes)} reviewer(s) requested changes.")

    # requested reviewers
    try:
        pr_obj = get_pr_object(owner, repo, number)
        requested_reviewers = pr_obj.get("requested_reviewers", [])
        requested_logins = [r.get("login") for r in requested_reviewers if r.get("login")]
        pending = [l for l in requested_logins if l and l not in latest_by_user]
        if pending:
            summary["warnings"].append(f"Pending requested reviewers: {', '.join(pending)}")
    except Exception as e:
        logger.debug("Could not fetch requested reviewers for %s/%s #%d: %s", owner, repo, number, e)

    # unresolved review threads
    resolved = get_pr_threads_resolved(owner, repo, number)
    if resolved is False:
        summary["warnings"].append("There are unresolved review conversations.")
    elif resolved is None:
        summary["warnings"].append("Unable to determine review thread resolution (GraphQL).")

    # Dependabot detection and age
    is_dependabot = "dependabot" in (author or "").lower() or (pr.get("head", {}).get("user") or {}).get("login", "").lower().startswith("dependabot")
    if is_dependabot:
        try:
            created_at = pr.get("created_at")
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days
        except Exception:
            age_days = None
        if age_days is None:
            summary["warnings"].append("Dependabot PR detected; cannot compute age.")
        else:
            summary["notes"].append(f"Dependabot PR age: {age_days} days")
            if age_days >= STALE_DAYS_FOR_DEPENDABOT and not approvals:
                summary["warnings"].append(f"Dependabot PR unhandled for {age_days} days (>= {STALE_DAYS_FOR_DEPENDABOT}).")
        summary["notes"].append("Dependabot PR")

    # mergeable check (be cautious: mergeable can be None)
    try:
        pr_obj2 = pr_obj
        mergeable = pr_obj2.get("mergeable")
        summary["mergeable"] = mergeable
        if mergeable and not approvals:
            summary["warnings"].append("PR is mergeable but has no approvals (policy violation candidate).")
    except Exception:
        pass

    return summary


# ----- Reporting ----
def build_report(org: str, items: List[Dict[str, Any]]) -> Tuple[str, int]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"*PR Review Status Report for* `{org}`\n_Time: {now}_\n"
    lines = [header]
    actionable = 0
    for s in items:
        repo = s["repo"]
        num = s["number"]
        title = s["title"][:140].replace("\n", " ")
        url = s.get("url", "")
        author = s.get("author", "")
        lines.append(f"*<{url}|{repo}#{num}>* — {title} (by `{author}`)")
        if s.get("warnings"):
            actionable += 1
            for w in s["warnings"]:
                lines.append(f"  • :warning: {w}")
        else:
            lines.append("  • :white_check_mark: OK")
        if s.get("notes"):
            for n in s["notes"]:
                lines.append(f"  • note: {n}")
        lines.append("")
    footer = f"_Repos with potentially actionable PRs: {actionable}_.\nRules: no merges without review; all review conversations resolved; Dependabot PRs handled."
    lines.append(footer)
    return "\n".join(lines), actionable


# State persistence for dedupe
def load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"reported": {}}
    except Exception as e:
        logger.exception("Failed to load dedupe file %s: %s", path, e)
        return {"reported": {}}


def save_state(path: str, state: Dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, default=str)
    except Exception:
        logger.exception("Failed to save dedupe file %s", path)


def make_pr_key(summary: Dict[str, Any]) -> str:
    return f"{summary['repo']}#{summary['number']}"


# Main flow
def main() -> None:
    logger.info("Starting PR review reporter for target=%s", GITHUB_ORG)
    repos = list_org_repos(GITHUB_ORG)
    if not repos:
        logger.info("No repositories found; exiting.")
        return

    # concurrent PR scanning
    summaries: List[Dict[str, Any]] = []
    total_prs = 0

    def scan_repo(repo_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
        owner = repo_obj["owner"]["login"]
        name = repo_obj["name"]
        repo_summaries: List[Dict[str, Any]] = []
        try:
            prs = list_open_prs(owner, name)
            if not prs:
                return []
            logger.info("Found %d open PR(s) in %s/%s", len(prs), owner, name)
            for pr in prs:
                repo_summaries.append(analyze_pr(owner, name, pr))
            return repo_summaries
        except Exception as e:
            logger.exception("Error processing repo %s/%s: %s", owner, name, e)
            return []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(scan_repo, r): r for r in repos}
        for fut in as_completed(futures):
            try:
                repo_summaries = fut.result()
                summaries.extend(repo_summaries)
                total_prs += len(repo_summaries)
            except Exception as e:
                logger.exception("Repo scan failed: %s", e)

    logger.info("Total PRs analyzed: %d", total_prs)

    if not summaries:
        msg = f"No open PRs found for `{GITHUB_ORG}` at {datetime.now(timezone.utc).isoformat()}."
        logger.info(msg)
        post_slack(msg)
        return

    # deduplication: load previous reported items and only notify about new/actionable changes
    state = load_state(DEDUP_FILE)
    reported = state.get("reported", {}) or {}
    to_notify: List[Dict[str, Any]] = []
    for s in summaries:
        key = make_pr_key(s)
        # actionable if warnings present
        actionable_flag = bool(s.get("warnings"))
        prev = reported.get(key)
        # notify if actionable and either not reported before or warnings changed
        if actionable_flag:
            prev_warnings = prev.get("warnings") if isinstance(prev, dict) else None
            if prev is None or prev_warnings != s.get("warnings"):
                to_notify.append(s)
            # update reported state
            reported[key] = {"warnings": s.get("warnings"), "last_seen": datetime.now(timezone.utc).isoformat()}
        else:
            # if previously reported but now resolved, we can notify resolution optionally
            if prev:
                # remove from reported so future re-appearances will be notified
                reported.pop(key, None)

    # save state 
    state["reported"] = reported
    save_state(DEDUP_FILE, state)

    # build and send report - include all PRs summary but emphasize actionable ones
    report_text, actionable_count = build_report(GITHUB_ORG, summaries)
    logger.debug("Report text:\n%s", report_text)

    try:
        post_slack(report_text)
    except Exception:
        logger.exception("Posting to Slack failed.")

    logger.info("Actionable PRs this run (changed/new): %d; total actionable currently: %d", len(to_notify), actionable_count)

    # optionally fail pipeline
    if actionable_count and FAIL_ON_VIOLATIONS:
        logger.error("Actionable PRs found (%d) and FAIL_ON_VIOLATIONS=true -> exiting 3", actionable_count)
        sys.exit(3)

    logger.info("Completed run; actionable PRs: %d", actionable_count)


if __name__ == "__main__":
    main()
