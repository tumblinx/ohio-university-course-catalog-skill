# ou-course-search

An unofficial command-line client and Claude Code skill for searching Ohio
University course offerings.

It talks to the public JSON API behind
<https://webapps.ohio.edu/classes/search>, which is an Angular single-page app —
fetching its HTML gets you an empty `<app-root>`, so this calls the endpoint the
page itself calls. No account, API key, or credential is involved.

**Not affiliated with, endorsed by, or supported by Ohio University.**

## Status of the API

The endpoint is public, unauthenticated, and CORS-open — OU configured it to be
callable from browsers. But it is **undocumented**: OU has not published it as a
developer API, makes no stability promise, and can change or remove it without
notice. Expect this tool to break someday.

The **official course offerings site is the system of record.** Seat counts,
statuses, and deadlines move daily and can be stale here. Verify anything you
are about to register for, pay for, or build a schedule around against the
official site. This tool is a convenience, not an authority.

## Install

Python 3.9+, no dependencies.

```bash
git clone <this repo> ~/.claude/skills/ou-course-search
chmod +x ~/.claude/skills/ou-course-search/ou_courses.py
```

As a Claude Code skill, drop the directory in `~/.claude/skills/` and `SKILL.md`
is picked up automatically.

## Set a contact first

Requests identify themselves with a `User-Agent` so OU can reach a human rather
than silently blocking the client. **Set it to something that reaches you:**

```bash
export OU_COURSE_SEARCH_CONTACT="https://github.com/you/ou-course-search"
```

The tool prints a reminder to stderr until you do. If you fork or redistribute
this, put *your* contact there, not the upstream one.

## Usage

```bash
./ou_courses.py terms                        # term ids + which is current
./ou_courses.py subjects [pattern]           # 222 subject codes
./ou_courses.py search --subject PAW --wide  # sections, with fees/prereqs/flags
./ou_courses.py search --name "scuba" --wide # keyword match on course title
./ou_courses.py show "REC 1220-100"          # fees, deadlines, books, restrictions
./ou_courses.py conflicts --enrolled "CS 4560-101,EE 4673-103" \
                          --candidate "REC 1220-100"
```

Add `--json out.json` to any search to dump raw records.

## Being a good citizen

The defaults here are deliberately conservative. Please don't loosen them.

| Behavior | Default | Override |
|---|---|---|
| Min seconds between requests | 1.0 | `OU_COURSE_SEARCH_INTERVAL` |
| Cache location | `$XDG_CACHE_HOME/ou-course-search` | `OU_COURSE_SEARCH_CACHE` |
| Lookup table TTL (`/data/*`) | 24h | — |
| Search result TTL | 10 min | — |

`--no-cache` bypasses the cache for a single run (use when seat counts matter);
`--clear-cache` empties it first.

`ohio.edu`'s robots.txt advertises `Crawl-delay: 10` for its own crawlers. This
client is an interactive query tool making a handful of requests, not a crawler,
but the 1-second floor and the response cache exist to keep it well clear of
anything that could look like load. **Do not** run this in a loop to mirror the
catalog, and do not remove the throttle.

If OU asks you to change or stop something, do that.

## Data and redistribution

This repository ships **no Ohio University data** — everything is fetched at
request time. Please keep it that way: don't commit cached results, scraped
dumps, or bulk exports. Factual listings (times, rooms, seat counts) aren't
copyrightable, but course descriptions are OU's text.

The API returns no student information. Course, section, and instructor data
only.

## License

The client code is released under the MIT License. That covers this code only —
not the data it retrieves, and not any Ohio University name, logo, or mark.
