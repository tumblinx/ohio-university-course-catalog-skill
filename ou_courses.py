#!/usr/bin/env python3
"""
Ohio University course-offerings API client.

The public search page at https://webapps.ohio.edu/classes/search is an Angular
SPA. This talks directly to the JSON API underneath it. No auth required.

Discovered contract (see SKILL.md for the full write-up):
  base            https://ais.kube.ohio.edu/api/course-offerings
  POST /search/query?selectedTab={campus}&page=N&pageSize=50
  GET  /data/terms          /data/terms/default   /data/subjects
  GET  /data/instructors    /data/buildings       /data/programs
"""
import argparse, hashlib, json, os, re, sys, time, urllib.request, datetime as dt
from pathlib import Path

BASE = "https://ais.kube.ohio.edu/api/course-offerings"
PAGE_SIZE = 50  # server caps here; larger values are silently clamped

# --- politeness ------------------------------------------------------------
# This endpoint is public and unauthenticated, but it is undocumented and not
# published as a developer API. Identify ourselves so OU can reach a human
# instead of silently blocking the client, and pace requests to well under the
# Crawl-delay: 10 that ohio.edu's robots.txt advertises for its own crawlers.
#
# SET THIS before publishing or sharing: a repo URL or email that reaches you.
CONTACT = os.environ.get(
    "OU_COURSE_SEARCH_CONTACT", "https://example.invalid/UNSET-see-README")
VERSION = "1.0"
USER_AGENT = f"ou-course-search/{VERSION} (unofficial client; +{CONTACT})"

MIN_INTERVAL = float(os.environ.get("OU_COURSE_SEARCH_INTERVAL", "1.0"))
_last_request = 0.0

# Cached responses. Lookup tables change once a term; seat counts move daily,
# so searches get a short TTL and detail views an even shorter one.
CACHE_DIR = Path(os.environ.get(
    "OU_COURSE_SEARCH_CACHE",
    os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
) / "ou-course-search"
TTL_LOOKUP = 24 * 3600   # /data/* reference tables
TTL_SEARCH = 600         # /search/* results
CACHE_ENABLED = True


def _throttle():
    """Space requests out; the API has no published rate limit, so we set one."""
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _cache_path(key):
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def _cache_read(key, ttl):
    if not CACHE_ENABLED:
        return None
    f = _cache_path(key)
    try:
        if time.time() - f.stat().st_mtime < ttl:
            return json.loads(f.read_text())
    except (OSError, ValueError):
        pass
    return None


def _cache_write(key, value):
    if not CACHE_ENABLED:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps(value))
    except OSError:
        pass  # cache is an optimization; never fail the query over it

# The API 500s on partial payloads. Every key below must be present.
DEFAULT_PAYLOAD = {
    "terms": [], "campuses": ["ATHN"], "program": "", "subjects": [],
    "catalogNumber": "", "name": "", "topic": "", "level": "ALL",
    "status": ["OPEN", "WAITLIST"],
    "generalEducationTier1": [], "generalEducationTier2": [],
    "generalEducationTier3": [], "themes": [], "bricks": [],
    "isSync": True, "isAsync": True, "instructors": [], "description": "",
    "offeredInPerson": True, "offeredOnline": True,
    "startTime": "", "endTime": "", "days": [], "eligibleGrades": "",
    "building": [], "timeOfDay": [],
}
ALL_STATUS = ["OPEN", "WAITLIST", "FULL", "MAJORS", "PERMISSION"]


def _get(path, ttl=TTL_LOOKUP):
    key = "GET " + path
    hit = _cache_read(key, ttl)
    if hit is not None:
        return hit
    req = urllib.request.Request(BASE + path, headers={"User-Agent": USER_AGENT})
    _throttle()
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    _cache_write(key, d)
    return d


def _post(path, payload, params="", ttl=TTL_SEARCH):
    body = json.dumps(payload, sort_keys=True)
    key = "POST " + path + params + " " + body
    hit = _cache_read(key, ttl)
    if hit is not None:
        return hit
    req = urllib.request.Request(
        BASE + path + params, data=body.encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    _throttle()
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    _cache_write(key, d)
    return d


def terms():
    return _get("/data/terms")


def default_term():
    return _get("/data/terms/default")


def term_id(t):
    """Term ids the search endpoint wants are '{strm}::{CODE}', e.g. 2271::FALL."""
    return f"{t['strm']}::{t['code']}"


def subjects():
    return _get("/data/subjects")


def payload(**over):
    p = dict(DEFAULT_PAYLOAD)
    p.update(over)
    return p


def search(term, campus="ATHN", all_status=False, **filters):
    """Paginated search. Returns every matching section."""
    p = payload(terms=[term], campuses=[campus], **filters)
    if all_status:
        p["status"] = ALL_STATUS
    out, page = [], 1
    while True:
        d = _post("/search/query", p,
                  f"?selectedTab={campus}&page={page}&pageSize={PAGE_SIZE}")
        rows = d.get("results", [])
        out.extend(rows)
        total = d.get("counts", {}).get(campus, 0)
        if len(out) >= total or not rows:
            break
        page += 1
    # the API can emit duplicate rows; de-dupe on class number
    seen, uniq = set(), []
    for x in out:
        k = x.get("classNumber") or (x["subject"], x["catalogNumber"], x["section"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq


# ---------- derived fields ----------

def seats(x):
    return (x.get("maxEnrolled") or 0) - (x.get("enrolled") or 0)


def fee(x):
    return max(x.get("fee") or 0, x.get("guaranteeFee") or 0)


def pf_ok(x):
    """CR in the grade basis = section permits credit/no-credit."""
    return "CR" in (x.get("eligibleGrades") or "").split(",")


def hidden_restriction(x):
    """The `requisite` field misses restrictions that only appear in `note`."""
    note = x.get("note") or ""
    m = re.search(r"[Ff]or ([^.]{0,60}?(?:majors?|students?)\s+only)", note)
    return m.group(1).strip() if m else None


def mode(x):
    b = (x.get("building") or "").upper()
    if "ONLINE" in b:
        return "Online"
    return "In person" if (x.get("meetings") or []) else "Arranged"


def _ampm(t):
    if not t:
        return ""
    h, m = map(int, t.split(":"))
    return f"{h % 12 or 12}:{m:02d}{'a' if h < 12 else 'p'}"


def meets(x):
    parts = []
    for m in x.get("meetings") or []:
        d = "".join(m.get("days") or [])
        s, e = _ampm(m.get("startTime")), _ampm(m.get("endTime"))
        if d or s:
            parts.append(f"{d} {s}-{e}".strip())
    return "; ".join(parts) or "Arranged"


def session(x):
    """Half-semester sections are common (esp. PAW/REC). Surface the date span."""
    b, e = (x.get("beginDate") or "")[:10], (x.get("endDate") or "")[:10]
    return f"{b}..{e}" if b else ""


def blocks(x):
    """Normalized meeting blocks for conflict math."""
    out = []
    for m in x.get("meetings") or []:
        if not m.get("startTime") or not m.get("days"):
            continue
        out.append({
            "days": set(m["days"]),
            "start": m["startTime"], "end": m["endTime"],
            "from": (m.get("startDate") or x.get("beginDate") or "")[:10],
            "to": (m.get("endDate") or x.get("endDate") or "")[:10],
        })
    return out


def _mins(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m


def overlap(a, b):
    """Two blocks clash only if days AND clock times AND date ranges all intersect."""
    if not (a["days"] & b["days"]):
        return None
    if a["from"] and b["from"]:
        if dt.date.fromisoformat(a["to"]) < dt.date.fromisoformat(b["from"]):
            return None
        if dt.date.fromisoformat(b["to"]) < dt.date.fromisoformat(a["from"]):
            return None
    s = max(_mins(a["start"]), _mins(b["start"]))
    e = min(_mins(a["end"]), _mins(b["end"]))
    return (sorted(a["days"] & b["days"]), e - s) if s < e else None


def clashes(x, y):
    hits = []
    for A in blocks(x):
        for B in blocks(y):
            o = overlap(A, B)
            if o:
                hits.append(o)
    return hits


def label(x):
    return f"{x['subject']} {x['catalogNumber']}-{x['section']}"


def find_section(term, spec, campus="ATHN"):
    """spec: 'SUBJ CAT' or 'SUBJ CAT-SEC' (e.g. 'AVN 1100-100')."""
    m = re.match(r"^\s*([A-Z]+[0-9]*)\s+([0-9A-Z]+?)(?:-(\w+))?\s*$", spec.strip(), re.I)
    if not m:
        raise SystemExit(f"can't parse section spec: {spec!r}")
    subj, cat, sec = m.group(1).upper(), m.group(2).upper(), m.group(3)
    rows = search(term, campus, all_status=True, subjects=[subj], catalogNumber=cat)
    rows = [r for r in rows if r["catalogNumber"].upper() == cat]
    if sec:
        rows = [r for r in rows if r["section"] == sec]
    if not rows:
        raise SystemExit(f"no section found for {spec!r}")
    return rows[0]


# ---------- output ----------

def row_line(x, wide=False):
    r = (f"{label(x):18} | {x['title'][:44]:44} | "
         f"{x['minCreditHours']:g}cr | {meets(x):26} | "
         f"{(x.get('primaryInstructor') or {}).get('displayName') or 'TBA':20} | "
         f"{seats(x):4} {x['status']:9}")
    if wide:
        flags = []
        if fee(x):
            flags.append(f"${fee(x):g}")
        if pf_ok(x):
            flags.append("P/F")
        if x.get("permissionRequired"):
            flags.append("PERM")
        hr = hidden_restriction(x)
        if hr:
            flags.append(hr.upper())
        if x.get("requisite"):
            flags.append("req:" + x["requisite"][:40])
        r += " | " + (", ".join(flags) or "-")
    return r


def detail(x):
    print("=" * 72)
    print(f"{label(x)}  {x['title']}" + (f"  [{x['topic']}]" if x.get("topic") else ""))
    print(f"  credits    : {x['minCreditHours']:g}-{x['maxCreditHours']:g}   component: {x.get('component')}")
    print(f"  meets      : {meets(x)}   @ {x.get('building')}")
    print(f"  session    : {session(x)}")
    print(f"  instructor : {(x.get('primaryInstructor') or {}).get('displayName')}")
    print(f"  seats      : {seats(x)} open  ({x.get('enrolled')}/{x.get('maxEnrolled')})  status={x['status']}")
    print(f"  mode       : {mode(x)}")
    print(f"  grades     : {x.get('eligibleGrades')}   ->  pass/fail eligible: {pf_ok(x)}")
    print(f"  fee        : ${fee(x):g}")
    print(f"  requisite  : {x.get('requisite')}")
    print(f"  permission : {x.get('permissionRequired')}")
    hr = hidden_restriction(x)
    if hr:
        print(f"  !! NOTE-ONLY RESTRICTION: {hr}")
    print(f"  bricks     : {x.get('bricks')}")
    print(f"  deadlines  : add {(x.get('lastDayToAdd') or '')[:10]}  drop {(x.get('lastDayToDrop') or '')[:10]}  withdraw {(x.get('lastDayToWithdraw') or '')[:10]}")
    d = re.sub(r"\s+", " ", x.get("description") or "")
    print(f"  description: {d[:500]}")
    res = x.get("resources") or []
    req_books = [r for r in res if r.get("required") and r.get("title")]
    if req_books:
        print("  materials  :")
        for r in req_books:
            print(f"     - {r.get('title')}  ${r.get('price')}")
    elif not res:
        print("  materials  : none listed")


# ---------- cli ----------

def main():
    ap = argparse.ArgumentParser(description="Ohio University course search")
    ap.add_argument("--no-cache", action="store_true",
                    help="bypass the local response cache (seat counts move daily)")
    ap.add_argument("--clear-cache", action="store_true",
                    help="delete cached responses, then run")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("terms", help="list term ids")
    sp = sub.add_parser("subjects", help="list subject codes")
    sp.add_argument("pattern", nargs="?", help="filter substring")

    sq = sub.add_parser("search", help="search sections")
    sq.add_argument("--term", help="term id like 2271::FALL (default: current)")
    sq.add_argument("--campus", default="ATHN")
    sq.add_argument("--subject", action="append", default=[])
    sq.add_argument("--catalog", default="")
    sq.add_argument("--name", default="", help="keyword match on course title")
    sq.add_argument("--credits", type=int, help="exact credit hours")
    sq.add_argument("--all-status", action="store_true", help="include FULL/closed")
    sq.add_argument("--open-only", action="store_true", help="seats > 0")
    sq.add_argument("--no-prereq", action="store_true", help="drop course/major-gated rows")
    sq.add_argument("--max-level", type=int, help="e.g. 4000 keeps <4000")
    sq.add_argument("--pf", action="store_true", help="only pass/fail eligible")
    sq.add_argument("--wide", action="store_true", help="show fees/flags/prereqs")
    sq.add_argument("--json", help="dump raw results to file")

    sd = sub.add_parser("show", help="full detail for a section")
    sd.add_argument("spec", help="'AVN 1100' or 'AVN 1100-100'")
    sd.add_argument("--term")
    sd.add_argument("--campus", default="ATHN")

    sc = sub.add_parser("conflicts", help="check candidates against enrolled sections")
    sc.add_argument("--enrolled", required=True, help="comma list, e.g. 'CS 4560-101,EE 4673-103'")
    sc.add_argument("--candidate", action="append", default=[], help="repeatable")
    sc.add_argument("--term")
    sc.add_argument("--campus", default="ATHN")

    a = ap.parse_args()

    global CACHE_ENABLED
    if a.clear_cache:
        for f in CACHE_DIR.glob("*.json"):
            try:
                f.unlink()
            except OSError:
                pass
    if a.no_cache:
        CACHE_ENABLED = False
    if CONTACT.startswith("https://example.invalid"):
        print("note: set OU_COURSE_SEARCH_CONTACT so requests identify a contact",
              file=sys.stderr)

    if a.cmd == "terms":
        for t in terms():
            print(f"{term_id(t):16} {t['description']}")
        print(f"\ndefault: {term_id(default_term())}")
        return

    if a.cmd == "subjects":
        for s in subjects():
            line = f"{s['subject']:6} {s.get('subjectLongName')}"
            if not a.pattern or a.pattern.lower() in line.lower():
                print(line)
        return

    term = getattr(a, "term", None) or term_id(default_term())

    if a.cmd == "show":
        detail(find_section(term, a.spec, a.campus))
        return

    if a.cmd == "conflicts":
        enrolled = [find_section(term, s, a.campus) for s in a.enrolled.split(",")]
        print(f"term {term}\n")
        print("=== conflicts inside current schedule ===")
        found = False
        for i in range(len(enrolled)):
            for j in range(i + 1, len(enrolled)):
                for days, mins in clashes(enrolled[i], enrolled[j]):
                    found = True
                    print(f"  !! {label(enrolled[i])} X {label(enrolled[j])}"
                          f" -> {','.join(days)} overlap {mins}min")
        if not found:
            print("  none")
        total = sum(x["minCreditHours"] for x in enrolled)
        print(f"\nenrolled credits: {total:g}")
        if a.candidate:
            print("\n=== candidates ===")
            for spec in a.candidate:
                c = find_section(term, spec, a.campus)
                hits = [(label(o), h) for o in enrolled for h in clashes(c, o)]
                if hits:
                    print(f"  [CONFLICT] {label(c):18} {c['minCreditHours']:g}cr  <- " +
                          "; ".join(f"{n} ({','.join(d)} {m}min)" for n, (d, m) in hits))
                else:
                    print(f"  [CLEAR   ] {label(c):18} {c['minCreditHours']:g}cr  "
                          f"seats={seats(c)}  {meets(c)}")
        return

    # search
    f = {}
    if a.subject:
        f["subjects"] = a.subject
    if a.catalog:
        f["catalogNumber"] = a.catalog
    if a.name:
        f["name"] = a.name
    if a.credits:
        f["minCreditHours"] = a.credits
        f["maxCreditHours"] = a.credits
    rows = search(term, a.campus, all_status=a.all_status, **f)

    if a.open_only:
        rows = [x for x in rows if seats(x) > 0]
    if a.pf:
        rows = [x for x in rows if pf_ok(x)]
    if a.max_level:
        rows = [x for x in rows if x["catalogNumber"][:1].isdigit()
                and int(x["catalogNumber"][:4]) < a.max_level]
    if a.no_prereq:
        bad = re.compile(r"major|minor|COB|permission|audition|admission|"
                         r"advanced standing|BS\d|AA\d|BF\d|HTC", re.I)
        rows = [x for x in rows
                if not bad.search(x.get("requisite") or "")
                and not re.search(r"\b[A-Z]{2,4}\s?\d{4}\b", x.get("requisite") or "")
                and not hidden_restriction(x)]

    rows.sort(key=lambda x: (x["subject"], x["catalogNumber"], x["section"]))
    for x in rows:
        print(row_line(x, a.wide))
    print(f"\n{len(rows)} sections  (term {term}, campus {a.campus})", file=sys.stderr)
    if a.json:
        json.dump(rows, open(a.json, "w"))
        print(f"raw -> {a.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
