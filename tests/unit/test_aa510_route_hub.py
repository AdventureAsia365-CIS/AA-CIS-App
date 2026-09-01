"""AA-510: Route detection (derive_routes/_runs/_spans), Hub family detection (families),
Subject snapshot presentation (stops/journey_name). Pure-function tests only — no DB, no HTTP."""

from services.acp_contract.route_detection import (
    LEAST_DAYS,
    LEAST_PLACES,
    MOST_DAYS,
    SHARED_ENOUGH,
    Moment,
    derive_routes,
    families,
    journey_name,
    stops,
)

TENANT = "11111111-1111-1111-1111-111111111111"


def _m(segment_id, tour_id, day, place, score=1):
    return Moment(segment_id=segment_id, tour_id=tour_id, day=day, place=place, score=score)


# ── derive_routes / _runs / _spans ──────────────────────────────────────────────────────────


def test_derive_routes_basic_consecutive_days_two_places():
    moments = [
        _m("s1", "t1", 1, "Kyoto", score=2),
        _m("s2", "t1", 2, "Magome", score=4),
    ]
    routes = derive_routes(TENANT, moments)
    assert len(routes) == 1
    r = routes[0]
    assert r.tour_id == "t1"
    assert r.first_day == 1 and r.last_day == 2
    assert r.places == ("Kyoto", "Magome")
    assert r.segment_ids == ("s1", "s2")
    assert r.score == 3  # mean(2, 4) rounded


def test_derive_routes_route_id_is_deterministic_composite_not_hash_or_uuid():
    moments = [_m("s1", "t1", 1, "Kyoto"), _m("s2", "t1", 2, "Magome")]
    routes = derive_routes(TENANT, moments)
    assert routes[0].route_id == f"{TENANT}:t1:1-2"


def test_derive_routes_gap_breaks_the_run():
    # day 1-2 then a gap (day 3 has nothing ranked, the transfer) then day 5-6.
    moments = [
        _m("s1", "t1", 1, "Kyoto"), _m("s2", "t1", 2, "Magome"),
        _m("s3", "t1", 5, "Tsumago"), _m("s4", "t1", 6, "Matsumoto"),
    ]
    routes = derive_routes(TENANT, moments)
    assert len(routes) == 2
    assert (routes[0].first_day, routes[0].last_day) in {(1, 2), (5, 6)}
    spans = {(r.first_day, r.last_day) for r in routes}
    assert spans == {(1, 2), (5, 6)}


def test_derive_routes_drops_single_day_span():
    moments = [_m("s1", "t1", 1, "Kyoto")]
    assert derive_routes(TENANT, moments) == []


def test_derive_routes_drops_single_place_span():
    # 2 consecutive days but only 1 distinct place -- a stay, not a journey.
    moments = [_m("s1", "t1", 1, "Kyoto"), _m("s2", "t1", 2, "Kyoto")]
    assert derive_routes(TENANT, moments) == []


def test_derive_routes_least_days_and_places_constants():
    assert LEAST_DAYS == 2
    assert LEAST_PLACES == 2


def test_derive_routes_long_run_cut_into_most_days_spans():
    # 7 consecutive days, MOST_DAYS=5 -- first span days 1-5, remainder (6-7) is < LEAST_DAYS
    # on its own so it must fold into the previous span, not become a dropped 2-day span... 6-7
    # IS exactly LEAST_DAYS=2, so it stays its own span here; use 8 days to force a genuine
    # trailing short (1-day) span that must fold.
    moments = [_m(f"s{d}", "t1", d, f"Place{d}") for d in range(1, 9)]  # days 1..8
    routes = derive_routes(TENANT, moments)
    spans = sorted((r.first_day, r.last_day) for r in routes)
    # cuts: [1..5], [6,7,8] (len 3 -- not < LEAST_DAYS=2, stays separate)
    assert spans == [(1, 5), (6, 8)]


def test_derive_routes_trailing_single_day_span_folds_into_previous():
    # 6 consecutive days -- cuts would be [1..5], [6] (len 1 < LEAST_DAYS) -> folds into [1..6].
    moments = [_m(f"s{d}", "t1", d, f"Place{d}") for d in range(1, 7)]
    routes = derive_routes(TENANT, moments)
    assert len(routes) == 1
    assert (routes[0].first_day, routes[0].last_day) == (1, 6)


def test_derive_routes_sorted_ascending_by_score_lowest_first():
    moments = [
        _m("s1", "weak", 1, "A", score=9), _m("s2", "weak", 2, "B", score=9),
        _m("s3", "strong", 1, "A", score=1), _m("s4", "strong", 2, "B", score=1),
    ]
    routes = derive_routes(TENANT, moments)
    assert [r.tour_id for r in routes] == ["strong", "weak"]


def test_derive_routes_groups_independently_per_tour():
    moments = [
        _m("s1", "t1", 1, "Kyoto"), _m("s2", "t1", 2, "Magome"),
        _m("s3", "t2", 1, "Sapporo"), _m("s4", "t2", 2, "Otaru"),
    ]
    routes = derive_routes(TENANT, moments)
    assert {r.tour_id for r in routes} == {"t1", "t2"}


# ── families (Hub grouping) ──────────────────────────────────────────────────────────────────


def test_families_groups_tours_sharing_enough_segments():
    tours = {
        "tour-a": {"seg1", "seg2", "seg3"},
        "tour-b": {"seg1", "seg2"},  # shares 2/2 with tour-b's own smaller set -> Jaccard 1.0
        "tour-c": {"seg9"},  # shares nothing
    }
    result = families(tours)
    assert result["tour-a"] == "tour-a"
    assert result["tour-b"] == "tour-a"
    assert "tour-c" not in result  # a family of one is not a family


def test_families_ratio_is_over_the_smaller_set():
    # tour-big shares 1 of its 10 segments with tour-small's only segment -- ratio over the
    # SMALLER set (tour-small, size 1) is 1/1 = 1.0, clears SHARED_ENOUGH even though tour-big's
    # own overlap fraction (1/10) would not.
    tours = {
        "tour-big": {f"seg{i}" for i in range(10)} | {"shared"},
        "tour-small": {"shared"},
    }
    result = families(tours)
    assert result["tour-big"] == result["tour-small"]


def test_families_below_threshold_stays_separate():
    tours = {"tour-a": {"s1", "s2", "s3", "s4"}, "tour-b": {"s1", "s9"}}
    # overlap 1, smaller=2 -> ratio 0.5... use a genuinely low-overlap pair instead.
    tours = {"tour-a": {"s1", "s2", "s3"}, "tour-b": {"s4", "s5", "s6", "s1"}}
    # overlap=1, smaller=3 -> ratio 0.33 > 0.3 SHARED_ENOUGH -- pick something clearly under.
    tours = {"tour-a": {"s1", "s2", "s3", "s4"}, "tour-b": {"s5", "s6", "s7", "s1"}}
    # overlap=1, smaller=4 -> 0.25 < 0.3
    result = families(tours)
    assert "tour-a" not in result and "tour-b" not in result


def test_families_named_after_alphabetically_smallest_member():
    tours = {"zeta-tour": {"s1"}, "alpha-tour": {"s1"}}
    result = families(tours)
    assert result["zeta-tour"] == "alpha-tour"
    assert result["alpha-tour"] == "alpha-tour"


def test_families_transitive_union_find():
    # a~b (share s1), b~c (share s2) but a and c share nothing directly -- still one family.
    tours = {
        "a": {"s1"}, "b": {"s1", "s2"}, "c": {"s2"},
    }
    result = families(tours)
    assert result["a"] == result["b"] == result["c"]


def test_shared_enough_is_030():
    assert SHARED_ENOUGH == 0.3


# ── stops (Subject snapshot presentation) ───────────────────────────────────────────────────


def test_stops_dedups_same_day_same_place_multiple_actions():
    steps = [(2, "Itsukushima Shrine", "visit"), (2, "Itsukushima Shrine", "see the torii")]
    result = stops(steps)
    assert len(result) == 1
    assert result[0].actions == ("visit", "see the torii")
    assert result[0].said == "visit and see the torii"


def test_stops_revisit_on_a_later_day_is_a_second_stop():
    steps = [(1, "Kyoto", "arrive"), (5, "Kyoto", "return")]
    result = stops(steps)
    assert len(result) == 2
    assert [s.day for s in result] == [1, 5]


def test_stops_preserves_given_order():
    steps = [(3, "C", ""), (1, "A", ""), (2, "B", "")]
    result = stops(steps)
    assert [s.place for s in result] == ["C", "A", "B"]


def test_stop_str_with_no_actions_omits_dash():
    steps = [(1, "Kyoto", "")]
    result = stops(steps)
    assert str(result[0]) == "day 1 Kyoto"


# ── journey_name (Hub/Route naming placeholder) ─────────────────────────────────────────────


def test_journey_name_joins_places_with_arrow():
    assert journey_name(["Kyoto", "Magome", "Tsumago"]) == "Kyoto → Magome → Tsumago"


def test_journey_name_dedups_and_caps_at_limit():
    places = ["Kyoto", "Kyoto", "Magome", "Tsumago", "Matsumoto", "Nagano"]
    result = journey_name(places, limit=4)
    assert result == "Kyoto → Magome → Tsumago → Matsumoto"


def test_journey_name_empty_is_a_placeholder():
    assert journey_name([]) == "Untitled journey"
