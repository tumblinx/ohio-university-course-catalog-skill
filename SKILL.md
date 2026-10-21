---
name: ou-course-search
description: Search Ohio University course offerings via the JSON API behind webapps.ohio.edu/classes/search. Use when the user asks about OU classes, sections, seat availability, schedule conflicts, prerequisites, fees, gen-ed bricks, or pass/fail eligibility — for any term or campus. Handles the SPA's hidden API, pagination, and the catalog's data traps.
---

# Ohio University course offerings

The search page at `https://webapps.ohio.edu/classes/search` is an Angular SPA — fetching its
HTML gets you an empty `<app-root>`. Talk to the JSON API underneath instead. It is **public,
unauthenticated, and CORS-open**.

## Use the helper script

`ou_courses.py` (in this skill directory) wraps the whole API. Prefer it over hand-rolled curl.

```bash
S=~/.claude/skills/ou-course-search/ou_courses.py

$S terms                            # term ids + which is current
$S subjects [pattern]               # 222 subject codes
$S search --subject PAW --wide      # sections, with fees/prereqs/flags
$S search --credits 1 --open-only --no-prereq --max-level 4000 --wide
$S search --name "podcast"          # keyword match on course title
$S show "AVN 1100-100"              # full detail: fees, deadlines, books, restrictions
$S conflicts --enrolled "CS 4560-101,EE 4673-103" --candidate "AVN 1100-100"
```

`conflicts` pulls real meeting data from the API for every section named, checks the enrolled
set against itself, and reports credit totals — so it catches conflicts a student's own
schedule already contains, not just candidate collisions.

Add `--json out.json` to any search to dump raw records for custom analysis.

Responses are cached (24h for `/data/*` lookups, 10 min for searches) and requests are
throttled to 1/sec. Pass `--no-cache` when seat counts matter — they move daily — or
`--clear-cache` to empty the cache first. See README.md before sharing or publishing this.

## API contract

Base: `https://ais.kube.ohio.edu/api/course-offerings`

| Endpoint | Method | Notes |
|---|---|---|
| `/data/terms`, `/data/terms/default` | GET | term objects: `strm`, `year`, `code`, `description` |
| `/data/subjects` | GET | subject codes + long names |
| `/data/instructors`, `/data/buildings`, `/data/programs` | GET | lookups |
| `/data/bricks`, `/data/bricks/themes` | GET | gen-ed taxonomy |
| `/search/query?selectedTab={campus}&page=N&pageSize=50` | **POST** | the search |
| `/search/counts` | POST | per-campus totals only |

**Four things that will waste your time if you don't know them:**

1. **Term ids are `{strm}::{CODE}`**, not `strm` alone — `2271::FALL`. The `/data/terms`
   response gives you the parts; the UI concatenates them. Sending `"2271"` returns a 500.
2. **The POST body must be complete.** Every key in `DEFAULT_PAYLOAD` must be present or the
   server returns `{"error":true,"message":"An internal server error occurred"}`. A partial
   body is not a partial filter — it's a crash. Missing/invalid *types* return
   `"Invalid request payload input"` instead.
3. **`pageSize` is capped at 50** regardless of what you ask for. Loop until
   `len(results) >= counts[campus]`.
4. **Results contain duplicates.** De-dupe on `classNumber`.

Campus ids: `ATHN` (Athens), plus regionals and `ECAM` (eCampus, which requires `program`).
Status values: `OPEN`, `WAITLIST`, `FULL`, `MAJORS`, `PERMISSION`. Responses also return
`OPEN75`, meaning open but ≥75% full — treat it as open.

## Data traps in the catalog itself

These bit us in real use; the helper handles each one.

- **`requisite` does not contain every restriction.** Major-only limits are often *only* in the
  free-text `note` field: ECT 1700 shows `requisite: None` but its note says "For VRGD majors
  only." Always check `note` before telling someone a class is open to them.
  `hidden_restriction()` extracts these; `--no-prereq` filters them out.
- **`eligibleGrades` is the pass/fail signal.** `CR` in that list means the section permits
  credit/no-credit. Only ~20% of sections have it, so it's genuinely discriminating — and it
  can contradict assumptions (a CS special-topics course allowed CR while a required EE course
  did not). Note this is the *section's* grade basis; a student's P/F election is a separate
  registrar form with its own earlier deadline.
- **`bricks` = gen-ed attribution.** If a school's P/F rule is "only for courses not needed for
  degree requirements," a course carrying a brick is a bad P/F target. Filtering for an empty
  `bricks` field is the right move for that question.
- **Half-semester sections are everywhere** (PAW, REC especially). `beginDate`/`endDate` differ
  from `termStartDate`/`termEndDate`. Two sections can share a time slot without conflicting
  because their date ranges don't overlap — conflict math **must** compare dates, not just
  days and times.
- **Seats = `maxEnrolled - enrolled`**, and it can be negative on over-enrolled sections.
- **Fees** live in `fee` and `guaranteeFee`; take the max. Some are large ($288 for scuba).
- **Required books** are in `resources[]` where `required: true` and `title` is set — a good
  proxy for workload. The same array also carries long boilerplate legal text with no title;
  skip those.
- **Deadlines are per-section**: `lastDayToAdd`, `lastDayToDrop`, `lastDayToWithdraw`. They
  differ between sections in the same term, especially for short sessions.
- **Subject codes are not intuitive.** ASL is under `HSLS`, not `DSI`. Nursing is `NRSE`, not
  `NURS`. Business spans `ACCT/AIS/BA/BUSL/FIN/MGT/MKT/OPN/REAL/SASM`. When a subject search
  comes up empty, search by `--name` keyword before concluding a course isn't offered.

## Reporting well

Seat counts and statuses move daily — say when the data was pulled. When a student is choosing
classes, the useful output is not a raw dump: sort by whatever constraint they actually named,
flag fees / permission / major restrictions / required weekend trips inline, and separate
courses that fit their schedule from ones that collide. Run `conflicts` against their real
enrolled sections rather than eyeballing times.
