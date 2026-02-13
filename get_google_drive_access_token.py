import argparse
import json
from pathlib import Path


DEFAULT_SCOPE = "https://www.googleapis.com/auth/drive"


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
        description="Get a Google Drive OAuth access token and optionally write it to .env.",
    )
    parser.add_argument(
        "--client-secret",
        default="client_secret.json",
        help="Path to OAuth client secret JSON (desktop app credentials).",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[DEFAULT_SCOPE],
        help=(
            "OAuth scope. Repeat for multiple scopes. "
            f"Default: {DEFAULT_SCOPE} (full Drive access: read/write/delete)"
        ),
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file to update.",
    )
    parser.add_argument(
        "--no-write-env",
        action="store_true",
        help="Do not write GOOGLE_DRIVE_ACCESS_TOKEN to .env.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open browser for OAuth consent.",
    )
    parser.add_argument(
        "--no-write-refresh-token",
        action="store_true",
        help="Do not write GOOGLE_DRIVE_REFRESH_TOKEN to .env.",
    )
    parser.add_argument(
        "--no-write-oauth-client",
        action="store_true",
        help="Do not write GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET to .env.",
    )
    return parser.parse_args()


def extract_oauth_client_credentials(client_secret_path: Path) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(client_secret_path.read_text(encoding="utf-8"))
    except Exception:
        return None, None

    client_obj = None
    if isinstance(payload, dict):
        if isinstance(payload.get("installed"), dict):
            client_obj = payload["installed"]
        elif isinstance(payload.get("web"), dict):
            client_obj = payload["web"]

    if not isinstance(client_obj, dict):
        return None, None

    client_id = str(client_obj.get("client_id", "")).strip() or None
    client_secret = str(client_obj.get("client_secret", "")).strip() or None
    return client_id, client_secret


def main() -> int:
    args = parse_args()

    client_secret_path = Path(args.client_secret)
    if not client_secret_path.exists():
        print(f"Error: client secret file not found: {client_secret_path}")
        print("Create OAuth Client ID (Desktop app) and download JSON first.")
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency: google-auth-oauthlib")
        print(
            "Run with uv without installing permanently, for example:\n"
            "uv run --with google-auth-oauthlib python get_google_drive_access_token.py"
        )
        return 1

    # Deduplicate scopes while preserving order.
    seen = set()
    scopes = []
    for scope in args.scope:
        if scope and scope not in seen:
            scopes.append(scope)
            seen.add(scope)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes)
    creds = flow.run_local_server(
        port=0,
        open_browser=not args.no_browser,
        access_type="offline",
        prompt="consent",
    )

    token = creds.token
    if not token:
        print("Error: access token not returned.")
        return 1

    client_id, client_secret = extract_oauth_client_credentials(client_secret_path)

    print("GOOGLE_DRIVE_ACCESS_TOKEN acquired.")
    print(f"Expires at: {creds.expiry}")
    print("")
    print(f"GOOGLE_DRIVE_ACCESS_TOKEN={token}")

    if not args.no_write_env:
        env_path = Path(args.env_file)
        upsert_env_var(env_path, "GOOGLE_DRIVE_ACCESS_TOKEN", token)
        if creds.refresh_token and not args.no_write_refresh_token:
            upsert_env_var(env_path, "GOOGLE_DRIVE_REFRESH_TOKEN", creds.refresh_token)
        if not args.no_write_oauth_client and client_id and client_secret:
            upsert_env_var(env_path, "GOOGLE_OAUTH_CLIENT_ID", client_id)
            upsert_env_var(env_path, "GOOGLE_OAUTH_CLIENT_SECRET", client_secret)
        print("")
        print(f"Updated {env_path} with GOOGLE_DRIVE_ACCESS_TOKEN.")
        if creds.refresh_token and not args.no_write_refresh_token:
            print(f"Updated {env_path} with GOOGLE_DRIVE_REFRESH_TOKEN.")
        if not args.no_write_oauth_client and client_id and client_secret:
            print(f"Updated {env_path} with GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET.")

    if creds.refresh_token:
        print("")
        print("Note: refresh token was also returned.")
        if args.no_write_refresh_token:
            print("You can store it manually as GOOGLE_DRIVE_REFRESH_TOKEN for auto refresh flow.")
        else:
            print("It has been stored as GOOGLE_DRIVE_REFRESH_TOKEN for auto refresh flow.")
    else:
        print("")
        print("Note: refresh token was not returned.")
        print("If you need auto refresh flow, revoke prior consent and run again with prompt consent.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
