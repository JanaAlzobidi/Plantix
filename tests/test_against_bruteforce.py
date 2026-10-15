"""Independent check of the engine against an exhaustive search.

Nothing here imports the engine's internals: the rules and the objective are
re-implemented straight from the EXPOWISE spec, then every possible schedule
of a small random instance is enumerated to find the true best one. The
engine must (1) never break a hard rule, (2) reach exactly the best
objective, and (3) give a reason of the right kind for every event it leaves
out.
"""

import random
from datetime import date, time, timedelta

import pandas as pd
import pytest

from engine import PRIORITY_LEVELS, EngineConfig, generate_schedule
from engine.data import PROGRAM_COLUMNS, VENUE_COLUMNS

SLOT = 15
EQUIPMENT = ["projector", "microphone", "computers"]
NO_OPTION_CODES = {
    "CAPACITY", "EQUIPMENT", "CAPACITY_AND_EQUIPMENT", "VENUE_UNAVAILABLE",
    "FREEZE_WINDOW", "NO_TIME_SLOT", "BLOCKED_BY_FIXED", "NO_VENUES",
}


def hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def mins(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


# ------------------------------------------------------------------ random instances

def random_instance(rng: random.Random):
    inst = crowded_instance(rng) if rng.random() < 0.5 else plain_instance(rng)
    return add_client_rules(inst, rng)


def add_client_rules(inst, rng: random.Random):
    """Client-specific rule: a priority order."""
    order = list(PRIORITY_LEVELS)
    if rng.random() < 0.4:
        rng.shuffle(order)
    inst["priorities"] = tuple(order)
    return inst


def plain_instance(rng: random.Random):
    n_days = rng.choice([1, 1, 2])
    days = [date(2026, 10, 17) + timedelta(days=i) for i in range(n_days)]
    open_m = 9 * 60
    close_m = open_m + rng.choice([120, 135, 150, 180])

    venues = []
    for j in range(rng.choice([1, 2, 2, 3])):
        venues.append({
            "id": f"V{j}",
            "cap": rng.choice([20, 40, 80, 150]),
            "eq": set(rng.sample(EQUIPMENT, rng.randint(0, 3))),
            "setup": rng.choice([0, 0, 15, 20, 30]),
            "available": rng.random() > 0.15,
        })

    programs = []
    fixed_count = rng.choice([0, 0, 1, 2])
    flex_count = (rng.choice([3, 4]) if n_days == 1 else 3) + (1 if len(venues) == 1 else 0)

    for i in range(fixed_count):
        v = rng.choice(venues)
        duration = rng.choice([30, 45, 60])
        start = open_m + rng.randrange(0, close_m - open_m - duration + 1, 5)
        programs.append({
            "id": f"F{i}", "fixed": True, "dur": duration,
            "att": rng.randint(1, v["cap"]), "req": set(rng.sample(sorted(v["eq"]), rng.randint(0, len(v["eq"])))),
            "day": rng.choice(days), "start": start, "venue": v["id"],
            "pdays": set(), "pslots": [],
        })

    for i in range(flex_count):
        pdays = set(rng.sample(days, rng.randint(0, len(days)))) if rng.random() < 0.6 else set()
        pslots = []
        if rng.random() < 0.5:
            a = open_m + rng.choice([0, 30, 60])
            pslots.append((a, a + rng.choice([45, 60, 90])))
        programs.append({
            "id": f"P{i}", "fixed": False, "dur": rng.choice([30, 45, 60, 90]),
            "att": rng.choice([10, 30, 60, 120, 200]),
            "req": set(rng.sample(EQUIPMENT, rng.randint(0, 2))),
            "pdays": pdays, "pslots": pslots,
        })

    approved = {}
    for p in programs:
        if p["fixed"]:
            if rng.random() < 0.3:
                approved[p["id"]] = (p["day"], p["start"], p["venue"])
        elif rng.random() < 0.5:
            approved[p["id"]] = (
                rng.choice(days),
                open_m + SLOT * rng.randint(0, (close_m - open_m - 30) // SLOT),
                rng.choice(venues)["id"],
            )

    reference = date(2026, 10, 17) + timedelta(days=rng.choice([-2, -1, 0]))
    freeze = rng.choice([0, 0, 1, 2, 3])
    return {
        "days": days, "open": open_m, "close": close_m, "venues": venues,
        "programs": programs, "approved": approved, "ref": reference, "freeze": freeze,
    }


def crowded_instance(rng: random.Random):
    """Every event fits the rooms; they compete for too little time, with
    approved slots, preferences and room sizes pulling in different directions."""
    n_days = rng.choice([1, 1, 2])
    days = [date(2026, 10, 17) + timedelta(days=i) for i in range(n_days)]
    open_m = 9 * 60
    close_m = open_m + rng.choice([120, 150])
    venues = [{
        "id": f"V{j}", "cap": cap, "eq": {"projector"},
        "setup": rng.choice([0, 15, 30]), "available": True,
    } for j, cap in enumerate(rng.sample([30, 60, 120], rng.choice([1, 2])))]
    small = min(v["cap"] for v in venues)

    n_flex = {(1, 1): 5, (1, 2): 4, (2, 1): 4, (2, 2): 3}[(n_days, len(venues))]
    programs = []
    if rng.random() < 0.4:
        v = rng.choice(venues)
        programs.append({
            "id": "F0", "fixed": True, "dur": 30, "att": rng.randint(1, small), "req": set(),
            "day": rng.choice(days), "start": open_m + rng.choice([0, 30, 60]), "venue": v["id"],
            "pdays": set(), "pslots": [],
        })
    for i in range(n_flex):
        a = open_m + rng.choice([0, 30, 60])
        programs.append({
            "id": f"P{i}", "fixed": False, "dur": rng.choice([45, 60, 90]),
            "att": rng.randint(1, small), "req": {"projector"} if rng.random() < 0.5 else set(),
            "pdays": {rng.choice(days)} if rng.random() < 0.7 else set(),
            "pslots": [(a, a + rng.choice([60, 90]))] if rng.random() < 0.6 else [],
        })

    approved = {}
    for p in programs:
        if not p["fixed"] and rng.random() < 0.5:
            approved[p["id"]] = (
                rng.choice(days), open_m + SLOT * rng.randint(0, 4), rng.choice(venues)["id"],
            )
    return {
        "days": days, "open": open_m, "close": close_m, "venues": venues, "programs": programs,
        "approved": approved, "ref": date(2026, 10, 17) + timedelta(days=rng.choice([-2, -1, 0])),
        "freeze": rng.choice([0, 0, 1, 2]),
    }


def to_frames(inst):
    prog_rows = []
    for p in inst["programs"]:
        prog_rows.append({
            "program_id": p["id"], "program_name": f"Name {p['id']}",
            "duration_min": str(p["dur"]), "attendance_value": str(p["att"]),
            "venue_requirements": ";".join(sorted(p["req"])),
            "time_type": "fixed" if p["fixed"] else "flexible",
            "fixed_date": p["day"].isoformat() if p["fixed"] else "",
            "fixed_start_time": hm(p["start"]) if p["fixed"] else "",
            "fixed_venue_id": p["venue"] if p["fixed"] else "",
            "preferred_dates": ";".join(sorted(d.isoformat() for d in p["pdays"])),
            "preferred_time_slots": ";".join(f"{hm(a)}-{hm(b)}" for a, b in p["pslots"]),
        })
    venue_rows = [{
        "venue_id": v["id"], "venue_name": f"Hall {v['id']}", "capacity": str(v["cap"]),
        "equipment": ";".join(sorted(v["eq"])), "min_setup_time_min": str(v["setup"]),
        "status": "available" if v["available"] else "maintenance",
    } for v in inst["venues"]]
    approved_rows = [{
        "program_id": pid, "date": d.isoformat(), "start_time": hm(s), "venue_id": vid,
    } for pid, (d, s, vid) in inst["approved"].items()]
    return (
        pd.DataFrame(prog_rows, columns=PROGRAM_COLUMNS),
        pd.DataFrame(venue_rows, columns=VENUE_COLUMNS),
        pd.DataFrame(approved_rows, columns=["program_id", "date", "start_time", "venue_id"]),
    )


def config_for(inst):
    return EngineConfig(
        start_date=inst["days"][0], end_date=inst["days"][-1],
        day_start=time(inst["open"] // 60, inst["open"] % 60),
        day_end=time(inst["close"] // 60, inst["close"] % 60),
        priorities=inst.get("priorities", PRIORITY_LEVELS),
        solver_time_limit_seconds=30,
    )


# ------------------------------------------------------------------ the spec, re-implemented

def frozen(day, inst):
    return inst["freeze"] > 0 and 0 <= (day - inst["ref"]).days <= inst["freeze"]


def fits_venue(p, v):
    return v["available"] and v["cap"] >= p["att"] and p["req"] <= v["eq"]


def busy_interval(p, start, v):
    return start, start + p["dur"] + v["setup"]


def fixed_is_valid(inst):
    """Spec 2a: a fixed event must fit its venue and hours; fixed events may not
    clash in a room (setup included)."""
    venues = {v["id"]: v for v in inst["venues"]}
    spans = []
    for p in inst["programs"]:
        if not p["fixed"]:
            continue
        v = venues[p["venue"]]
        end = p["start"] + p["dur"]
        if not fits_venue(p, v) or p["start"] < inst["open"] or end > inst["close"]:
            return False
        spans.append((p["venue"], p["day"], *busy_interval(p, p["start"], v)))
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            if a[0] == b[0] and a[1] == b[1] and a[2] < b[3] and b[2] < a[3]:
                return False
    return True


def options_for(p, inst):
    venues = inst["venues"]
    days = inst["days"]
    if p["id"] not in inst["approved"]:
        days = [d for d in days if not frozen(d, inst)]
    out = []
    for d in days:
        for s in range(inst["open"], inst["close"] - p["dur"] + 1, SLOT):
            for v in venues:
                if fits_venue(p, v):
                    out.append((d, s, v["id"]))
    return out


def score(p, choice, inst):
    """Contribution of one flexible event, ordered by the client's priorities."""
    keep, count, stable, pref, fit = raw_score(p, choice, inst)
    by_level = {"keep_approved": keep, "schedule_count": count, "stability": stable,
                "preferences": pref, "room_fit": fit}
    return tuple(by_level[name] for name in inst.get("priorities", PRIORITY_LEVELS))


def raw_score(p, choice, inst):
    if choice is None:
        return (0, 0, 0, 0, 0)
    d, s, vid = choice
    v = next(x for x in inst["venues"] if x["id"] == vid)
    old = inst["approved"].get(p["id"])
    keep = 1 if old else 0
    stable = 0
    if old:
        od, os_, ov = old
        base = 0 if d != od else (1 if s != os_ else (2 if vid != ov else 3))
        stable = base * (2 if frozen(od, inst) else 1)
    pref = (2 if d in p["pdays"] else 0) + (1 if any(a <= s and s + p["dur"] <= b for a, b in p["pslots"]) else 0)
    fit = round(10 * p["att"] / v["cap"])
    return (keep, 1, stable, pref, fit)


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def occupied_by_fixed(inst):
    """Room spans (setup included) of fixed events."""
    venues = {v["id"]: v for v in inst["venues"]}
    rooms = []
    for p in inst["programs"]:
        if p["fixed"]:
            rooms.append((p["venue"], p["day"], *busy_interval(p, p["start"], venues[p["venue"]])))
    return rooms


def overlaps_any(key, d, a, b, spans):
    return any(k == key and dd == d and a < y and x < b for k, dd, x, y in spans)


def best_objective(inst):
    venues = {v["id"]: v for v in inst["venues"]}
    rooms = occupied_by_fixed(inst)
    flex = [p for p in inst["programs"] if not p["fixed"]]
    opts = [options_for(p, inst) for p in flex]
    best = [None]

    def dfs(i, total):
        if i == len(flex):
            if best[0] is None or total > best[0]:
                best[0] = total
            return
        p = flex[i]
        dfs(i + 1, total)
        for d, s, vid in opts[i]:
            a, b = busy_interval(p, s, venues[vid])
            if overlaps_any(vid, d, a, b, rooms):
                continue
            rooms.append((vid, d, a, b))
            dfs(i + 1, add(total, score(p, (d, s, vid), inst)))
            rooms.pop()

    dfs(0, tuple(0 for _ in PRIORITY_LEVELS))
    return best[0]


def check_engine_schedule(inst, result):
    """Hard rules (spec 4) checked on the engine's output, plus its objective."""
    venues = {v["id"]: v for v in inst["venues"]}
    programs = {p["id"]: p for p in inst["programs"]}
    placed = {}
    for row in result.schedule.itertuples():
        placed[row.program_id] = (date.fromisoformat(row.date), mins(row.start_time), row.venue_id)

    spans = []
    total = tuple(0 for _ in PRIORITY_LEVELS)
    for pid, (d, s, vid) in placed.items():
        p, v = programs[pid], venues[vid]
        assert fits_venue(p, v), f"{pid} placed in an unsuitable venue {vid}"
        assert inst["open"] <= s and s + p["dur"] <= inst["close"], f"{pid} outside operating hours"
        assert d in inst["days"], f"{pid} outside the horizon"
        if p["fixed"]:
            assert (d, s, vid) == (p["day"], p["start"], p["venue"]), f"fixed {pid} was moved"
        else:
            assert (s - inst["open"]) % SLOT == 0
            if pid not in inst["approved"]:
                assert not frozen(d, inst), f"new flexible {pid} placed in the freeze window"
            total = add(total, score(p, (d, s, vid), inst))
        spans.append((vid, d, *busy_interval(p, s, v), pid))

    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            assert not (a[0] == b[0] and a[1] == b[1] and a[2] < b[3] and b[2] < a[3]), \
                f"{a[4]} and {b[4]} overlap in {a[0]} (setup included)"

    for p in inst["programs"]:
        if p["fixed"]:
            assert p["id"] in placed, f"fixed {p['id']} missing"
    return placed, total


# ------------------------------------------------------------------ the tests

SEEDS = range(400)


@pytest.mark.parametrize("seed", SEEDS)
def test_engine_matches_exhaustive_search(seed):
    rng = random.Random(seed)
    inst = random_instance(rng)
    programs, venues, approved = to_frames(inst)
    result = generate_schedule(
        programs, venues, approved,
        reference_date=inst["ref"].isoformat(), freeze_window_days=inst["freeze"],
        config=config_for(inst),
    )

    if not fixed_is_valid(inst):
        assert result.status == "INVALID_DATA", "invalid fixed events were accepted"
        return
    assert result.status == "OPTIMAL", f"status {result.status}: {list(result.issues['message'])}"

    placed, engine_total = check_engine_schedule(inst, result)
    assert engine_total == best_objective(inst), (
        f"engine objective {engine_total} != best possible {best_objective(inst)}"
    )

    reasons = dict(zip(result.unscheduled["program_id"], result.unscheduled["reason_code"]))
    assert set(reasons) == {p["id"] for p in inst["programs"]} - set(placed)
    venues_by_id = {v["id"]: v for v in inst["venues"]}
    fixed_rooms = occupied_by_fixed(inst)
    for p in inst["programs"]:
        if p["id"] not in reasons:
            continue
        free = [
            o for o in options_for(p, inst)
            if not overlaps_any(o[2], o[0], *busy_interval(p, o[1], venues_by_id[o[2]]), fixed_rooms)
        ]
        if free:
            assert reasons[p["id"]] == "CONFLICTS", f"{p['id']}: has free options but reason {reasons[p['id']]}"
        else:
            assert reasons[p["id"]] in NO_OPTION_CODES, f"{p['id']}: no options but reason {reasons[p['id']]}"


@pytest.mark.parametrize("seed", range(5))
def test_same_input_gives_the_same_schedule(seed):
    inst = random_instance(random.Random(1000 + seed))
    frames = to_frames(inst)
    kwargs = dict(reference_date=inst["ref"].isoformat(), freeze_window_days=inst["freeze"], config=config_for(inst))
    first = generate_schedule(*frames, **kwargs)
    second = generate_schedule(*frames, **kwargs)
    pd.testing.assert_frame_equal(first.schedule, second.schedule)
