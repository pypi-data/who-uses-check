"""Compare the public names of a package before and after a change, and look up each removed
name in the py-code.org index to see which PyPI packages use it.

Usage:
  python check.py --base BASE_DIR --head HEAD_DIR [--source src] [--packages a,b]
                  [--min-downloads N] [--max-lookups N] [--comment] [--fail-on-used]

Writes a Markdown report to $GITHUB_STEP_SUMMARY (or stdout), sets the outputs `removed` and
`used`, and with --comment creates or updates one comment on the pull request.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from public_api import find_packages, public_names
from py_code_org.api import ApiError, Index

MARKER = "<!-- py-code-api-check -->"


def human(n):
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(n)


def source_root(tree: Path, source):
    if source:
        return tree / source
    return tree / "src" if (tree / "src").is_dir() and find_packages(tree / "src") else tree


def removed_names(base, head, source, packages):
    base_root, head_root = source_root(base, source), source_root(head, source)
    packages = packages or sorted(set(find_packages(base_root)))
    before = public_names(base_root, packages)
    after = public_names(head_root, packages)
    removed = sorted(before - after)
    # Report a removed class or module once, not once per member.
    gone = set(removed)
    top = [n for n in removed if not any(n.startswith(p + ".") for p in gone if p != n)]
    return packages, top, removed


def lookup(index, names, min_downloads, max_lookups):
    used, unused, skipped = [], [], names[max_lookups:]
    for name in names[:max_lookups]:
        hit = index.who_uses(name)
        rows = [r for r in (hit or {}).get("rows", []) if r[2] >= min_downloads]
        if hit and rows:
            used.append({"name": name, "total": hit["total"], "matching": len(rows), "top": rows[:5]})
        else:
            unused.append(name)
    used.sort(key=lambda u: -u["total"])
    return used, unused, skipped


def report(packages, top, removed, used, unused, skipped, built, min_downloads):
    lines = [MARKER, "### Public names removed in this change", ""]
    if not top:
        lines.append(f"No public names of {', '.join(f'`{p}`' for p in packages)} were removed.")
        return "\n".join(lines) + "\n"
    users = f" with at least {human(min_downloads)} downloads a month" if min_downloads else ""
    lines.append(f"{len(top)} public name{'s' if len(top) != 1 else ''} removed or renamed"
                 + (f" ({len(removed)} counting class members)" if len(removed) != len(top) else "")
                 + f". {len(used)} of them {'are' if len(used) != 1 else 'is'} used by packages on PyPI{users}.")
    if used:
        lines += ["", "| Removed name | PyPI packages using it | Most downloaded users |", "|---|--:|---|"]
        for u in used:
            link = f"https://py-code.org/search/?q={urllib.parse.quote(u['name'])}"
            who = ", ".join(f"{r[0]} ({human(r[2])}/mo)" if r[2] else r[0] for r in u["top"])
            count = f"{u['total']:,}" if not min_downloads else f"{u['matching']:,}"
            lines.append(f"| [`{u['name']}`]({link}) | {count} | {who} |")
    if unused:
        shown = ", ".join(f"`{n}`" for n in unused[:20])
        more = f" and {len(unused) - 20} more" if len(unused) > 20 else ""
        lines += ["", f"No indexed package uses: {shown}{more}."]
    if skipped:
        lines += ["", f"{len(skipped)} more removed names were not looked up (`max-lookups`)."]
    lines += ["", f"<sub>From [py-code.org](https://py-code.org): imports and attribute use in the latest release "
                  f"of PyPI projects, index built {built[:10]}. Dynamic imports and names reached through "
                  f"variables are not counted.</sub>"]
    return "\n".join(lines) + "\n"


def github(method, url, token, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "py-code-api-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r) if r.status != 204 else None


def post_comment(text, had_findings):
    token, repo, event_path = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_EVENT_PATH")
    if not (token and repo and event_path):
        print("::notice::Not commenting: GITHUB_TOKEN or the pull request event is missing.")
        return
    event = json.loads(Path(event_path).read_text())
    number = (event.get("pull_request") or {}).get("number")
    if not number:
        print("::notice::Not commenting: this run is not for a pull request.")
        return
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    try:
        existing = None
        page = 1
        while existing is None:
            batch = github("GET", f"{api}/repos/{repo}/issues/{number}/comments?per_page=100&page={page}", token)
            existing = next((c for c in batch if MARKER in (c.get("body") or "")), None)
            if len(batch) < 100:
                break
            page += 1
        if existing:
            github("PATCH", f"{api}/repos/{repo}/issues/comments/{existing['id']}", token, {"body": text})
        elif had_findings:
            github("POST", f"{api}/repos/{repo}/issues/{number}/comments", token, {"body": text})
    except urllib.error.HTTPError as e:
        # Pull requests from forks get a read-only token; the job summary still has the report.
        print(f"::warning::Could not comment on the pull request (HTTP {e.code}). The report is in the job summary.")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--source", default="")
    ap.add_argument("--packages", default="")
    ap.add_argument("--min-downloads", type=int, default=0)
    ap.add_argument("--max-lookups", type=int, default=300)
    ap.add_argument("--comment", action="store_true")
    ap.add_argument("--fail-on-used", action="store_true")
    a = ap.parse_args(argv)

    packages = [p.strip() for p in a.packages.split(",") if p.strip()]
    packages, top, removed = removed_names(Path(a.base), Path(a.head), a.source, packages)
    if not packages:
        print("::error::No Python packages found. Set the `source` or `packages` input.")
        return 2
    index = Index()
    try:
        used, unused, skipped = lookup(index, top, a.min_downloads, a.max_lookups)
        built = index.status().get("built", "")
    except ApiError as e:
        print(f"::warning::Could not reach the py-code.org index: {e}")
        used, unused, skipped, built = [], top, [], ""
    text = report(packages, top, removed, used, unused, skipped, built, a.min_downloads)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text.replace(MARKER + "\n", ""))
    print(text.replace(MARKER + "\n", ""))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"removed={len(top)}\nused={len(used)}\n")
    if a.comment:
        post_comment(text, bool(top))
    if a.fail_on_used and used:
        print(f"::error::{len(used)} removed public names are used by packages on PyPI.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
