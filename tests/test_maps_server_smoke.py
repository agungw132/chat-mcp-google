import pytest

from chat_google.mcp_servers import maps_server


@pytest.mark.asyncio
async def test_maps_tools_smoke(monkeypatch):
    async def fake_request_json(path, params=None):
        if path == "/place/textsearch/json":
            return (
                {
                    "results": [
                        {
                            "name": "Tatsu",
                            "formatted_address": "Mall of The Netherlands",
                            "rating": 4.5,
                            "user_ratings_total": 120,
                            "place_id": "place-1",
                            "types": ["restaurant", "food"],
                        }
                    ]
                },
                None,
            )
        if path == "/geocode/json" and "address" in (params or {}):
            return (
                {
                    "results": [
                        {
                            "formatted_address": "Damrak 1, Amsterdam",
                            "place_id": "geo-1",
                            "types": ["street_address"],
                            "geometry": {"location": {"lat": 52.377, "lng": 4.898}},
                        }
                    ]
                },
                None,
            )
        if path == "/geocode/json" and "latlng" in (params or {}):
            return (
                {
                    "results": [
                        {
                            "formatted_address": "Amsterdam, Netherlands",
                            "place_id": "rev-1",
                            "types": ["locality", "political"],
                        }
                    ]
                },
                None,
            )
        if path == "/place/details/json":
            return (
                {
                    "result": {
                        "name": "Tatsu",
                        "place_id": "place-1",
                        "formatted_address": "Leidschendam, NL",
                        "rating": 4.6,
                        "user_ratings_total": 88,
                        "opening_hours": {"open_now": True, "weekday_text": ["Mon: 10:00-22:00"]},
                        "geometry": {"location": {"lat": 52.1, "lng": 4.4}},
                        "url": "https://maps.google.com/?cid=123",
                        "types": ["restaurant", "food"],
                    }
                },
                None,
            )
        if path == "/directions/json":
            return (
                {
                    "routes": [
                        {
                            "summary": "A4",
                            "legs": [
                                {
                                    "start_address": "Leiden, Netherlands",
                                    "end_address": "Rotterdam, Netherlands",
                                    "distance": {"value": 36000},
                                    "duration": {"value": 2100},
                                }
                            ],
                        }
                    ]
                },
                None,
            )
        return {}, None

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)

    places = await maps_server.search_places_text("Tatsu")
    geocode = await maps_server.geocode_address("Damrak 1 Amsterdam")
    reverse = await maps_server.reverse_geocode(52.377, 4.898)
    details = await maps_server.get_place_details("place-1")
    directions = await maps_server.get_directions("Leiden", "Rotterdam")

    assert "Places for 'Tatsu'" in places
    assert "Geocode results for 'Damrak 1 Amsterdam'" in geocode
    assert "Reverse geocode results for '52.377,4.898'" in reverse
    assert "Place Details" in details
    assert "Directions from 'Leiden' to 'Rotterdam'" in directions
