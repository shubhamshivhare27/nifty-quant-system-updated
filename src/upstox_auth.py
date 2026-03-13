"""
upstox_auth.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Upstox OAuth2 token management — auto-refresh flow.

HOW IT WORKS
────────────
Step 1 (one-time setup):
  User clicks "Connect Upstox" in dashboard → redirected to Upstox login
  → Upstox redirects back to your app with ?code=AUTH_CODE
  → We exchange AUTH_CODE for access_token + refresh_token
  → refresh_token is saved to Streamlit secrets (persists forever)

Step 2 (daily, automatic):
  access_token expires every 24h.
  get_valid_token() checks expiry and auto-refreshes using refresh_token.
  No user login required after the initial setup.

Step 3 (GitHub Actions):
  A daily cron job calls refresh_and_update_github_secret() to push the
  new access_token to GitHub Secrets so all workflows use a fresh token.

REQUIRED STREAMLIT SECRETS
────────────────────────────
  UPSTOX_API_KEY       = "your_api_key"
  UPSTOX_API_SECRET    = "your_api_secret"
  UPSTOX_REDIRECT_URI  = "https://your-app.streamlit.app"
  UPSTOX_REFRESH_TOKEN = "refresh_token_from_first_login"   ← set once
  UPSTOX_TOKEN         = "current_access_token"              ← auto-updated
  UPSTOX_TOKEN_EXPIRY  = "2026-03-14T10:00:00"              ← auto-updated
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from urllib.parse import urlencode
from pathlib import Path

log = logging.getLogger("upstox_auth")

# ── Upstox OAuth endpoints ────────────────────────────────────────────────────
AUTH_URL    = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL   = "https://api.upstox.com/v2/login/authorization/token"

# Local token cache file (for non-Streamlit use — e.g. GitHub Actions)
TOKEN_CACHE = Path(__file__).resolve().parent.parent / "data" / "upstox_token.json"


# ── Credential helpers ────────────────────────────────────────────────────────

def _secret(key: str, default: str = "") -> str:
    """Read from env (set from Streamlit secrets by dashboard.py)."""
    return os.environ.get(key, default).strip()


def get_credentials() -> dict:
    """Return all Upstox OAuth credentials from environment."""
    return {
        "api_key":       _secret("UPSTOX_API_KEY"),
        "api_secret":    _secret("UPSTOX_API_SECRET"),
        "redirect_uri":  _secret("UPSTOX_REDIRECT_URI", "https://localhost"),
        "refresh_token": _secret("UPSTOX_REFRESH_TOKEN"),
        "access_token":  _secret("UPSTOX_TOKEN"),
        "token_expiry":  _secret("UPSTOX_TOKEN_EXPIRY"),
    }


def credentials_complete() -> bool:
    """True if minimum credentials for OAuth are present."""
    c = get_credentials()
    return bool(c["api_key"] and c["api_secret"])


def is_connected() -> bool:
    """True if refresh_token is present (user has completed initial OAuth)."""
    return bool(_secret("UPSTOX_REFRESH_TOKEN"))


# ── Step 1: Build the login URL ───────────────────────────────────────────────

def get_login_url() -> str:
    """
    Returns the Upstox OAuth login URL.
    Redirect user to this URL to initiate login.
    After login, Upstox redirects to UPSTOX_REDIRECT_URI?code=AUTH_CODE
    """
    c = get_credentials()
    if not c["api_key"]:
        raise ValueError("UPSTOX_API_KEY is not set in Streamlit secrets.")
    params = {
        "client_id":     c["api_key"],
        "redirect_uri":  c["redirect_uri"],
        "response_type": "code",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# ── Step 2: Exchange auth code for tokens ─────────────────────────────────────

def exchange_code_for_tokens(auth_code: str) -> dict:
    """
    Exchange one-time auth_code for access_token + refresh_token.
    Called once after the user completes initial login.

    Returns:
        {
          "access_token":  "...",
          "refresh_token": "...",
          "expires_at":    "2026-03-15T10:00:00"
        }
    """
    c = get_credentials()
    if not c["api_key"] or not c["api_secret"]:
        raise ValueError("UPSTOX_API_KEY and UPSTOX_API_SECRET must be set.")

    payload = {
        "code":          auth_code,
        "client_id":     c["api_key"],
        "client_secret": c["api_secret"],
        "redirect_uri":  c["redirect_uri"],
        "grant_type":    "authorization_code",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept":        "application/json",
    }
    resp = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)

    if resp.status_code != 200:
        raise ValueError(
            f"Token exchange failed ({resp.status_code}): {resp.text[:400]}"
        )

    data = resp.json()
    expires_at = (datetime.now() + timedelta(hours=23, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")

    result = {
        "access_token":  data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),   # may be same as before for Upstox
        "expires_at":    expires_at,
    }

    # Cache locally
    _save_token_cache(result)

    log.info("Token exchange successful. refresh_token and access_token obtained.")
    return result


# ── Step 3: Refresh access token using refresh_token ─────────────────────────

def refresh_access_token() -> dict:
    """
    Use the stored refresh_token to get a new access_token.
    Upstox supports this via the same token endpoint with grant_type=refresh_token
    (NOTE: Upstox uses a different approach — see note below).

    ⚠️ UPSTOX SPECIFIC: Upstox does not support standard refresh_token grant.
    Instead, they issue a new access_token by re-using the auth_code flow
    OR by using their extended_token endpoint.
    
    Their recommended daily refresh: use the extended token API.
    POST /v2/login/authorization/token with grant_type=refresh_token
    This works if the session is still active (within 30 days).
    """
    c = get_credentials()

    if not c["refresh_token"]:
        raise ValueError(
            "UPSTOX_REFRESH_TOKEN is not set. "
            "Complete the initial OAuth login from the dashboard first."
        )

    payload = {
        "refresh_token": c["refresh_token"],
        "client_id":     c["api_key"],
        "client_secret": c["api_secret"],
        "redirect_uri":  c["redirect_uri"],
        "grant_type":    "refresh_token",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept":       "application/json",
    }

    resp = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)

    if resp.status_code != 200:
        raise ValueError(
            f"Token refresh failed ({resp.status_code}): {resp.text[:400]}\n"
            "The refresh_token may have expired. Re-authenticate from the dashboard."
        )

    data = resp.json()
    expires_at = (datetime.now() + timedelta(hours=23, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")

    result = {
        "access_token":  data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", c["refresh_token"]),  # use old if not rotated
        "expires_at":    expires_at,
    }

    # Update env so current process uses new token
    os.environ["UPSTOX_TOKEN"]        = result["access_token"]
    os.environ["UPSTOX_TOKEN_EXPIRY"] = result["expires_at"]
    if result["refresh_token"]:
        os.environ["UPSTOX_REFRESH_TOKEN"] = result["refresh_token"]

    # Cache locally
    _save_token_cache(result)

    log.info(f"Token refreshed successfully. Expires at: {expires_at}")
    return result


# ── Step 4: Get a valid token (auto-refresh if expired) ──────────────────────

def get_valid_token() -> str:
    """
    Returns a valid access_token, auto-refreshing if expired or within 30 min of expiry.
    This is the main function used by portfolio.py and data_fetcher.py.

    Raises ValueError if refresh fails and no valid token available.
    """
    access_token = _secret("UPSTOX_TOKEN")
    expiry_str   = _secret("UPSTOX_TOKEN_EXPIRY")

    # Check if token is still valid
    if access_token and expiry_str:
        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M:%S")
            if datetime.now() < expiry - timedelta(minutes=30):
                return access_token  # Token is valid
            log.info("Access token expiring soon — refreshing …")
        except ValueError:
            log.warning("Could not parse UPSTOX_TOKEN_EXPIRY — attempting refresh.")

    # Try to load from local cache first (useful in GitHub Actions)
    cached = _load_token_cache()
    if cached:
        try:
            expiry = datetime.strptime(cached["expires_at"], "%Y-%m-%dT%H:%M:%S")
            if datetime.now() < expiry - timedelta(minutes=30):
                os.environ["UPSTOX_TOKEN"]        = cached["access_token"]
                os.environ["UPSTOX_TOKEN_EXPIRY"] = cached["expires_at"]
                log.info("Using cached token from disk.")
                return cached["access_token"]
        except Exception:
            pass

    # Refresh using refresh_token
    if not _secret("UPSTOX_REFRESH_TOKEN"):
        raise ValueError(
            "No valid access token and no refresh token available.\n"
            "Please complete the initial Upstox OAuth login from the dashboard."
        )

    result = refresh_access_token()
    return result["access_token"]


# ── Token cache (local file — used by GitHub Actions) ────────────────────────

def _save_token_cache(token_data: dict) -> None:
    """Save token to local JSON file."""
    try:
        TOKEN_CACHE.parent.mkdir(exist_ok=True)
        with open(TOKEN_CACHE, "w") as f:
            json.dump(token_data, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save token cache: {e}")


def _load_token_cache() -> dict | None:
    """Load token from local JSON file."""
    try:
        if TOKEN_CACHE.exists():
            with open(TOKEN_CACHE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


# ── GitHub Secrets updater (called by GitHub Actions) ────────────────────────

def refresh_and_update_github_secret() -> None:
    """
    Refreshes the access token and updates UPSTOX_TOKEN + UPSTOX_TOKEN_EXPIRY
    in GitHub repository secrets.

    Called by the daily GitHub Actions cron job (.github/workflows/refresh_token.yml).
    Requires GITHUB_TOKEN and GITHUB_REPO env vars to be set.
    """
    import base64
    from nacl import encoding, public as nacl_public  # PyNaCl for secret encryption

    log.info("Refreshing Upstox token for GitHub Secrets update …")
    result = refresh_access_token()

    github_token = os.environ.get("GITHUB_TOKEN", "")
    github_repo  = os.environ.get("GITHUB_REPO", "")   # e.g. "username/repo-name"

    if not github_token or not github_repo:
        log.warning("GITHUB_TOKEN or GITHUB_REPO not set — skipping GitHub secret update.")
        log.info(f"New access_token obtained. Update UPSTOX_TOKEN manually in Streamlit secrets.")
        return

    # Get repo public key for secret encryption
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    key_resp = requests.get(
        f"https://api.github.com/repos/{github_repo}/actions/secrets/public-key",
        headers=headers, timeout=15
    )
    key_resp.raise_for_status()
    pub_key_data = key_resp.json()

    def encrypt_secret(pub_key: str, secret_value: str) -> str:
        pub_key_bytes = base64.b64decode(pub_key)
        sealed = nacl_public.SealedBox(nacl_public.PublicKey(pub_key_bytes))
        return base64.b64encode(sealed.encrypt(secret_value.encode())).decode()

    # Update UPSTOX_TOKEN
    for secret_name, secret_value in [
        ("UPSTOX_TOKEN",        result["access_token"]),
        ("UPSTOX_TOKEN_EXPIRY", result["expires_at"]),
        ("UPSTOX_REFRESH_TOKEN", result["refresh_token"]),
    ]:
        encrypted = encrypt_secret(pub_key_data["key"], secret_value)
        put_resp = requests.put(
            f"https://api.github.com/repos/{github_repo}/actions/secrets/{secret_name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": pub_key_data["key_id"]},
            timeout=15,
        )
        if put_resp.status_code in (201, 204):
            log.info(f"GitHub secret {secret_name} updated ✅")
        else:
            log.error(f"Failed to update {secret_name}: {put_resp.status_code} {put_resp.text[:200]}")

    log.info("GitHub Secrets update complete.")


# ── CLI entry point (for testing / manual refresh) ───────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        # python upstox_auth.py refresh
        token = get_valid_token()
        print(f"✅ Valid token: {token[:20]}…")

    elif len(sys.argv) > 1 and sys.argv[1] == "github":
        # python upstox_auth.py github  ← called by GitHub Actions
        refresh_and_update_github_secret()

    else:
        print("Usage:")
        print("  python upstox_auth.py refresh   — get/refresh access token")
        print("  python upstox_auth.py github    — refresh + update GitHub secrets")
