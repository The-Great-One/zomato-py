"""Live smoke tests for Zomato API.

These tests make real HTTP calls to Zomato. They are read-only and opt-in.
Run with: python -m pytest tests/test_smoke.py -q --live
"""

import os
import pytest

from zomato import ZomatoClient, Location


pytestmark = pytest.mark.skipif(
    os.environ.get("ZOMATO_LIVE") != "1",
    reason="Set ZOMATO_LIVE=1 to run live smoke tests",
)


@pytest.fixture
def client():
    return ZomatoClient()


class TestLiveSmoke:
    """Read-only live API tests — safe summaries only."""

    def test_csrf(self, client):
        token = client._ensure_csrf()
        assert len(token) >= 16
        print(f"  CSRF token acquired: {len(token)} chars")

    def test_search_restaurants(self, client):
        results = client.search_restaurants(city="gurugram")
        results = results[:5]  # limit for smoke
        assert isinstance(results, list)
        if results:
            r = results[0]
            assert "name" in r
            assert "resId" in r
            print(f"  Found {len(results)} restaurants — first: {r['name']}")

    def test_get_restaurant(self, client):
        info = client.get_restaurant(res_id=1827)
        assert "name" in info
        assert info["name"]  # non-empty
        print(f"  Restaurant: {info['name']} — {info['cuisine']}")

    def test_get_reviews(self, client):
        reviews = client.get_reviews(res_id=1827, limit=3)
        assert isinstance(reviews, list)
        print(f"  Found {len(reviews)} reviews")

    def test_search_location(self, client):
        locations = client.search_location("Gurugram")
        assert isinstance(locations, list)
        assert len(locations) > 0
        print(f"  Found {len(locations)} locations — first: {locations[0]['name']}")

    def test_auto_suggest(self, client):
        results = client.auto_suggest(query="pizza")
        assert isinstance(results, dict)
        print(f"  Auto-suggest keys: {list(results.keys())}")

    def test_get_events(self, client):
        events = client.get_events(city="")
        assert isinstance(events, list)
        print(f"  Found {len(events)} events")
        if events:
            print(f"  First event: {events[0].get('title', 'N/A')}")