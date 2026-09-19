"""Test suite.

    pytest -q

Covers the ranking maths, the pricing rules, the availability constraint and
the HTTP surface. The database is rebuilt per test module in a temp file, so
tests never touch the development database.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                                   # noqa: E402
from app.nlp import TfidfIndex, tokenize                     # noqa: E402
from app.recommender import parse_intent                     # noqa: E402


@pytest.fixture(scope="module")
def app():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    application = create_app("testing")
    application.config["DATABASE_PATH"] = path
    with application.app_context():
        from app.database import init_db
        from app.recommender import build_index
        from app.services import load_fleet
        init_db()
        build_index(load_fleet(), application.config["RECOMMENDER_WEIGHTS"])
    yield application
    os.unlink(path)


@pytest.fixture
def client(app):
    return app.test_client()


def future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- tokeniser

class TestTokenizer:
    def test_drops_stopwords_and_lowercases(self):
        assert "the" not in tokenize("The Fast Car")

    def test_folds_synonyms_to_one_token(self):
        assert "budget" in tokenize("cheap")
        assert "budget" in tokenize("affordable")

    def test_emits_bigrams(self):
        assert any("_" in t for t in tokenize("fast luxury car"))

    def test_empty_input_is_safe(self):
        assert tokenize("") == []
        assert tokenize("the and or") == []


class TestTfidf:
    @pytest.fixture
    def index(self):
        return TfidfIndex({
            "fast": "fast supercar racing performance track",
            "family": "spacious family suv seven seats luggage",
            "cheap": "budget economy cheap low running cost",
        })

    def test_ranks_the_relevant_document_first(self, index):
        assert index.search("supercar racing", top_k=1)[0][0] == "fast"
        assert index.search("seven seats for the family", top_k=1)[0][0] == "family"

    def test_similarity_is_bounded(self, index):
        vec = index.vectorise_query("supercar")
        for doc in index.doc_ids:
            assert 0.0 <= index.similarity(vec, doc) <= 1.0001

    def test_unknown_terms_score_zero(self, index):
        vec = index.vectorise_query("zzzz qqqq")
        assert all(index.similarity(vec, d) == 0.0 for d in index.doc_ids)


# ------------------------------------------------------------ intent parser

class TestIntentParser:
    @pytest.mark.parametrize("text,expected", [
        ("under 500 a day", 500),
        ("budget of 1,200", 1200),
        ("less than 3k per day", 3000),
        ("max 250", 250),
        ("AED 800", 800),
    ])
    def test_extracts_budget(self, text, expected):
        assert parse_intent(text).budget_max == expected

    def test_distinguishes_strict_from_soft_ceilings(self):
        assert parse_intent("under 3000 a day").budget_strict is True
        assert parse_intent("around 3000 a day").budget_strict is False

    @pytest.mark.parametrize("text,expected", [
        ("6 people", 6), ("family of four", 4),
        ("seven passengers", 7), ("2 of us", 2),
    ])
    def test_extracts_passenger_count(self, text, expected):
        assert parse_intent(text).passengers == expected

    def test_extracts_duration_in_days(self):
        assert parse_intent("for 2 weeks").days == 14
        assert parse_intent("for a 5 day trip").days == 5

    def test_detects_categories_and_occasions(self):
        intent = parse_intent("luxury car for a wedding")
        assert "Luxury" in intent.categories
        assert "wedding" in intent.occasions

    def test_price_ceiling_is_not_an_economy_request(self):
        """'budget around 3000' states a limit, not a want for a cheap car."""
        assert "Economy" not in parse_intent("supercar, budget around 3000").categories

    def test_cues_match_on_word_boundaries_only(self):
        """'heading' must not trigger the supercar cue 'head'."""
        assert "Supercar" not in parse_intent("heading to the desert").categories

    def test_explicit_fields_override_the_text(self):
        intent = parse_intent("under 500", {"budget_max": 2000, "passengers": 7})
        assert intent.budget_max == 2000
        assert intent.passengers == 7

    def test_handles_empty_input(self):
        intent = parse_intent("")
        assert intent.budget_max is None and intent.categories == []


# -------------------------------------------------------------- recommender

class TestRecommender:
    def post(self, client, **payload):
        return client.post("/api/v1/recommend", json=payload)

    def test_requires_some_input(self, client):
        assert self.post(client, query="").status_code == 400

    def test_returns_ranked_results(self, client):
        data = self.post(client, query="fast supercar", limit=5).get_json()
        scores = [r["match"]["score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)
        assert data["results"][0]["category"] in ("Supercar", "Sports")

    def test_every_result_explains_itself(self, client):
        data = self.post(client, query="family suv for the desert").get_json()
        for result in data["results"]:
            assert result["match"]["reasons"]
            assert 0 <= result["match"]["percent"] <= 100

    def test_capacity_is_a_hard_constraint(self, client):
        data = self.post(client, query="anything", passengers=7).get_json()
        assert all(r["seats"] >= 7 for r in data["results"])

    def test_strict_ceiling_excludes_dearer_cars(self, client):
        data = self.post(client, query="supercar under 1000 a day").get_json()
        assert all(r["daily_rate"] <= 1020 for r in data["results"])

    def test_falls_back_rather_than_returning_nothing(self, client):
        """No luxury car costs under AED 200, but the user still gets options."""
        data = self.post(client, query="luxury car under 200 a day").get_json()
        assert data["count"] > 0

    def test_signals_are_normalised(self, client):
        data = self.post(client, query="electric car with autopilot").get_json()
        for result in data["results"]:
            for value in result["match"]["signals"].values():
                assert 0.0 <= value <= 1.0001


# ------------------------------------------------------------------ pricing

class TestPricing:
    def quote(self, client, **payload):
        return client.post("/api/v1/quote", json=payload).get_json()["quote"]

    def test_base_total_is_rate_times_days(self, client):
        q = self.quote(client, car_slug="nissan-sunny", days=2)
        assert q["base_total"] == pytest.approx(99 * 2)

    def test_no_discount_below_three_days(self, client):
        assert self.quote(client, car_slug="nissan-sunny", days=2)["discount"] == 0

    @pytest.mark.parametrize("days,pct", [(3, 7), (7, 15), (30, 25)])
    def test_discount_tiers(self, client, days, pct):
        assert self.quote(client, car_slug="nissan-sunny", days=days)["discount_pct"] == pct

    def test_vat_applies_after_discount_and_extras(self, client):
        q = self.quote(client, car_slug="mercedes-s500", days=5,
                       extras=["insurance", "chauffeur"])
        subtotal = q["base_total"] - q["discount"] + q["extras_total"]
        assert q["vat"] == pytest.approx(subtotal * 0.05, abs=0.01)
        assert q["total"] == pytest.approx(subtotal + q["vat"], abs=0.01)

    def test_unknown_extras_are_ignored(self, client):
        q = self.quote(client, car_slug="nissan-sunny", days=2, extras=["free_yacht"])
        assert q["extras_total"] == 0

    def test_unknown_car_is_rejected(self, client):
        res = client.post("/api/v1/quote", json={"car_slug": "delorean", "days": 2})
        assert res.status_code == 400


# ------------------------------------------------------------------ booking

class TestBooking:
    def payload(self, **overrides):
        base = {
            "car_slug": "mini-cooper-s",
            "pickup_date": future(10),
            "return_date": future(13),
            "full_name": "Test Driver",
            "email": "test@example.com",
            "phone": "+971500000000",
        }
        base.update(overrides)
        return base

    def test_creates_a_booking(self, client):
        res = client.post("/api/v1/bookings", json=self.payload())
        assert res.status_code == 201
        booking = res.get_json()["booking"]
        assert booking["reference"].startswith("VD-")
        assert booking["quote"]["total"] > 0

    def test_booking_is_retrievable(self, client):
        ref = client.post("/api/v1/bookings", json=self.payload()).get_json()["booking"]["reference"]
        assert client.get(f"/api/v1/bookings/{ref}").status_code == 200

    def test_booking_can_be_cancelled_once(self, client):
        ref = client.post("/api/v1/bookings", json=self.payload()).get_json()["booking"]["reference"]
        assert client.post(f"/api/v1/bookings/{ref}/cancel").status_code == 200
        assert client.post(f"/api/v1/bookings/{ref}/cancel").status_code == 404

    @pytest.mark.parametrize("overrides,field", [
        ({"email": "nope"}, "email"),
        ({"return_date": future(9)}, "return_date"),
        ({"pickup_date": "1999-01-01", "return_date": "1999-01-05"}, "pickup_date"),
        ({"car_slug": "not-a-car"}, "car_slug"),
        ({"full_name": ""}, "full_name"),
        ({"pickup_date": "garbage"}, "pickup_date"),
    ])
    def test_rejects_bad_input(self, client, overrides, field):
        res = client.post("/api/v1/bookings", json=self.payload(**overrides))
        assert res.status_code == 400
        assert res.get_json()["field"] == field

    def test_exhausting_stock_blocks_further_bookings(self, client):
        """The Ghost has one unit, so a second overlapping hire must fail."""
        single = {"car_slug": "rolls-royce-ghost",
                  "pickup_date": future(40), "return_date": future(44)}
        first = client.post("/api/v1/bookings", json=self.payload(**single))
        assert first.status_code == 201

        overlap = client.post("/api/v1/bookings", json=self.payload(
            car_slug="rolls-royce-ghost",
            pickup_date=future(41), return_date=future(43)))
        assert overlap.status_code == 400

    def test_adjacent_dates_do_not_overlap(self, client):
        """A hire starting the day another ends is allowed."""
        res = client.post("/api/v1/bookings", json=self.payload(
            car_slug="rolls-royce-ghost",
            pickup_date=future(44), return_date=future(46)))
        assert res.status_code == 201


# --------------------------------------------------------------- API surface

class TestApi:
    def test_health(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["status"] == "ok" and data["fleet_size"] == 18

    def test_lists_the_fleet(self, client):
        data = client.get("/api/v1/cars").get_json()
        assert data["count"] == 18
        assert "features" in data["cars"][0]

    @pytest.mark.parametrize("query,check", [
        ("category=SUV", lambda c: c["category"] == "SUV"),
        ("min_seats=7", lambda c: c["seats"] >= 7),
        ("max_price=200", lambda c: c["daily_rate"] <= 200),
        ("fuel_type=Electric", lambda c: c["fuel_type"] == "Electric"),
    ])
    def test_filters(self, client, query, check):
        data = client.get(f"/api/v1/cars?{query}").get_json()
        assert data["count"] > 0
        assert all(check(c) for c in data["cars"])

    def test_sorting(self, client):
        rates = [c["daily_rate"] for c in
                 client.get("/api/v1/cars?sort=price_asc").get_json()["cars"]]
        assert rates == sorted(rates)

    def test_detail_includes_similar_vehicles(self, client):
        data = client.get("/api/v1/cars/bmw-m4-competition").get_json()
        assert data["car"]["make"] == "BMW"
        assert len(data["car"]["similar"]) == 3
        assert all(s["slug"] != "bmw-m4-competition" for s in data["car"]["similar"])

    def test_unknown_car_returns_404_json(self, client):
        res = client.get("/api/v1/cars/flying-carpet")
        assert res.status_code == 404
        assert res.get_json()["error"] == "not_found"

    def test_availability_respects_bookings(self, client):
        data = client.get(
            f"/api/v1/availability?pickup_date={future(40)}&return_date={future(44)}"
        ).get_json()
        assert all(c["slug"] != "rolls-royce-ghost" for c in data["cars"])

    def test_availability_rejects_reversed_dates(self, client):
        res = client.get(
            f"/api/v1/availability?pickup_date={future(5)}&return_date={future(2)}")
        assert res.status_code == 400

    def test_stats(self, client):
        data = client.get("/api/v1/stats").get_json()
        assert data["fleet_size"] == 18 and data["categories"]


# --------------------------------------------------------------- HTML pages

class TestPages:
    @pytest.mark.parametrize("path", [
        "/", "/fleet", "/concierge", "/lookup",
        "/cars/tesla-model-3-lr", "/book/nissan-sunny",
    ])
    def test_pages_render(self, client, path):
        res = client.get(path)
        assert res.status_code == 200
        assert b"Velocity Drive" in res.data

    def test_missing_car_renders_404_page(self, client):
        assert client.get("/cars/nope").status_code == 404

    def test_booking_form_posts_and_redirects(self, client):
        res = client.post("/book/nissan-sunny", data={
            "pickup_date": future(60), "return_date": future(62),
            "full_name": "Form Tester", "email": "form@example.com",
            "phone": "+971500000000", "extras": ["insurance"],
        })
        assert res.status_code == 302
        assert "/booking/VD-" in res.headers["Location"]

    def test_invalid_form_redisplays_with_error(self, client):
        res = client.post("/book/nissan-sunny", data={
            "pickup_date": future(60), "return_date": future(62),
            "full_name": "X", "email": "bad", "phone": "1",
        })
        assert res.status_code == 400
        assert b"valid email" in res.data
