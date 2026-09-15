#!/usr/bin/env python3
"""
Collect a daily commit digest for the Extremum Analytics intern projects.

Runs inside GitHub Actions, where the token works normally. Reads the private
project repos and writes a metadata-only digest into data/ in this repository,
which is public so that the Cowork scheduled task can read it anonymously.

No file contents and no diffs are ever written out -- only commit metadata,
file paths, and line counts.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN", "").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if not TOKEN:
    sys.exit("GH_TOKEN is not set. Add the PAT as a repository or org secret named INTERN_REVIEW_TOKEN.")


def api(path, params=None):
    """GET a GitHub API path. Returns (status, parsed_json_or_None)."""
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ea-intern-status",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return e.code, None
        except Exception:
            if attempt < 2:
                time.sleep(3)
                continue
            return 0, None
    return 0, None


def main():
    cfg = json.load(open(os.path.join(ROOT, "projects.json")))
    org = cfg["org"]
    off = timedelta(hours=float(cfg.get("timezone_offset_hours", 5.5)))
    redact = bool(cfg.get("redact_commit_messages", False))
    want_paths = bool(cfg.get("include_file_paths", True))

    now_utc = datetime.now(timezone.utc)
    local_now = now_utc + off
    # Local calendar day -> UTC window
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = (local_midnight - off).replace(tzinfo=timezone.utc)

    day1 = datetime.strptime(cfg["day1_date"], "%Y-%m-%d").date()
    elapsed = (local_now.date() - day1).days + 1  # Day 1 is the start date itself

    out = {
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_date": local_now.strftime("%Y-%m-%d"),
        "window_start_utc": since_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "day1_date": cfg["day1_date"],
        "elapsed_day_number": elapsed,
        "org": org,
        "projects": [],
    }

    for p in cfg["projects"]:
        rec = {
            "project": p["project"],
            "name": p["name"],
            "assignee": p["assignee"],
            "repo": p.get("repo"),
        }

        if not p.get("repo"):
            rec["status"] = "no_repo_configured"
            out["projects"].append(rec)
            continue

        status, repo = api(f"/repos/{org}/{p['repo']}")
        if status == 404 or repo is None:
            rec["status"] = "repo_not_found" if status == 404 else f"api_error_{status}"
            out["projects"].append(rec)
            continue

        rec["status"] = "ok"
        rec["default_branch"] = repo.get("default_branch")
        rec["repo_created_at"] = repo.get("created_at")
        rec["last_push_at"] = repo.get("pushed_at")
        rec["is_empty"] = bool(repo.get("size", 0) == 0)

        # Branches
        _, branches = api(f"/repos/{org}/{p['repo']}/branches", {"per_page": 100})
        branch_names = [b["name"] for b in (branches or [])]
        rec["branches"] = branch_names

        # Commits in today's local window, across all branches, de-duplicated
        seen = {}
        for br in branch_names or [rec.get("default_branch")]:
            if not br:
                continue
            _, commits = api(
                f"/repos/{org}/{p['repo']}/commits",
                {"sha": br, "since": out["window_start_utc"], "per_page": 100},
            )
            for c in commits or []:
                seen.setdefault(c["sha"], {"commit": c, "branches": set()})["branches"].add(br)

        today = []
        add = dele = 0
        for sha, item in seen.items():
            c = item["commit"]
            _, detail = api(f"/repos/{org}/{p['repo']}/commits/{sha}")
            stats = (detail or {}).get("stats", {}) or {}
            files = (detail or {}).get("files", []) or []
            add += stats.get("additions", 0)
            dele += stats.get("deletions", 0)
            entry = {
                "sha": sha[:8],
                "author": (c.get("commit", {}).get("author", {}) or {}).get("name"),
                "login": (c.get("author") or {}).get("login"),
                "date": (c.get("commit", {}).get("author", {}) or {}).get("date"),
                "branches": sorted(item["branches"]),
                "additions": stats.get("additions", 0),
                "deletions": stats.get("deletions", 0),
                "files_changed": len(files),
            }
            if not redact:
                entry["message"] = (c.get("commit", {}).get("message") or "").strip()[:500]
            if want_paths:
                entry["paths"] = [f.get("filename") for f in files][:40]
            today.append(entry)

        today.sort(key=lambda x: x["date"] or "")
        rec["commits_today"] = today
        rec["commit_count_today"] = len(today)
        rec["additions_today"] = add
        rec["deletions_today"] = dele

        # Cumulative history on the default branch
        _, all_commits = api(
            f"/repos/{org}/{p['repo']}/commits",
            {"sha": rec.get("default_branch") or "main", "per_page": 100},
        )
        hist = all_commits or []
        rec["total_commits_default_branch"] = len(hist)
        dates = sorted({(c.get("commit", {}).get("author", {}) or {}).get("date", "")[:10] for c in hist} - {""})
        rec["first_commit_date"] = dates[0] if dates else None
        rec["active_days"] = len(dates)
        rec["active_dates"] = dates[-14:]

        # Repository shape, for judging "does it look like the day's deliverable"
        _, tree = api(
            f"/repos/{org}/{p['repo']}/git/trees/{rec.get('default_branch') or 'main'}",
            {"recursive": "1"},
        )
        paths = [t["path"] for t in (tree or {}).get("tree", []) if t.get("type") == "blob"]
        rec["file_count"] = len(paths)
        rec["top_level"] = sorted({p2.split("/")[0] for p2 in paths})[:40]
        markers = {
            "has_readme": any(p2.lower().startswith("readme") for p2 in paths),
            "has_tests": any("test" in p2.lower() for p2 in paths),
            "has_requirements": any(p2.lower().endswith(("requirements.txt", "pyproject.toml")) for p2 in paths),
            "has_frontend": any(p2.lower().endswith(("package.json",)) for p2 in paths),
            "mentions_langgraph": any("langgraph" in p2.lower() for p2 in paths),
        }
        rec["markers"] = markers

        out["projects"].append(rec)

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    for fname in (f"{out['local_date']}.json", "latest.json"):
        with open(os.path.join(ROOT, "data", fname), "w") as f:
            json.dump(out, f, indent=2, sort_keys=False)

    print(f"Wrote digest for {out['local_date']} (day {elapsed}), {len(out['projects'])} projects.")
    for r in out["projects"]:
        print(f"  {r['project']:>3} {r['assignee']:<16} {r.get('status'):<20} commits_today={r.get('commit_count_today', '-')}")


if __name__ == "__main__":
    main()
