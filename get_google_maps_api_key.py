import argparse
import subprocess
import time
import shutil
from pathlib import Path
from typing import Any

import httpx

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


DEFAULT_ENABLE_SERVICES = [
    "apikeys.googleapis.com",
    "geocoding-backend.googleapis.com",
    "directions-backend.googleapis.com",
    "places-backend.googleapis.com",
]


def upsert_env_var(env_path: Path, key: str, value: str) -> None:
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    replaced = False
    output_lines = []
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            output_lines.append(f"{key}={value}")
            replaced = True
        else:
            output_lines.append(line)

    if not replaced:
        if output_lines and output_lines[-1].strip() != "":
            output_lines.append("")
        output_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Programmatically create GOOGLE_MAPS_API_KEY, optionally enable required APIs, "
            "and optionally write the key to .env."
        )
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Google Cloud project ID or number.",
    )
    parser.add_argument(
        "--display-name",
        default="chat-google-maps-key",
        help="Display name for the new API key.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file to update.",
    )
    parser.add_argument(
        "--no-write-env",
        action="store_true",
        help="Do not write GOOGLE_MAPS_API_KEY to .env.",
    )
    parser.add_argument(
        "--access-token",
        default="",
        help=(
            "OAuth Bearer token with cloud-platform scope. "
            "If omitted, script tries gcloud commands automatically."
        ),
    )
    parser.add_argument(
        "--client-secret",
        default="",
        help=(
            "Optional OAuth client secret JSON path for browser-based token flow "
            "(fallback when gcloud is not installed)."
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open browser for OAuth consent (used with --client-secret).",
    )
    parser.add_argument(
        "--skip-enable-apis",
        action="store_true",
        help="Skip enabling APIs before key creation.",
    )
    parser.add_argument(
        "--api-service",
        action="append",
        default=[],
        help=(
            "API service to enable and/or restrict key access to. Repeat for multiple values. "
            "Defaults include apikeys + geocoding + directions + places backend services."
        ),
    )
    parser.add_argument(
        "--no-api-restrictions",
        action="store_true",
        help="Create key without API target restrictions.",
    )
    parser.add_argument(
        "--allowed-ip",
        action="append",
        default=[],
        help="Optional server IP restrictions (repeatable).",
    )
    parser.add_argument(
        "--allowed-referrer",
        action="append",
        default=[],
        help="Optional browser referrer restrictions (repeatable).",
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=int,
        default=180,
        help="Timeout for long-running operation polling.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval in seconds.",
    )
    return parser.parse_args()


def _run_command(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "Command failed")
    output = proc.stdout.strip()
    if not output:
        raise RuntimeError("Command returned empty output")
    return output


def _get_access_token(explicit_token: str, client_secret: str, no_browser: bool) -> str:
    if explicit_token.strip():
        return explicit_token.strip()

    has_gcloud = shutil.which("gcloud") is not None
    commands = [
        ["gcloud", "auth", "application-default", "print-access-token"],
        ["gcloud", "auth", "print-access-token"],
    ]
    errors = []
    if has_gcloud:
        for cmd in commands:
            try:
                return _run_command(cmd)
            except Exception as exc:  # pragma: no cover - environment specific
                errors.append(f"{' '.join(cmd)} => {exc}")
                continue
    else:
        errors.append("gcloud not found in PATH")

    client_secret_path = client_secret.strip()
    if client_secret_path:
        path = Path(client_secret_path)
        if not path.exists():
            raise RuntimeError(f"client secret file not found: {path}")
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise RuntimeError(
                "google-auth-oauthlib is required for --client-secret flow.\n"
                "Use:\n"
                "  uv run --with google-auth-oauthlib python get_google_maps_api_key.py --project <PROJECT_ID> --client-secret client_secret.json"
            ) from exc

        flow = InstalledAppFlow.from_client_secrets_file(str(path), [CLOUD_PLATFORM_SCOPE])
        creds = flow.run_local_server(port=0, open_browser=not no_browser)
        token = str(getattr(creds, "token", "")).strip()
        if token:
            return token
        raise RuntimeError("OAuth flow completed but access token was empty.")

    raise RuntimeError(
        "Unable to get access token automatically.\n"
        "Authenticate first:\n"
        "  1) gcloud auth login\n"
        "  2) gcloud auth application-default login\n"
        "Or pass --access-token.\n"
        "Or use OAuth client secret fallback:\n"
        "  uv run --with google-auth-oauthlib python get_google_maps_api_key.py --project <PROJECT_ID> --client-secret client_secret.json\n"
        f"Details: {' | '.join(errors)}"
    )


def _extract_google_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload)
    err = payload.get("error")
    if isinstance(err, dict):
        message = str(err.get("message", "")).strip()
        status = str(err.get("status", "")).strip()
        code = err.get("code", "")
        parts = [p for p in [f"code={code}" if code else "", status, message] if p]
        if parts:
            return " | ".join(parts)
    return str(payload)


def _request_json(
    method: str,
    url: str,
    token: str,
    json_body: dict | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    with httpx.Client(timeout=httpx.Timeout(timeout=30.0, connect=5.0)) as client:
        response = client.request(method=method, url=url, headers=headers, json=json_body)

    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = response.text.strip()[:500]
        raise RuntimeError(
            f"{method} {url} failed with HTTP {response.status_code}: {_extract_google_error(payload)}"
        )

    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to parse JSON response from {url}: {exc}") from exc


def _poll_operation(
    base_url: str,
    operation_name: str,
    token: str,
    timeout_seconds: int,
    interval_seconds: float,
) -> dict:
    start = time.time()
    while True:
        op = _request_json("GET", f"{base_url}/{operation_name}", token)
        if op.get("done"):
            if "error" in op:
                raise RuntimeError(_extract_google_error(op["error"]))
            return op
        if (time.time() - start) > timeout_seconds:
            raise RuntimeError(
                f"Operation polling timed out after {timeout_seconds}s: {operation_name}"
            )
        time.sleep(interval_seconds)


def _enable_required_services(
    project: str,
    services: list[str],
    token: str,
    timeout_seconds: int,
    interval_seconds: float,
) -> None:
    if not services:
        return
    url = f"https://serviceusage.googleapis.com/v1/projects/{project}/services:batchEnable"
    payload = {"serviceIds": services}
    op = _request_json("POST", url, token, payload)
    op_name = op.get("name")
    if not op_name:
        return
    _poll_operation(
        base_url="https://serviceusage.googleapis.com/v1",
        operation_name=op_name,
        token=token,
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
    )


def _build_restrictions(
    api_services: list[str],
    no_api_restrictions: bool,
    allowed_ips: list[str],
    allowed_referrers: list[str],
) -> dict | None:
    restrictions: dict[str, Any] = {}
    if not no_api_restrictions:
        restrictions["apiTargets"] = [{"service": svc} for svc in api_services]

    if allowed_ips and allowed_referrers:
        raise ValueError("Use either --allowed-ip or --allowed-referrer, not both.")
    if allowed_ips:
        restrictions["serverKeyRestrictions"] = {"allowedIps": allowed_ips}
    elif allowed_referrers:
        restrictions["browserKeyRestrictions"] = {"allowedReferrers": allowed_referrers}

    return restrictions or None


def _create_maps_api_key(
    project: str,
    display_name: str,
    token: str,
    restrictions: dict | None,
    timeout_seconds: int,
    interval_seconds: float,
) -> tuple[str, str]:
    create_url = f"https://apikeys.googleapis.com/v2/projects/{project}/locations/global/keys"
    payload: dict[str, Any] = {"displayName": display_name}
    if restrictions:
        payload["restrictions"] = restrictions

    create_op = _request_json("POST", create_url, token, payload)
    op_name = create_op.get("name")
    if not op_name:
        raise RuntimeError("API Keys create response missing operation name.")

    done = _poll_operation(
        base_url="https://apikeys.googleapis.com/v2",
        operation_name=op_name,
        token=token,
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
    )
    key_resource = ((done.get("response") or {}).get("name") or "").strip()
    if not key_resource:
        raise RuntimeError("Operation finished but key resource name is missing.")

    key_string_url = f"https://apikeys.googleapis.com/v2/{key_resource}/keyString"
    key_string_resp = _request_json("GET", key_string_url, token)
    key_string = str(key_string_resp.get("keyString", "")).strip()
    if not key_string:
        raise RuntimeError("Created key but keyString response is empty.")
    return key_resource, key_string


def main() -> int:
    args = parse_args()

    api_services = args.api_service or list(DEFAULT_ENABLE_SERVICES)

    try:
        token = _get_access_token(
            explicit_token=args.access_token,
            client_secret=args.client_secret,
            no_browser=args.no_browser,
        )
    except Exception as exc:
        print(f"Error getting access token: {exc}")
        return 1

    try:
        if not args.skip_enable_apis:
            print("Enabling required services...")
            for svc in api_services:
                print(f"- {svc}")
            _enable_required_services(
                project=args.project,
                services=api_services,
                token=token,
                timeout_seconds=args.poll_timeout_seconds,
                interval_seconds=args.poll_interval_seconds,
            )
            print("Service enablement complete.")
        else:
            print("Skipping API enablement (--skip-enable-apis).")

        restrictions = _build_restrictions(
            api_services=api_services,
            no_api_restrictions=args.no_api_restrictions,
            allowed_ips=args.allowed_ip,
            allowed_referrers=args.allowed_referrer,
        )
        if restrictions:
            print("Applying API key restrictions:")
            if "apiTargets" in restrictions:
                print("- API targets:")
                for item in restrictions["apiTargets"]:
                    print(f"  - {item['service']}")
            if "serverKeyRestrictions" in restrictions:
                print("- Server IP restrictions enabled.")
            if "browserKeyRestrictions" in restrictions:
                print("- Browser referrer restrictions enabled.")
        else:
            print("Creating key without restrictions.")

        key_resource, key_string = _create_maps_api_key(
            project=args.project,
            display_name=args.display_name,
            token=token,
            restrictions=restrictions,
            timeout_seconds=args.poll_timeout_seconds,
            interval_seconds=args.poll_interval_seconds,
        )
    except Exception as exc:
        print(f"Error creating Google Maps API key: {exc}")
        print("")
        print("Hints:")
        print("- Ensure billing is enabled for the project.")
        print("- Ensure your account has permissions:")
        print("  - serviceusage.services.enable")
        print("  - apikeys.keys.create")
        print("  - apikeys.keys.getKeyString")
        print("- If Service Usage API is not enabled yet, enable it manually once:")
        print("  gcloud services enable serviceusage.googleapis.com --project <PROJECT_ID>")
        return 1

    print("")
    print("Google Maps API key created successfully.")
    print(f"Key resource: {key_resource}")
    print("")
    print(f"GOOGLE_MAPS_API_KEY={key_string}")

    if not args.no_write_env:
        env_path = Path(args.env_file)
        upsert_env_var(env_path, "GOOGLE_MAPS_API_KEY", key_string)
        print("")
        print(f"Updated {env_path} with GOOGLE_MAPS_API_KEY.")

    print("")
    print("Important:")
    print("- Keep this key secret.")
    print("- If this key is for server-side usage, keep server IP restriction enabled.")
    print("- For browser usage, use referrer restrictions instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
