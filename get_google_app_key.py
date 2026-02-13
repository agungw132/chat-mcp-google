import argparse
import webbrowser


ACCOUNT_URL = "https://myaccount.google.com/"
APP_PASSWORDS_URL = "https://myaccount.google.com/apppasswords"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Helper guide for Google App Password (GOOGLE_APP_KEY). "
            "App Password cannot be generated programmatically."
        )
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open Google Account and App Password pages in your browser.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("GOOGLE_APP_KEY cannot be generated programmatically via public API.")
    print("You must create it manually from Google Account security settings.")
    print("")
    print("Steps:")
    print("1. Open https://myaccount.google.com/")
    print("2. Go to Security.")
    print("3. Enable 2-Step Verification.")
    print("4. Open App Passwords: https://myaccount.google.com/apppasswords")
    print("5. Generate a new app password (16 characters, no spaces).")
    print("6. Put it into .env as GOOGLE_APP_KEY=xxxxxxxxxxxxxxxx")
    print("")
    print("Notes:")
    print("- App Password is used for IMAP/SMTP/CalDAV/CardDAV.")
    print("- It is different from OAuth access tokens (e.g. Drive API token).")

    if args.open:
        webbrowser.open(ACCOUNT_URL)
        webbrowser.open(APP_PASSWORDS_URL)
        print("")
        print("Opened Google Account and App Password pages in browser.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
