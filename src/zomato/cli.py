"""Zomato CLI — command-line interface for restaurant & event discovery."""

from __future__ import annotations

import argparse
import json
import sys

from .client import ZomatoClient


def _print_restaurants(restaurants: list[dict]) -> None:
    if not restaurants:
        print("No restaurants found.")
        return
    print(f"\nFound {len(restaurants)} restaurants:\n")
    for i, r in enumerate(restaurants, 1):
        rating = r.get("rating", "N/A")
        name = r.get("name", "Unknown")
        cuisine = r.get("cuisine", "")
        cost = r.get("cost_for_two", "")
        locality = r.get("locality", "")
        print(f"  {i:2d}. {name} — {rating}★ — {cuisine} — {cost} — {locality}")


def _print_restaurant(info: dict) -> None:
    print(f"\n  Name:        {info.get('name', 'N/A')}")
    print(f"  Rating:      {info.get('rating', 'N/A')} ({info.get('rating_text', '')})")
    print(f"  Cuisine:     {info.get('cuisine', 'N/A')}")
    print(f"  Cost (two):  {info.get('cost_for_two', 'N/A')}")
    print(f"  Address:     {info.get('address', 'N/A')}")
    print(f"  Locality:    {info.get('locality', 'N/A')}")
    print(f"  City:        {info.get('city', 'N/A')}")
    print(f"  Timings:     {info.get('timings', 'N/A')}")
    print(f"  Phone:       {info.get('phone', 'N/A')}")


def _print_reviews(reviews: list[dict]) -> None:
    if not reviews:
        print("No reviews found.")
        return
    print(f"\nFound {len(reviews)} reviews:\n")
    for i, rev in enumerate(reviews, 1):
        rating = rev.get("rating", "N/A")
        user = rev.get("user_name", "Anonymous")
        text = rev.get("text", "")[:200]
        likes = rev.get("likes", 0)
        print(f"  {i}. {rating}★ by {user} (👍 {likes})")
        print(f"     {text}\n")


def _print_events(events: list[dict]) -> None:
    if not events:
        print("No events found.")
        return
    print(f"\nFound {len(events)} events:\n")
    for i, e in enumerate(events, 1):
        title = e.get("title", "Unknown")
        venue = e.get("venue", "")
        city = e.get("city", "")
        category = e.get("category", "")
        date = e.get("date", "")
        desc = e.get("description", "")
        print(f"  {i:2d}. {title}")
        if date:
            print(f"      📅 {date}")
        if venue:
            print(f"      📍 {venue}")
        if city:
            print(f"      🏙️  {city}")
        if category:
            print(f"      🎭 {category}")
        if desc:
            # Truncate description to 150 chars
            print(f"      📝 {desc[:150]}")


def _print_locations(locations: list[dict]) -> None:
    if not locations:
        print("No locations found.")
        return
    print(f"\nFound {len(locations)} locations:\n")
    for i, loc in enumerate(locations, 1):
        print(f"  {i}. {loc['name']} (ID: {loc['entity_id']}, Type: {loc['entity_type']})")
        if loc.get("display_subtitle"):
            print(f"     {loc['display_subtitle']}")


def cmd_restaurants(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    if args.city:
        client.set_location(city=args.city)
    if args.lat and args.lng:
        client.set_location(lat=args.lat, lng=args.lng)
    results = client.search_restaurants(
        city=args.city,
        context=args.context,
    )
    if args.limit:
        results = results[:args.limit]
    _print_restaurants(results)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_restaurant(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    info = client.get_restaurant(res_id=args.id)
    _print_restaurant(info)
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))


def cmd_reviews(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    reviews = client.get_reviews(
        res_id=args.id,
        limit=args.limit,
    )
    _print_reviews(reviews)
    if args.json:
        print(json.dumps(reviews, indent=2, ensure_ascii=False))


def cmd_events(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    events = client.get_events(city=args.city, category=args.category)
    # Filter by keyword query (searches title, venue, description)
    if args.query:
        q = args.query.lower()
        events = [
            e for e in events
            if q in e.get("title", "").lower()
            or q in e.get("venue", "").lower()
            or q in e.get("description", "").lower()
            or q in e.get("category", "").lower()
        ]
    if args.limit:
        events = events[:args.limit]
    _print_events(events)
    if args.json:
        print(json.dumps(events, indent=2, ensure_ascii=False))


def cmd_movies(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    movies = client.get_movies(city=args.city)
    if args.limit:
        movies = movies[:args.limit]
    _print_events(movies)
    if args.json:
        print(json.dumps(movies, indent=2, ensure_ascii=False))


def cmd_search(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    if args.city:
        client.set_location(city=args.city)
    results = client.auto_suggest(query=args.query)
    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_location(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    locations = client.search_location(query=args.query)
    _print_locations(locations)
    if args.json:
        print(json.dumps(locations, indent=2, ensure_ascii=False))


def cmd_collections(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    if args.city:
        client.set_location(city=args.city)
    collections = client.get_collections(city=args.city)
    if not collections:
        print("No collections found.")
        return
    print(f"\nFound {len(collections)} collections:\n")
    for i, c in enumerate(collections, 1):
        print(f"  {i}. {c.get('title', 'Unknown')}")
        if c.get("description"):
            print(f"     {c['description']}")
        if c.get("url"):
            print(f"     {c['url']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zomato",
        description="Discover restaurants, reviews, and events on Zomato",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # restaurants
    p = sub.add_parser("restaurants", help="Search restaurants in a city")
    p.add_argument("--city", default="gurugram", help="City slug (e.g. gurugram, delhi)")
    p.add_argument("--context", default="delivery", choices=["delivery", "dineout", "nightlife"])
    p.add_argument("--lat", type=float, default=None)
    p.add_argument("--lng", type=float, default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_restaurants)

    # restaurant
    p = sub.add_parser("restaurant", help="Get details for a specific restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_restaurant)

    # reviews
    p = sub.add_parser("reviews", help="Get reviews for a restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_reviews)

    # events
    p = sub.add_parser("events", help="Discover events near you")
    p.add_argument("--city", default="gurugram")
    p.add_argument("--category", default="")
    p.add_argument("--query", default="", help="Keyword search (e.g. 'sufi', 'comedy', 'live music')")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_events)

    # movies
    p = sub.add_parser("movies", help="Discover movies near you")
    p.add_argument("--city", default="gurugram")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_movies)

    # search (auto-suggest)
    p = sub.add_parser("search", help="Search suggestions for a query")
    p.add_argument("query", help="Search query (e.g. 'pizza')")
    p.add_argument("--city", default="gurugram")
    p.set_defaults(func=cmd_search)

    # location
    p = sub.add_parser("location", help="Search for Zomato locations")
    p.add_argument("query", help="Location name (e.g. 'Gurugram')")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_location)

    # collections
    p = sub.add_parser("collections", help="Get curated collections for a city")
    p.add_argument("--city", default="gurugram")
    p.set_defaults(func=cmd_collections)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()