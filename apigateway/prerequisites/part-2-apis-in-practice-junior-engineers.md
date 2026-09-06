# APIs for Humans: Part 2 — APIs in Practice: Your First Real Calls

*Part 2 of 5 in the API Mastery Roadmap prerequisites series. Part 1 covered the concepts; this one gets you actually using APIs — reading documentation, making real requests with curl and Python, and handling authentication tokens safely. Target audience: junior engineers in their first role, bootcamp graduates, and anyone who understands the theory but hasn't wired it up in code yet.*

---

There's a gap that every junior engineer falls into, and it's not knowing the concepts — they've watched the YouTube videos, they understand REST, they can explain JSON in a job interview. The gap is the moment they sit down with real API documentation and have to make an actual call that works, handles errors, and doesn't accidentally commit a secret key to a public GitHub repo.

This article is about closing that gap.

We're going to work through a real API (GitHub's, since it requires zero signup to use most of it), cover how to read documentation you've never seen before, write a small Python script that actually does something useful, and talk about authentication in the way that prevents embarrassing (or career-threatening) mistakes.

---

## Learning to Read API Documentation

API documentation is a skill. The first time you open Stripe's docs, or GitHub's API reference, or AWS's API documentation, the volume of it is overwhelming. Here's the frame that makes it manageable:

Every API endpoint's documentation, regardless of how it's formatted, answers the same five questions:

1. **What is the HTTP method?** (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`)
2. **What is the path?** (`/repos/{owner}/{repo}/issues`)
3. **What parameters does it accept?** (path params, query params, request body)
4. **What does a successful response look like?** (status code + body shape)
5. **What can go wrong?** (error codes and their meanings)

Let's practice on a real example. Here's the GitHub API documentation entry for listing repository issues:

```
GET /repos/{owner}/{repo}/issues

Lists issues in a repository. Only open issues will be listed.

Path parameters:
  owner  (required)  string  The account owner of the repository
  repo   (required)  string  The name of the repository

Query parameters:
  state    string   Filter by state: open (default), closed, all
  labels   string   Comma-separated list of label names
  per_page integer  Results per page (max 100, default 30)
  page     integer  Page number (default 1)

Response:
  200 OK — Array of issue objects
  301 Moved Permanently
  404 Not Found
  422 Validation Failed
```

From this, I can immediately construct a valid request:

```bash
# Get the first 10 open issues labeled "bug" from the kubernetes/kubernetes repo
curl "https://api.github.com/repos/kubernetes/kubernetes/issues?state=open&labels=bug&per_page=10"
```

Path parameters (the `{owner}` and `{repo}`) go into the URL directly. Query parameters go after `?` as key-value pairs separated by `&`. This pattern holds for almost every REST API you'll ever use.

---

## curl is Your Best Friend for API Work

Before you write a single line of code, curl lets you test any API call from the terminal. It's the fastest way to validate that a request works before you invest time writing it in your language of choice.

**Basic GET request:**
```bash
curl https://api.github.com/users/octocat
```

**Pretty-print the JSON (so you can actually read it):**
```bash
curl -s https://api.github.com/users/octocat | python3 -m json.tool
```

**See the headers in the response (the `-I` flag, or `-i` to see headers *and* body):**
```bash
curl -I https://api.github.com/users/octocat
```

**POST request with a JSON body:**
```bash
curl -X POST https://api.example.com/items \
  -H "Content-Type: application/json" \
  -d '{"name": "widget", "price": 9.99}'
```

**Pass an authentication header:**
```bash
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  https://api.github.com/user
```

**Save a response to a file:**
```bash
curl -o response.json https://api.github.com/repos/torvalds/linux
```

The flags to memorize:
- `-s` — Silent mode (no progress bar, just the output)
- `-X METHOD` — Override the HTTP method
- `-H "Header: Value"` — Add a request header
- `-d 'body'` — Send a request body
- `-o filename` — Save output to a file
- `-v` — Verbose mode (shows headers on both sides — invaluable for debugging)

**Pro tip**: When a curl request isn't working and you don't know why, add `-v`. It shows you exactly what was sent and received, including headers you might be missing.

---

## Authentication: Don't Wing This Part

Authentication is where junior engineers most commonly get burned, either by leaking secrets or by implementing it wrong. Let's cover the three patterns you'll encounter constantly.

### Pattern 1: API Keys

The simplest form. You get a key (a long random string), and you pass it with every request — usually as a header, sometimes as a query parameter.

```bash
# As a header (more common, more secure)
curl -H "X-API-Key: sk_live_abc123xyz" https://api.example.com/data

# As a query parameter (less secure — shows up in server logs and browser history)
curl "https://api.example.com/data?api_key=sk_live_abc123xyz"
```

**The rule that protects your job:** Never hardcode API keys in source code. Not even once, even if you're sure it's just a test. Environments are for environment variables.

```bash
# In your terminal (for local dev)
export WEATHER_API_KEY="your_key_here"

# Then in your code
import os
api_key = os.environ.get("WEATHER_API_KEY")
```

If you ever accidentally commit a key, treat it as compromised immediately. Rotate it. Don't just delete the commit — commit history is forever, and bots scrape GitHub for exposed secrets within minutes of a push.

### Pattern 2: Bearer Tokens (OAuth 2.0)

Most production APIs, especially those that act on behalf of a user, use OAuth 2.0. You get a token (by logging in, or by exchanging a client ID and secret), and you send it as a `Bearer` token in the `Authorization` header.

```bash
curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  https://api.example.com/me
```

The token usually expires. When it does, you'll get a `401`. You then use a *refresh token* (a separate, longer-lived token) to get a new access token. The exact flow varies by API — read the docs.

### Pattern 3: Basic Auth

The oldest pattern. You send a username and password, base64-encoded, in the Authorization header. You'll mostly see this in internal tools and older APIs.

```bash
curl -u "username:password" https://api.example.com/resource
# This is equivalent to:
curl -H "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQ=" https://api.example.com/resource
```

Never use Basic Auth over plain HTTP. It's only acceptable over HTTPS, because base64 is not encryption — it's trivially reversible.

---

## Writing Your First API Consumer in Python

Let's build something real. We'll write a script that fetches the latest open issues from any GitHub repo and prints a summary. This is genuinely useful and gives you a template you can adapt to any API.

First, a note on the `requests` library. It's Python's standard tool for HTTP, and if you haven't installed it:

```bash
pip install requests
```

Here's the script:

```python
import os
import sys
import requests

def get_open_issues(owner: str, repo: str, token: str = None) -> list:
    """
    Fetches open issues from a GitHub repository.
    
    Token is optional for public repos, but GitHub's unauthenticated
    rate limit is only 60 requests/hour. With a token it's 5,000.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    params = {
        "state": "open",
        "per_page": 10,
        "sort": "updated",
        "direction": "desc"
    }
    
    response = requests.get(url, headers=headers, params=params)
    
    # Always check the status code before assuming success
    if response.status_code == 404:
        print(f"Repo {owner}/{repo} not found. Check the spelling.")
        sys.exit(1)
    
    if response.status_code == 403:
        print("Rate limit hit. Set a GITHUB_TOKEN to get 5,000 requests/hour.")
        sys.exit(1)
    
    # This raises an exception for any 4xx or 5xx response
    response.raise_for_status()
    
    return response.json()


def main():
    owner = sys.argv[1] if len(sys.argv) > 1 else "kubernetes"
    repo = sys.argv[2] if len(sys.argv) > 2 else "kubernetes"
    
    # Read token from environment — never hardcode it
    token = os.environ.get("GITHUB_TOKEN")
    
    print(f"\nFetching latest open issues from {owner}/{repo}...\n")
    issues = get_open_issues(owner, repo, token)
    
    if not issues:
        print("No open issues found.")
        return
    
    for issue in issues:
        labels = [label["name"] for label in issue.get("labels", [])]
        label_str = f"  [{', '.join(labels)}]" if labels else ""
        
        print(f"#{issue['number']:>6}  {issue['title'][:60]:<60}{label_str}")
        print(f"         Opened by @{issue['user']['login']} — "
              f"{issue['created_at'][:10]}")
        print()


if __name__ == "__main__":
    main()
```

Run it:

```bash
# No token (60 requests/hour limit)
python3 issues.py torvalds linux

# With a GitHub token (5,000 requests/hour)
export GITHUB_TOKEN="ghp_yourtokenhere"
python3 issues.py kubernetes kubernetes
```

Take a look at this script and notice the patterns — they apply to almost every API integration you'll ever write:

1. **Build the URL from parts**, don't concatenate strings by hand.
2. **Set headers explicitly** — the `Accept` header tells the server what format you want, the version header ensures the API doesn't surprise you with breaking changes.
3. **Put auth in headers, read credentials from the environment.**
4. **Handle specific error codes before the generic fallback.** 404 and 403 deserve their own messages; everything else can use `raise_for_status()`.
5. **Parse the JSON into Python objects** with `response.json()`. Never try to parse the JSON string yourself.

---

## Rate Limiting: The Thing That Will Bite You

Most APIs limit how many requests you can make in a time window. When you exceed it, you get a `429 Too Many Requests`. This is the part junior engineers often don't think about until it causes an incident.

The smart way to handle rate limits:

**Check the response headers.** Most APIs tell you your current limit status:

```bash
curl -I https://api.github.com/users/octocat
```

Look for headers like:
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 58
X-RateLimit-Reset: 1693485600
```

`X-RateLimit-Reset` is a Unix timestamp. When `Remaining` hits 0, you wait until that time.

**In code, handle 429 with exponential backoff:**

```python
import time

def make_request_with_retry(url: str, headers: dict, max_retries: int = 3):
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers)
        
        if response.status_code == 429:
            # Respect the Retry-After header if present
            retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
            print(f"Rate limited. Waiting {retry_after}s before retry {attempt + 1}/{max_retries}")
            time.sleep(retry_after)
            continue
        
        return response
    
    raise Exception(f"Max retries exceeded for {url}")
```

Don't just sleep a fixed amount and retry in a tight loop — that's how you make rate limit problems worse and potentially get your IP banned.

---

## Pagination: APIs Don't Give You Everything At Once

When you ask for a list of things — issues, users, transactions — the API rarely gives you all of them in one response. It paginates.

The two most common pagination patterns:

**Page-number pagination** (GitHub, many REST APIs):
```python
all_issues = []
page = 1

while True:
    response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/issues",
        headers=headers,
        params={"state": "open", "per_page": 100, "page": page}
    )
    
    data = response.json()
    if not data:
        break  # Empty page means we're done
    
    all_issues.extend(data)
    
    # Also check the Link header — GitHub tells you if there's a next page
    if 'next' not in response.links:
        break
    
    page += 1
```

**Cursor-based pagination** (Stripe, Slack, many newer APIs):
```python
all_events = []
cursor = None

while True:
    params = {"limit": 100}
    if cursor:
        params["starting_after"] = cursor
    
    response = requests.get("https://api.stripe.com/v1/events",
                           auth=(STRIPE_KEY, ""), params=params)
    data = response.json()
    
    all_events.extend(data["data"])
    
    if not data["has_more"]:
        break
    
    # The cursor is the ID of the last item in this page
    cursor = data["data"][-1]["id"]
```

Cursor-based pagination is generally better — it handles concurrent insertions correctly, which page-number pagination can't.

---

## Debugging API Calls: The Systematic Approach

When an API call isn't working, resist the urge to randomly change things and hope. Follow this sequence:

**Step 1: Get the raw request and response.**
```bash
curl -v -X POST "https://api.example.com/endpoint" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key": "value"}' 2>&1
```

The `2>&1` captures everything (including the verbose output that goes to stderr) so you can read it top to bottom.

**Step 2: Check the obvious things first.**
- Is the URL correct? (Extra slashes, wrong version path?)
- Is the method correct? (POST vs PUT?)
- Is the `Content-Type` header set when sending a body?
- Is the auth token fresh? (Tokens expire.)
- Does the body match the API's expected schema?

**Step 3: Look at the error response body, not just the status code.**

A 400 response has a body that tells you *what* was wrong. Most junior engineers stop at "I got a 400" when the body says something like `"missing required field: user_id"` and that's the entire answer.

```bash
curl -s -w "\nHTTP Status: %{http_code}\n" \
  -X POST "https://api.example.com/endpoint" \
  -H "Content-Type: application/json" \
  -d '{"incomplete": true}'
```

**Step 4: Reproduce in isolation.**

If something works in Postman but not in your code, or works in curl but not in your code, the problem is in how your code is constructing the request. Use `-v` in curl and add request logging to your code to compare them side by side.

---

## The Five Habits That Separate Good Junior Engineers from Average Ones

After watching a lot of code reviews over the years, these are the API integration habits that actually matter:

**1. Always validate the status code before touching the body.** `response.json()` on a 500 error might return an error object, might return garbage, might throw an exception. Check the status first.

**2. Use environment variables for every credential.** Not just production keys — all of them. Make it a habit from day one.

**3. Log the request ID or correlation header when it's there.** APIs that care about observability include a header like `X-Request-Id` or `X-Correlation-Id` in their responses. Log it. When something breaks and you need to ask the API provider to look up the request, that ID is the only way they can find it.

**4. Don't assume a 200 means success.** Some poorly-designed APIs return 200 with an error in the body (I've seen `{"success": false, "error": "payment declined"}` with a 200 status). Check the body too.

**5. Read the API changelog.** APIs change. If you're depending on an API in production, subscribe to their status page and changelog. You don't want to find out about a breaking change from a 3 AM pager.

---

## Recap

- Read API documentation by answering five questions: method, path, parameters, success response, and error responses.
- curl is your first debugging tool — use `-v` when things aren't working.
- Authentication patterns: API keys in headers (not query strings), Bearer tokens from OAuth, Basic auth only over HTTPS.
- Never hardcode credentials. Environment variables, every time.
- Handle specific status codes (404, 403, 429) before generic fallbacks.
- Rate limiting is real — check the headers and implement exponential backoff.
- Pagination is the rule, not the exception — page through lists instead of assuming one response has everything.

---

*Next up: [Part 3 — Designing APIs That Don't Embarrass You](./part-3-api-design-software-engineers.md). This one is for engineers who have consumed APIs and are now building them. Resource modeling, versioning, error contracts, idempotency, and the decisions you'll regret if you don't make them deliberately.*
