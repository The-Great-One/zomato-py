# zomato-py

Unofficial Python client for Zomato's web API. Discover restaurants, read reviews, browse collections, and find events happening near you — all without an API key.

## Features

- **Restaurant search** — find restaurants by city, cuisine, location, or keyword
- **Restaurant details** — full info including rating, cuisine, cost, photos, menu
- **Reviews** — read and filter restaurant reviews
- **Collections** — curated restaurant collections per city
- **Location search** — find Zomato entity IDs for any city/area
- **Auto-suggest** — search suggestions as you type
- **Events** — discover events, movies, concerts, and shows via District by Zomato
- **Quick links** — browse home/city quick links for discovery

## Installation

```bash
pip install -e .
```

## Quick Start

```python
from zomato import ZomatoClient

client = ZomatoClient()

# Search restaurants in Gurugram
results = client.search_restaurants(city="gurugram")
for r in results[:5]:
    print(f"{r['name']} — {r['rating']} — {r['cuisine']}")

# Get restaurant details
info = client.get_restaurant(res_id=1827)
print(info['name'], info['cuisine'], info['cost_for_two'])

# Get reviews
reviews = client.get_reviews(res_id=1827, limit=5)
for rev in reviews:
    print(f"{rev['rating']}★ — {rev['text'][:100]}")

# Find events near you
events = client.get_events(city="gurugram")
for e in events[:5]:
    print(f"{e['title']} — {e['venue']} — {e['city']}")

# Location search
locs = client.search_location("Gurugram")
for loc in locs:
    print(f"{loc['name']} (ID: {loc['entity_id']})")
```

## CLI

```bash
zomato restaurants --city gurugram
zomato restaurant --id 1827
zomato reviews --id 1827 --limit 5
zomato events --city gurugram
zomato search "pizza" --city gurugram
zomato location "Gurugram"
```

## Authentication

No API key required. The client manages CSRF tokens and session cookies automatically, just like the Zomato web app.

## Disclaimer

This is an unofficial package. It uses Zomato's public web API endpoints which may change at any time. Not affiliated with Zomato.
