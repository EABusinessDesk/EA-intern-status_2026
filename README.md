# EA Intern Status

Publishes a nightly, metadata-only digest of commit activity across the nine
Extremum Analytics intern project repositories, so that an automated end-of-day
review can read it without needing credentials.

## Why this exists

The intern project repos are private. The scheduled review runs in an
environment whose network policy allows **unauthenticated** GitHub traffic only —
any request carrying a token is refused, even against a public repo. So the
review cannot read the private repos directly.

This repository bridges that gap. A GitHub Action runs inside the organisation,
where the token works normally, reads the private repos, and writes a digest
here. This repo is public, so the review can clone it anonymously.

## What is published

Commit **metadata only**. Specifically: commit SHA (short), author name and
login, timestamp, branch, lines added/removed, number of files changed, the
file paths touched, and the commit message. Plus per-repo shape: branch list,
total commit count, first commit date, active dates, top-level directories, and
a few structural markers (has tests, has a frontend, etc.).

**No file contents and no diffs are ever written.**

Two settings in `projects.json` tighten this further if you want:

- `redact_commit_messages: true` — omit commit messages entirely
- `include_file_paths: false` — omit the list of changed file paths

## Setup

1. **Create this repository** as `ExtremumAnalytics-CIR/EA-intern-status`, and
   make it **public**. That is what allows anonymous reads; nothing sensitive
   is published here.

2. **Add the token as a secret.** In this repo: Settings → Secrets and variables
   → Actions → New repository secret.
   - Name: `INTERN_REVIEW_TOKEN`
   - Value: the fine-grained read-only PAT scoped to the organisation

   The token needs `Contents: Read` and `Metadata: Read` on all org
   repositories. It never needs write access anywhere.

3. **Push these files** to the default branch, keeping the layout:

   ```
   .github/workflows/collect.yml
   scripts/collect.py
   projects.json
   ```

4. **Fill in the three missing repos.** `projects.json` has `"repo": null` for
   P6, P7 and P8 because no repository exists for them yet. The digest reports
   them as `no_repo_configured`, which is itself useful. Set the name once each
   intern creates their repo.

5. **Set `day1_date`** in `projects.json` to the cohort's Day 1 date. This is
   what the review uses to work out which day of the nine-day plan everyone
   should be on.

6. **Run it once by hand** — Actions tab → "Collect intern commit digest" →
   Run workflow — and confirm `data/latest.json` appears.

## Schedule

The Action runs at `10 15 * * 1-5` (15:10 UTC = 20:40 IST, Mon–Fri), about
twenty minutes before the 21:00 IST review reads it. GitHub's scheduled runs can
be delayed under load, so the review checks `generated_at_utc` and says so if
the digest is stale rather than silently reporting yesterday's numbers.

## Output

- `data/latest.json` — most recent digest
- `data/YYYY-MM-DD.json` — one file per day, building a history you can look
  back through

## Maintenance

- Renamed a repo? Update `projects.json`.
- Token expired? Regenerate it and update the `INTERN_REVIEW_TOKEN` secret. The
  Action will fail loudly rather than publish an empty digest.
