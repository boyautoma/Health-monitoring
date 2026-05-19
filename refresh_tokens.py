"""Generate fresh Garmin OAuth tokens locally (non-cloud IP)."""
import os
import sys
import time
from garminconnect import Garmin

TOKEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".garmin_tokens")

def main():
    os.makedirs(TOKEN_DIR, exist_ok=True)

    # Try existing tokens first
    token_files = os.listdir(TOKEN_DIR) if os.path.isdir(TOKEN_DIR) else []
    if token_files:
        print(f"Found existing tokens: {token_files}")
        try:
            client = Garmin()
            if hasattr(client, 'garth') and client.garth:
                client.garth.load(TOKEN_DIR)
            client.login()
            if hasattr(client, 'garth') and client.garth:
                client.garth.dump(TOKEN_DIR)
            print("Token refresh successful!")
            print(f"Tokens saved to {TOKEN_DIR}")
            return
        except Exception as e:
            print(f"Token refresh failed: {e}")
            print("Falling back to password login...")

    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        email = input("Garmin email: ")
        password = input("Garmin password: ")

    print("Logging in with credentials...")
    client = Garmin(email, password)
    client.login()
    if hasattr(client, 'garth') and client.garth:
        client.garth.dump(TOKEN_DIR)
    print(f"Fresh tokens saved to {TOKEN_DIR}")

    for f in os.listdir(TOKEN_DIR):
        size = os.path.getsize(os.path.join(TOKEN_DIR, f))
        print(f"  {f}: {size} bytes")

if __name__ == "__main__":
    main()
