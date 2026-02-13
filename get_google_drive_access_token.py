import argparse
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
    return parser.parse_args()


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
    creds = flow.run_local_server(port=0, open_browser=not args.no_browser)

    token = creds.token
    if not token:
        print("Error: access token not returned.")
        return 1

    print("GOOGLE_DRIVE_ACCESS_TOKEN acquired.")
    print(f"Expires at: {creds.expiry}")
    print("")
    print(f"GOOGLE_DRIVE_ACCESS_TOKEN={token}")

    if not args.no_write_env:
        env_path = Path(args.env_file)
        upsert_env_var(env_path, "GOOGLE_DRIVE_ACCESS_TOKEN", token)
        print("")
        print(f"Updated {env_path} with GOOGLE_DRIVE_ACCESS_TOKEN.")

    if creds.refresh_token:
        print("")
        print("Note: refresh token was also returned.")
        print("This project currently uses access token only (no auto refresh flow).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
