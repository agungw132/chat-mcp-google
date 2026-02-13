# Pseudocode - MCP Maps Server

Source: `src/chat_google/mcp_servers/maps_server.py`

## 1) Server initialization

```text
LOAD .env
CREATE FastMCP server named "GoogleMaps"
DEFINE Maps API base URL and HTTP timeout
DEFINE pydantic input models for all tools
```

## 2) Core helpers

### `_get_api_key()`

```text
READ GOOGLE_MAPS_API_KEY from env
IF missing -> raise ValueError
RETURN key
```

### `_request_json(path, params)`

```text
ADD API key into query params
SEND GET request to MAPS_API_BASE + path
IF HTTP status != 200:
    RETURN (None, formatted HTTP error)
PARSE JSON payload
IF parse fails:
    RETURN (None, parse error)
CHECK Google Maps status field:
    - OK or ZERO_RESULTS => success
    - others => RETURN (payload, "Error: Google Maps API status ...")
RETURN (payload, None)
```

### Formatting helpers

```text
_maps_directions_url:
    build web URL to open route in Google Maps

_format_distance:
    convert meters -> km or miles depending on units

_format_duration:
    convert seconds -> "<h>h <m>m" or "<m>m"

_format_place_line:
    normalize name/address/rating/place_id/types/link into one output line
```

## 3) Tool pseudocode

## 3.1 `search_places_text(query, limit=5, language='en', region=None)`

```text
VALIDATE input
CALL /place/textsearch/json with query/language/(optional region)
IF error: return error
TAKE first limit results
IF empty: return "No places found ..."
FORMAT each place line with:
    name, address, rating, place_id, type preview, maps link
RETURN formatted list
ON exception: return "Error searching places: ..."
```

## 3.2 `geocode_address(address, limit=3, language='en', region=None)`

```text
VALIDATE input
CALL /geocode/json with address/language/(optional region)
IF error: return error
TAKE first limit results
IF empty: return "No geocode result found ..."
FORMAT each result:
    formatted address, lat/lng, type preview, place_id, link
RETURN formatted list
ON exception: return "Error geocoding address: ..."
```

## 3.3 `reverse_geocode(latitude, longitude, limit=3, language='en')`

```text
VALIDATE latitude/longitude range + other params
CALL /geocode/json with latlng + language
IF error: return error
TAKE first limit results
IF empty: return "No reverse geocode result found ..."
FORMAT each result:
    formatted address, type preview, place_id, link
RETURN formatted list
ON exception: return "Error reverse geocoding: ..."
```

## 3.4 `get_place_details(place_id, language='en')`

```text
VALIDATE input
CALL /place/details/json with selected fields:
    name, address, phones, website, rating, opening_hours,
    geometry, url, types, place_id
IF error: return error
IF result missing: return "No place details found ..."

EXTRACT open_now + weekday_text preview
EXTRACT lat/lng and type preview
RETURN structured multi-line detail block
ON exception: return "Error getting place details: ..."
```

## 3.5 `get_directions(origin, destination, mode='driving', alternatives=False, language='en', units='metric', departure_time=None)`

```text
VALIDATE input
CALL /directions/json with requested route params
IF error: return error
IF no routes: return "No route found ..."

IF alternatives=True:
    take up to first 3 routes
ELSE:
    take first route only

FOR each selected route:
    aggregate distance (meters) over route legs
    aggregate duration (seconds) over route legs
    aggregate duration_in_traffic if present
    format line with summary + distance + duration + endpoints

IF no leg details parsed: return "No route details found ..."
APPEND maps web link generated from origin/destination/mode
RETURN formatted directions block
ON exception: return "Error getting directions: ..."
```

## 4) Server runner

```text
def run():
    mcp.run()

if __name__ == "__main__":
    run()
```
