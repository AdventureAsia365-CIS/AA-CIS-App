"""AA-330 Phần B — services/acp_shared/marketplace_estimates.py.

runway_months() and parse_price() are pure functions (no DB, no mocks needed).
Test data for parse_price() is taken verbatim from the real price_raw samples
surveyed live against aa-cis-dev-db in AA-330 Phần B STEP 0 (08/08/2026),
one test per distinct shape found — not invented strings.
"""
from services.acp_shared.marketplace_estimates import (FX_RATES_TO_USD,
                                                        MIN_PLAUSIBLE_PRICE_USD,
                                                        parse_price,
                                                        runway_months)


class TestRunwayMonths:
    """Must match the issue's own example table exactly. If a case here does
    NOT match, the test should fail loudly — never adjust the formula to
    force a match (explicit instruction, AA-330 Phần B build task)."""

    def test_12_tour_87_atom_3_per_week_is_7_months(self):
        assert runway_months(87, 3) == 7

    def test_25_tour_180_atom_5_per_week_is_9_months(self):
        assert runway_months(180, 5) == 9

    def test_50_tour_360_atom_7_per_week_is_12_months(self):
        assert runway_months(360, 7) == 12  # issue says "12+" — floor is 12

    def test_5_tour_35_atom_2_per_week_is_4_months(self):
        """Issue's row says '1-2 bài/tuần' -> '~4 tháng' — only matches the
        upper end of that range (2/week); 1/week gives 8, not 4. Documented
        in the Linear STEP 0 comment (08/08/2026), not silently glossed over."""
        assert runway_months(35, 2) == 4

    def test_zero_posts_per_week_returns_none(self):
        assert runway_months(87, 0) is None

    def test_negative_posts_per_week_returns_none(self):
        assert runway_months(87, -1) is None

    def test_zero_atoms_is_zero_months_not_none(self):
        assert runway_months(0, 3) == 0


class TestParsePrice:
    def test_empty_and_none_return_none(self):
        assert parse_price(None) is None
        assert parse_price("") is None
        assert parse_price("   ") is None

    def test_from_dollar_with_no_number_returns_none(self):
        """23/534 non-null price_raw rows in the real dataset are literally
        'From $' with nothing after it — broken/incomplete source data."""
        assert parse_price("From $") is None

    def test_on_request_returns_none(self):
        assert parse_price("On request") is None

    def test_bare_unlabeled_number_returns_none(self):
        """No currency marker at all — STEP 0 flagged these as ambiguous/
        possibly data-entry errors, not safe to assume USD."""
        assert parse_price("89") is None
        assert parse_price("565") is None
        assert parse_price("4348") is None

    def test_simple_us_dollar_prefix(self):
        assert parse_price("US$2,590") == 2590.0

    def test_simple_bare_dollar(self):
        assert parse_price("$350") == 350.0

    def test_dollar_glued_to_following_text(self):
        assert parse_price("$1000Per Person") == 1000.0

    def test_number_then_usd_suffix(self):
        assert parse_price("3999.00 USD") == 3999.0

    def test_from_prefix_with_redundant_usd_suffix(self):
        assert parse_price("From $637 USD") == 637.0

    def test_gbp_symbol(self):
        rate = FX_RATES_TO_USD["GBP"]
        assert parse_price("£2699") == round(2699 * rate, 2)

    def test_inr_code_with_per_person_suffix(self):
        rate = FX_RATES_TO_USD["INR"]
        assert parse_price("INR 1,850 per person") == round(1850 * rate, 2)

    def test_jpy_half_width_yen_symbol(self):
        rate = FX_RATES_TO_USD["JPY"]
        assert parse_price("From¥35,000") == round(35000 * rate, 2)

    def test_jpy_full_width_yen_symbol(self):
        """U+FFE5 fullwidth yen sign — distinct code point from U+00A5,
        confirmed present in the real dataset (2 rows) during STEP 0."""
        rate = FX_RATES_TO_USD["JPY"]
        assert parse_price("From￥35,000") == round(35000 * rate, 2)

    def test_jpy_word_yen_suffix(self):
        rate = FX_RATES_TO_USD["JPY"]
        assert parse_price("10,000 yen *") == round(10000 * rate, 2)

    def test_krw_symbol_prefix_and_code_suffix_glued(self):
        rate = FX_RATES_TO_USD["KRW"]
        assert parse_price("₩1,450,000KRW") == round(1450000 * rate, 2)

    def test_dollar_prefix_with_explicit_conflicting_code_prefers_explicit_code(self):
        """Real sample '$23,300 TWD' — bare $ AND an explicit TWD code both
        present. The explicit code wins (D: strong marker beats bare symbol)."""
        rate = FX_RATES_TO_USD["TWD"]
        assert parse_price("$23,300 TWD") == round(23300 * rate, 2)

    def test_tiered_by_group_size_takes_lowest_tier_not_supplement(self):
        """D4: real sample with a Single Occupation supplement ($54) LOWER
        than every real tier — must NOT be picked as 'the price'. Lowest
        genuine tier ($244, the 10+ traveller rate) is correct."""
        text = ("2-5 Traveller : $492\n6-9 Traveller : $292\n"
                "10 + Traveller : $244\nSingle Occupation: $54")
        assert parse_price(text) == 244.0

    def test_tiered_by_group_size_simple(self):
        text = "2-5 Traveller : $182\n6-9 Traveller : $115\n10 + Traveller : $86"
        assert parse_price(text) == 86.0

    def test_adult_child_takes_lower_child_price(self):
        rate = FX_RATES_TO_USD["JPY"]
        text = ("Adults (13 and older):15,000 Japanese Yen\n"
                "Children (12 and under):8,000 Japanese Yen")
        assert parse_price(text) == round(8000 * rate, 2)

    def test_from_price_ignores_trailing_per_day_rate(self):
        """'$79 per day' is a different unit, not a cheaper total price —
        must not be picked over the real $630 total."""
        assert parse_price("From $630\n$79 per day") == 630.0

    def test_ignores_trailing_supplement_not_a_lower_price(self):
        rate = FX_RATES_TO_USD["EUR"]
        text = "Price\n5950 EUR\n\nSingle room supplement\n+1.000 EUR"
        assert parse_price(text) == round(5950 * rate, 2)

    def test_hourly_activity_rate_returns_none_not_a_tour_price(self):
        """STEP 0 flagged this shape explicitly — picking up '1,000 yen' as
        the tour's price would misrepresent its actual price band (this is
        a per-activity rate, not a package price)."""
        text = "Price: 1,000 yen/hour; 2,000 yen/3 hours; 3,000 yen/day"
        assert parse_price(text) is None

    def test_complex_seasonal_date_range_table_returns_none(self):
        """No reliable currency marker attached to any individual number —
        must not guess."""
        text = (
            "PRICES: 01-MAY-2026 to 30-SEP-2026\n\n"
            "01 Pax (in SGL room)                                         2323,-\n"
            "02 pax                                                                  1268,-\n"
            "Single Supplement                                               243,-"
        )
        assert parse_price(text) is None

    def test_multi_row_table_still_finds_directly_attached_dollar_amount(self):
        """The 'USD' header is several lines away from any number and is
        correctly ignored (no cross-line leap) — but a real '$45' directly
        attached to a row further down still parses via the $ match."""
        text = (
            "RATES\nDESCRIPTION                                             PAX             "
            "PRICE PER PERSON USD\n1 day tour with lunch                            1                          $45"
        )
        assert parse_price(text) == 45.0

    def test_stray_symbol_far_from_any_real_number_returns_none(self):
        """Regression for a real bug found during manual verification: an
        unbounded whitespace gap let a stray '$' several lines away from a
        real price reach across a newline and grab an unrelated row-index
        number ('1') as if it were the price."""
        text = "person                  usd.$\n     1                       606.8\n     2                       461.3"
        assert parse_price(text) is None

    def test_zero_amount_returns_none(self):
        assert parse_price("$0") is None

    def test_gunma_museum_admission_fee_not_used_as_tour_price(self):
        """Same bug class found in live verification (08/08/2026): tour_id
        72ab6e91-063b-4604-8d37-19f96dcb5a63, src_name "Gunma Museum of
        Natural History". Raw text below is the exact price_raw for that
        row -- parse_price() returned $1.33 for it before this fix.
        NOTE: unlike the Tomioka Silk Mill case below, this specific tour
        was confirmed NOT reachable through GET /catalog at the time of
        the fix (raw_tours.src_itineraries is NULL for this row, which
        fails v_trip_registry's own unrelated pre-existing floor from
        migration 083) -- so this $1.33 was never actually shown to a
        customer. Fixed and tested anyway: same bug class, and it would
        surface the moment that unrelated NULL gets backfilled."""
        text = (
            "Admission\nGeneral admission: 210 yen\n"
            "Senior (65+), university/high school student: 100 yen\n"
            "Child up to high school: Free\n"
            "Groups of 20+: 20% discount (General admission: 160 yen)\n"
            "Separate fee during special exhibits\n"
            "Free admission for persons with a physical disability certificate, "
            "intellectual disability certificate, or mental disability certificate "
            "and one caregiver"
        )
        assert parse_price(text) is None

    def test_tomioka_silk_mill_admission_fee_not_used_as_tour_price(self):
        """THE confirmed live customer-facing case: tour_id a68ebb28-9cc2-
        454b-8747-2f92c3815c83, src_name "Tomioka Silk Mill\\nWorld
        Heritage & National Treasure" -- confirmed present in
        acp_contract.v_trip_registry (so genuinely reachable through
        GET /catalog) and confirmed as the ONLY tour below $10 among all
        441 price_available=true tours in the live catalog before this
        fix (price_usd was $1.27). This is the case that actually
        mattered."""
        text = "Adult: 200 yen, elementary/jr. high school student: 100 yen"
        assert parse_price(text) is None

    def test_min_plausible_price_threshold_boundary(self):
        """A converted amount just under the threshold is rejected; a real
        catalog price just over it (Triund Trek, $10.50, the next-lowest
        genuine value in the live catalog right after the two admission-fee
        bugs above) is accepted unchanged."""
        assert parse_price("$4.99") is None
        assert parse_price("$5.00") == 5.00
        assert parse_price("INR 999 per person") == round(999 * FX_RATES_TO_USD["INR"], 2)

    def test_min_plausible_price_constant_is_5_usd(self):
        assert MIN_PLAUSIBLE_PRICE_USD == 5.0
