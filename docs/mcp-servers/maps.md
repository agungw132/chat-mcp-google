# Maps MCP Server

Source:

- `src/chat_google/mcp_servers/maps_server.py`
- wrapper: `maps_server.py`
- FastMCP server name: `GoogleMaps`

## Purpose

Use this server for place search, geocoding, reverse geocoding, place details, and route directions.

## Required configuration

- `GOOGLE_MAPS_API_KEY`

Required Google APIs (same project as key):

- Geocoding API
- Directions API
- Places API

## Tool catalog

- `search_places_text(query, limit=5, language='en', region=None)`
- `geocode_address(address, limit=3, language='en', region=None)`
- `reverse_geocode(latitude, longitude, limit=3, language='en')`
- `get_place_details(place_id, language='en')`
- `get_directions(origin, destination, mode='driving', alternatives=False, language='en', units='metric', departure_time=None)`

## Calling guidance

Place discovery:

- natural-language place query -> `search_places_text`
- once place chosen, enrich info -> `get_place_details`

Address coordinate conversion:

- address to coordinates -> `geocode_address`
- coordinates to address -> `reverse_geocode`

Routing:

- route estimation and map link -> `get_directions`

## Output semantics

- Plain text with place/address/rating identifiers.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding the model context.
- Place tools include `place_id` and maps link when available.
- Directions include distance, duration, endpoints, and web map URL.

## Error semantics

- Google status-based errors are normalized:
- `Error: Google Maps API status <STATUS> ...`
- HTTP-level errors are normalized:
- `Error: Google Maps HTTP <status> ...`

## Constraints and validation

- `limit` is bounded by validation.
- `latitude` range: `[-90, 90]`.
- `longitude` range: `[-180, 180]`.
- `mode` allowed:
- `driving`
- `walking`
- `bicycling`
- `transit`

## Recommended multi-step patterns

Location-aware calendar planning:

1. `search_places_text("Tatsu Mall of The Netherlands")`
2. `get_place_details(place_id=...)`
3. add address to calendar description in `calendar.add_event`
4. send invite through `gmail.send_calendar_invite_email`

Navigation request:

1. optional `geocode_address` for normalization
2. `get_directions(origin, destination, mode=...)`
