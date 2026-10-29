"""Collect every number the README card displays.

Two data sources:
  * GitHub - repos, stars, followers (cheap GraphQL) and, per repository,
    your commits plus their added/deleted lines (REST, author-filtered).
  * GoatCounter - profile views. Read through the JSON API, which is the
    whole point: reading never increments the counter the way the badge
    request does. Visitors hit /count, we only ever read.

Nothing here is rate-limit naive: requests are spaced, 403/429 back off
until the reset window, 5xx retries, and per-repo results are cached by
pushedAt in CACHE_PATH so a daily run only rescans repositories that moved.

    python3 stats.py              # print the numbers, no README write
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USER = "ItsZcx"
API = "https://api.github.com"
CACHE_PATH = ".github/stats-cache.json"

# Repositories whose diffs are data, not code: vendor trees, datasets,
# generated dumps. They still count toward commits and repos, they just do
# not belong in a "lines of code" figure. Edit freely.
LOC_EXCLUDE = {
    "ItsZcx/PackItUp",  # +1.8M lines in 2 commits
    "EpitechPromo2027/B-SVR-500-BAR-5-1-survivor-joan-pau.merida-ruiz",  # -533k
}

# The same history published twice, so its diff is only counted once.
MIRRORS = {
    "fas-ai/fas-ai": "EpitechPromo2027/G-EIP-600-BAR-6-1-eip-oriol.linan",
}

GOATCOUNTER_SITE = os.environ.get("GOATCOUNTER_SITE", "https://zcx.goatcounter.com")
GOATCOUNTER_PATH = os.environ.get("GOATCOUNTER_PATH", "/profile")


def _env(name):
    return (os.environ.get(name) or "").strip() or None


GH_TOKEN = _env("STATS_TOKEN") or _env("ACCESS_TOKEN") or _env("GITHUB_TOKEN")
GC_TOKEN = _env("GOATCOUNTER_TOKEN")
GOATCOUNTER_SITE = GOATCOUNTER_SITE.rstrip("/")

REQUESTS = 0


# ---------------------------------------------------------------- transport


def _request(url, data=None, token=None, allow=()):
    """One HTTP call with rate-limit aware retries. Returns (json, headers)."""
    global REQUESTS
    token = token or GH_TOKEN

    for attempt in range(7):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{USER}-readme-stats",
        }
        if token:
            headers["Authorization"] = (
                f"Bearer {token}"  # GoatCounter is case-sensitive
            )
        if data is not None:
            headers["Content-Type"] = "application/json"

        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, data=data, headers=headers), timeout=90
            ) as response:
                REQUESTS += 1
                payload = response.read()
                return (json.loads(payload) if payload else {}), response.headers
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            if error.code in allow:  # e.g. 409 on an empty repository
                return {}, error.headers
            remaining = error.headers.get("X-RateLimit-Remaining")
            reset = error.headers.get("X-RateLimit-Reset")
            retry_after = error.headers.get("Retry-After")

            if error.code in (403, 429) and attempt < 6:
                if retry_after:
                    wait = int(retry_after)
                elif remaining == "0" and reset:
                    wait = int(reset) - int(time.time()) + 2
                else:
                    wait = 60  # secondary limit: no reset header
                wait = max(5, min(wait, 3600))
                print(
                    f"    rate limited ({error.code}), sleeping {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue

            if error.code >= 500 and attempt < 6:
                time.sleep(5 * (attempt + 1))
                continue

            if error.code in (401, 403):
                if "goatcounter" in url:
                    raise SystemExit(
                        f"GoatCounter rejected the token (HTTP {error.code}).\n"
                        f"  - is GOATCOUNTER_TOKEN exported in this shell?\n"
                        f"  - no quotes, no trailing newline\n"
                        f"  - create/rotate it at {GOATCOUNTER_SITE}/user/api"
                    )
                raise SystemExit(
                    f"GitHub rejected STATS_TOKEN (HTTP {error.code}).\n"
                    f"  - scope must include `repo` for private/org repos\n"
                    f"  - SAML orgs need Configure SSO -> Authorize on the token"
                )

            hint = body[:200] + ("..." if len(body) > 200 else "")
            if body.lstrip().startswith("<"):
                hint = "(HTML error page, not JSON)"
            raise SystemExit(f"HTTP {error.code} {url}\n{hint}")

    raise SystemExit(f"gave up on {url}")


def graphql(query, variables):
    body, _ = _request(
        API + "/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
    )
    if "errors" in body:
        raise SystemExit(f"GraphQL errors: {body['errors']}")
    return body["data"]


def rest(path, params=None, allow=()):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _request(url, allow=allow)


# ------------------------------------------------------------------ github

USER_QUERY = """
query ($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
  }
}"""

OWNED_QUERY = """
query ($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
      totalCount
      edges { node { stargazers { totalCount } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""

ACCESSIBLE_QUERY = """
query ($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      edges { node { nameWithOwner isPrivate pushedAt } }
      pageInfo { hasNextPage endCursor }
    }
  }
}"""

SCAN_QUERY = """
query ($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor) {
            totalCount
            edges {
              node {
                additions
                deletions
                author { user { login } }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
  }
}"""

WINDOW_QUERY = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner pushedAt }
      }
    }
  }
}"""


def profile():
    """Owned repos, stars received, followers."""
    user = graphql(USER_QUERY, {"login": USER})["user"]
    stars, cursor, total = 0, None, 0
    while True:
        data = graphql(OWNED_QUERY, {"login": USER, "cursor": cursor})
        owned = data["user"]["repositories"]
        total = owned["totalCount"]
        stars += sum(
            edge["node"]["stargazers"]["totalCount"] for edge in owned["edges"]
        )
        if not owned["pageInfo"]["hasNextPage"]:
            break
        cursor = owned["pageInfo"]["endCursor"]
    return {
        "repos": total,
        "stars": stars,
        "followers": user["followers"]["totalCount"],
        "created": user["createdAt"],
    }


def accessible_repos():
    """Every repo the token can read: owned, collaborator, org member.

    Uses REST /user/repos rather than GraphQL's ownerAffiliations filter.
    The GraphQL path silently omitted private organisation repositories even
    with a `repo`-scoped, SSO-authorised token; the REST endpoint is the
    canonical "what can this token see" list and returns them.
    """
    repos, page = {}, 1
    while True:
        batch, headers = rest(
            "/user/repos",
            {
                "affiliation": "owner,collaborator,organization_member",
                "per_page": 100,
                "page": page,
                "sort": "pushed",
                "direction": "desc",
            },
        )
        if not batch:
            break
        for repo in batch:
            repos[repo["full_name"]] = {
                "pushedAt": repo["pushed_at"],
                "isPrivate": repo["private"],
            }
        if 'rel="next"' not in (headers.get("Link") or ""):
            break
        page += 1
    return repos


def my_commit_count(full_name):
    """How many commits you authored on the default branch. One request.

    The Link header's last page number is the total when per_page=1, so this
    is a cheap way to skip repositories you never committed to before paying
    for a full history scan.
    """
    body, headers = rest(
        f"/repos/{full_name}/commits", {"author": USER, "per_page": 1}, allow=(404, 409)
    )
    if not body:
        return 0
    link = headers.get("Link") or ""
    match = re.search(r'[?&]page=(\d+)>; rel="last"', link)
    return int(match.group(1)) if match else 1


def scan_repo(full_name):
    """Your commits on the default branch + their added/deleted lines.

    REST's commit *list* does not carry diff stats (it silently returns
    stats: 0), and fetching each commit individually would be one request
    per commit. GraphQL's history connection returns additions/deletions
    inline, 100 commits at a time, so it is the only affordable route.

    Caveat: the API cannot filter history by author, so this pages through
    every commit in the repo and keeps the ones you authored.
    """
    owner, name = full_name.split("/", 1)
    commits = added = deleted = 0
    cursor, pages = None, 0

    while True:
        data = graphql(SCAN_QUERY, {"owner": owner, "name": name, "cursor": cursor})
        repo = data["repository"]
        ref = repo and repo.get("defaultBranchRef")
        if not ref:  # empty repository
            return {"commits": 0, "added": 0, "deleted": 0}

        history = ref["target"]["history"]
        pages += 1
        if pages == 1 and history.get("totalCount", 0) > 50000:
            print(
                f"    {full_name}: {history['totalCount']:,} commits, this will take a while",
                file=sys.stderr,
            )

        for edge in history["edges"]:
            node = edge["node"]
            login = ((node.get("author") or {}).get("user") or {}).get("login")
            if login != USER:
                continue
            commits += 1
            added += node.get("additions") or 0
            deleted += node.get("deletions") or 0

        page = history["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    return {"commits": commits, "added": added, "deleted": deleted}


# ------------------------------------------------------------------- views


def views():
    """Read the GoatCounter total. Reading never increments the counter.

    /stats/hits returns one stats entry per day in the window, so asking for
    everything since 2000 returns ~10k days of hourly buckets (4.5 MB). The
    counter cannot have hits before the account existed, so the account's
    created_at is both correct and tiny.
    """
    if not GC_TOKEN:
        raise SystemExit("GOATCOUNTER_TOKEN is not set")

    me, _ = _request(f"{GOATCOUNTER_SITE}/api/v0/me", token=GC_TOKEN)
    since = (me.get("user") or {}).get("created_at") or "2000-01-01T00:00:00Z"
    since = since.split("T")[0] + "T00:00:00Z"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    body, _ = _request(
        f"{GOATCOUNTER_SITE}/api/v0/stats/hits?start={since}&end={now}&limit=100",
        token=GC_TOKEN,
    )
    for hit in body.get("hits", []):
        path = hit.get("path", "")  # field is `path`, not `name`
        if path == GOATCOUNTER_PATH or path == GOATCOUNTER_PATH.lstrip("/"):
            return hit.get("count", 0)
    return body.get("total") or 0


# ------------------------------------------------------------------- cache


def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=1, sort_keys=True)


# -------------------------------------------------------------------- main


def fetch(verbose=True):
    started = time.time()

    views_total = views()  # cheapest call, and validates the token first
    who = profile()
    visible = accessible_repos()

    cache = load_cache()
    scanned = checked = skipped = 0

    for full_name in sorted(visible):
        meta = visible[full_name]
        entry = cache.get(full_name)

        if entry and entry.get("pushedAt") == meta["pushedAt"]:
            skipped += 1
        else:
            if verbose:
                print(f"  checking {full_name}", file=sys.stderr)
            mine = my_commit_count(full_name)
            checked += 1
            time.sleep(0.1)  # stay clear of burst limits

            if mine == 0:
                entry = {"commits": 0, "added": 0, "deleted": 0}
            else:
                if verbose:
                    print(
                        f"    scanning {full_name} ({mine} of yours)", file=sys.stderr
                    )
                entry = scan_repo(full_name)
                scanned += 1
                if entry["commits"] == 0:
                    # REST found your commits by email but GraphQL could not
                    # match them to an account; trust the count, lose the diff
                    print(
                        f"    {full_name}: {mine} commits found, no diff stats "
                        f"(unlinked author?)",
                        file=sys.stderr,
                    )
                    entry["commits"] = mine

            entry["pushedAt"] = meta["pushedAt"]
            cache[full_name] = entry
            save_cache(cache)  # resumable if the job dies mid-scan

    cache = {name: cache[name] for name in visible if name in cache}
    save_cache(cache)

    commits = sum(entry["commits"] for entry in cache.values())

    loc_repos = {
        name: entry
        for name, entry in cache.items()
        if name not in LOC_EXCLUDE and not (name in MIRRORS and MIRRORS[name] in cache)
    }
    added = sum(entry["added"] for entry in loc_repos.values())
    deleted = sum(entry["deleted"] for entry in loc_repos.values())

    if verbose:
        print(
            f"  {scanned} scanned, {skipped} unchanged, {checked} probed, "
            f"{REQUESTS} requests, {time.time() - started:.0f}s",
            file=sys.stderr,
        )

    return {
        "repos": who["repos"],
        "stars": who["stars"],
        "followers": who["followers"],
        "commits": commits,
        "loc": added - deleted,
        "added": added,
        "deleted": deleted,
        "views": views_total,
        "contributed": sum(1 for entry in cache.values() if entry["commits"] > 0),
    }


if __name__ == "__main__":
    for key, value in fetch().items():
        print(f"{key:>14}: {value}")
