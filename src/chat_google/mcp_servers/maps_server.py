import os
from urllib.parse import quote_plus
from typing import Literal

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()
mcp = FastMCP("GoogleMaps")

MAPS_API_BASE = "https://maps.googleapis.com/maps/api"
HTTP_TIMEOUT = httpx.Timeout(timeout=20.0, connect=5.0)


class _SearchPlacesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=10, strict=True)
    language: str = Field(default="en", min_length=2, max_length=10)
    region: str | None = Field(default=None, min_length=2, max_length=3)


class _GeocodeAddressInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    address: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=10, strict=True)
    language: str = Field(default="en", min_length=2, max_length=10)
    region: str | None = Field(default=None, min_length=2, max_length=3)


class _ReverseGeocodeInput(BaseModel):
    limit: int = Field(default=3, ge=1, le=10, strict=True)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    language: str = Field(default="en", min_length=2, max_length=10)


class _PlaceDetailsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    place_id: str = Field(min_length=1)
    language: str = Field(default="en", min_length=2, max_length=10)


class _DirectionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    mode: Literal["driving", "walking", "bicycling", "transit"] = "driving"
    alternatives: bool = False
    language: str = Field(default="en", min_length=2, max_length=10)
    units: Literal["metric", "imperial"] = "metric"
    departure_time: str | None = Field(default=None, min_length=1)


def _get_api_key() -> str:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_MAPS_API_KEY must be set in .env")
    return api_key


def _client_kwargs() -> dict:
    return {"follow_redirects": True, "timeout": HTTP_TIMEOUT}


def _maps_directions_url(origin: str, destination: str, mode: str) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}"
        f"&destination={quote_plus(destination)}"
        f"&travelmode={quote_plus(mode)}"
    )


def _format_distance(distance_m: int, units: str) -> str:
    if units == "imperial":
        return f"{distance_m / 1609.344:.1f} mi"
    return f"{distance_m / 1000.0:.1f} km"


def _format_duration(duration_s: int) -> str:
    if duration_s <= 0:
        return "-"
    hours, rem = divmod(duration_s, 3600)
    minutes = rem // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_maps_status_error(payload: dict) -> str | None:
    status = str(payload.get("status", "UNKNOWN_ERROR"))
    if status in {"OK", "ZERO_RESULTS"}:
        return None
    detail = str(payload.get("error_message", "")).strip()
    detail_part = f" - {detail}" if detail else ""
    return f"Error: Google Maps API status {status}{detail_part}"


async def _request_json(path: str, params: dict | None = None) -> tuple[dict | None, str | None]:
    query_params = dict(params or {})
    query_params["key"] = _get_api_key()
    url = f"{MAPS_API_BASE}{path}"

    async with httpx.AsyncClient(**_client_kwargs()) as client:
        response = await client.get(url, params=query_params)

    if response.status_code != 200:
        body = response.text.strip()[:300]
        body_part = f" - {body}" if body else ""
        return None, f"Error: Google Maps HTTP {response.status_code}{body_part}"

    try:
        payload = response.json()
    except Exception as exc:
        return None, f"Google Maps response parse error: {str(exc)}"

    err = _format_maps_status_error(payload)
    if err:
        return payload, err
    return payload, None


def _format_place_line(item: dict) -> str:
    name = item.get("name") or "Unknown"
    address = item.get("formatted_address") or "-"
    rating = item.get("rating", "-")
    user_ratings_total = item.get("user_ratings_total", "-")
    place_id = item.get("place_id") or "-"
    types = ", ".join(item.get("types", [])[:3]) or "-"
    maps_url = (
        f"https://www.google.com/maps/place/?q=place_id:{quote_plus(place_id)}"
        if place_id != "-"
        else "-"
    )
    return (
        f"- {name} | Address: {address} | Rating: {rating} ({user_ratings_total}) | "
        f"Types: {types} | Place ID: {place_id} | Link: {maps_url}"
    )


@mcp.tool()
async def search_places_text(
    query: str,
    limit: int = 5,
    language: str = "en",
    region: str | None = None,
) -> str:
    """Searches places by free-text query (name, address, category)."""
    try:
        params = _SearchPlacesInput.model_validate(
            {"query": query, "limit": limit, "language": language, "region": region}
        )
        request_params = {"query": params.query, "language": params.language}
        if params.region:
            request_params["region"] = params.region

        data, err = await _request_json("/place/textsearch/json", request_params)
        if err:
            return err
        results = (data or {}).get("results", [])[: params.limit]
        if not results:
            return f"No places found for '{params.query}'"

        lines = [_format_place_line(item) for item in results]
        return f"Places for '{params.query}' (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error searching places: {str(exc)}"


@mcp.tool()
async def geocode_address(
    address: str,
    limit: int = 3,
    language: str = "en",
    region: str | None = None,
) -> str:
    """Converts an address into latitude/longitude coordinates."""
    try:
        params = _GeocodeAddressInput.model_validate(
            {"address": address, "limit": limit, "language": language, "region": region}
        )
        request_params = {"address": params.address, "language": params.language}
        if params.region:
            request_params["region"] = params.region

        data, err = await _request_json("/geocode/json", request_params)
        if err:
            return err
        results = (data or {}).get("results", [])[: params.limit]
        if not results:
            return f"No geocode result found for '{params.address}'"

        lines = []
        for item in results:
            geometry = item.get("geometry", {})
            location = geometry.get("location", {})
            lat = location.get("lat", "-")
            lng = location.get("lng", "-")
            formatted_address = item.get("formatted_address", "-")
            place_id = item.get("place_id", "-")
            types = ", ".join(item.get("types", [])[:3]) or "-"
            maps_url = (
                f"https://www.google.com/maps/place/?q=place_id:{quote_plus(place_id)}"
                if place_id != "-"
                else "-"
            )
            lines.append(
                f"- Address: {formatted_address} | LatLng: {lat}, {lng} | "
                f"Types: {types} | Place ID: {place_id} | Link: {maps_url}"
            )

        return f"Geocode results for '{params.address}' (showing {len(lines)}):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Error geocoding address: {str(exc)}"


@mcp.tool()
async def reverse_geocode(
    latitude: float,
    longitude: float,
    limit: int = 3,
    language: str = "en",
) -> str:
    """Converts latitude/longitude into formatted addresses."""
    try:
        params = _ReverseGeocodeInput.model_validate(
            {
                "latitude": latitude,
                "longitude": longitude,
                "limit": limit,
                "language": language,
            }
        )
        data, err = await _request_json(
            "/geocode/json",
            {
                "latlng": f"{params.latitude},{params.longitude}",
                "language": params.language,
            },
        )
        if err:
            return err
        results = (data or {}).get("results", [])[: params.limit]
        if not results:
            return f"No reverse geocode result found for '{params.latitude},{params.longitude}'"

        lines = []
        for item in results:
            formatted_address = item.get("formatted_address", "-")
            place_id = item.get("place_id", "-")
            types = ", ".join(item.get("types", [])[:3]) or "-"
            maps_url = (
                f"https://www.google.com/maps/place/?q=place_id:{quote_plus(place_id)}"
                if place_id != "-"
                else "-"
            )
            lines.append(
                f"- Address: {formatted_address} | Types: {types} | "
                f"Place ID: {place_id} | Link: {maps_url}"
            )

        return (
            f"Reverse geocode results for '{params.latitude},{params.longitude}' "
            f"(showing {len(lines)}):\n" + "\n".join(lines)
        )
    except Exception as exc:
        return f"Error reverse geocoding: {str(exc)}"


@mcp.tool()
async def get_place_details(place_id: str, language: str = "en") -> str:
    """Gets detailed information for a place by place ID."""
    try:
        params = _PlaceDetailsInput.model_validate({"place_id": place_id, "language": language})
        data, err = await _request_json(
            "/place/details/json",
            {
                "place_id": params.place_id,
                "language": params.language,
                "fields": (
                    "place_id,name,formatted_address,formatted_phone_number,"
                    "international_phone_number,website,rating,user_ratings_total,"
                    "opening_hours,geometry,url,types"
                ),
            },
        )
        if err:
            return err
        result = (data or {}).get("result")
        if not result:
            return f"No place details found for place_id '{params.place_id}'"

        opening_hours = result.get("opening_hours", {})
        open_now = opening_hours.get("open_now")
        weekday_text = opening_hours.get("weekday_text", [])
        weekday_preview = " | ".join(weekday_text[:2]) if weekday_text else "-"
        geometry = result.get("geometry", {}).get("location", {})
        lat = geometry.get("lat", "-")
        lng = geometry.get("lng", "-")
        types = ", ".join(result.get("types", [])[:5]) or "-"

        return (
            "Place Details:\n"
            f"Name: {result.get('name', '-')}\n"
            f"Place ID: {result.get('place_id', params.place_id)}\n"
            f"Address: {result.get('formatted_address', '-')}\n"
            f"LatLng: {lat}, {lng}\n"
            f"Phone: {result.get('formatted_phone_number', '-')}\n"
            f"International Phone: {result.get('international_phone_number', '-')}\n"
            f"Website: {result.get('website', '-')}\n"
            f"Rating: {result.get('rating', '-')} ({result.get('user_ratings_total', '-')})\n"
            f"Open Now: {open_now if open_now is not None else '-'}\n"
            f"Opening Hours (preview): {weekday_preview}\n"
            f"Types: {types}\n"
            f"Link: {result.get('url', '-')}"
        )
    except Exception as exc:
        return f"Error getting place details: {str(exc)}"


@mcp.tool()
async def get_directions(
    origin: str,
    destination: str,
    mode: str = "driving",
    alternatives: bool = False,
    language: str = "en",
    units: str = "metric",
    departure_time: str | None = None,
) -> str:
    """
    Gets route directions between origin and destination.
    departure_time supports values like 'now' or a Unix timestamp string.
    """
    try:
        params = _DirectionsInput.model_validate(
            {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "alternatives": alternatives,
                "language": language,
                "units": units,
                "departure_time": departure_time,
            }
        )

        request_params = {
            "origin": params.origin,
            "destination": params.destination,
            "mode": params.mode,
            "alternatives": str(params.alternatives).lower(),
            "language": params.language,
            "units": params.units,
        }
        if params.departure_time:
            request_params["departure_time"] = params.departure_time

        data, err = await _request_json("/directions/json", request_params)
        if err:
            return err
        routes = (data or {}).get("routes", [])
        if not routes:
            return f"No route found from '{params.origin}' to '{params.destination}'"

        shown_routes = routes[:3] if params.alternatives else routes[:1]
        lines = []
        for idx, route in enumerate(shown_routes, start=1):
            legs = route.get("legs", [])
            if not legs:
                continue
            distance_m = sum(
                int((leg.get("distance", {}) or {}).get("value", 0))
                for leg in legs
                if isinstance(leg, dict)
            )
            duration_s = sum(
                int((leg.get("duration", {}) or {}).get("value", 0))
                for leg in legs
                if isinstance(leg, dict)
            )
            duration_traffic_s = sum(
                int((leg.get("duration_in_traffic", {}) or {}).get("value", 0))
                for leg in legs
                if isinstance(leg, dict) and leg.get("duration_in_traffic")
            )
            start_address = legs[0].get("start_address", "-")
            end_address = legs[-1].get("end_address", "-")
            route_name = route.get("summary") or f"Route {idx}"
            traffic_part = (
                f" | Duration in traffic: {_format_duration(duration_traffic_s)}"
                if duration_traffic_s > 0
                else ""
            )
            lines.append(
                f"- {route_name} | Distance: {_format_distance(distance_m, params.units)} | "
                f"Duration: {_format_duration(duration_s)}{traffic_part} | "
                f"From: {start_address} | To: {end_address}"
            )

        if not lines:
            return f"No route details found from '{params.origin}' to '{params.destination}'"

        map_link = _maps_directions_url(params.origin, params.destination, params.mode)
        return (
            f"Directions from '{params.origin}' to '{params.destination}' "
            f"(mode={params.mode}, showing {len(lines)} route(s)):\n"
            + "\n".join(lines)
            + f"\nMap Link: {map_link}"
        )
    except Exception as exc:
        return f"Error getting directions: {str(exc)}"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
