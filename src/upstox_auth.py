"""
upstox_auth.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Upstox token management with full TOTP auto-login.

HOW IT WORKS
────────────
- Uses `upstox-totp` library to fully automate the login flow.
- No browser, no manual steps, no OTP on phone.
- GitHub Actions runs this daily at 07:30 IST, refreshes the token,
  and pushes the new UPSTOX_TOKEN to both GitHub + Streamlit secrets.

REQUIRED SECRETS (GitHub + Streamlit)
──────────────────────────────────────
  UPSTOX_USERNAME     = "9876543210"          # 10-digit mobile number
  UPSTOX_PASSWORD     = "your-password"       # Upstox login password
  UPSTOX_PIN          = "123456"              # 6-digit Upstox PIN
  UPSTOX_TOTP_SECRET  = "BASE32SECRETKEY"     # TOTP secret (see setup below)
  UPSTOX_API_KEY      = "your-api-key"        # from upstox developer console
  UPSTOX_API_SECRET   = "your-api-secret"     # from upstox developer console
  UPSTOX_REDIRECT_URI = "https://your-app.streamlit.app"

HOW TO GET UPSTOX_TOTP_SECRET
──────────────────────────────
1. Log into Upstox → Profile → Security → Enable TOTP
2. When shown the QR code, also click "Can't scan? Show key"
3. That key (Base32 string) = UPSTOX_TOTP_SECRET
4. Scan the QR code with Google Authenticator too (as backup)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

log = logging.getLogger("upstox_auth")

TOKEN_CACHE = Path(__file__).resolve().parent.parent / "data" / "upstox_token.json"
AUTH_URL    = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL   = "https://api.upstox.com/v2/login/authorization/token"


# ── Secret reader ─────────────────────────────────────────────────────────────

def _secret(key: str, default: str = "") -> str:
    """
    Read from os.environ first, then st.secrets directly.
    Works both inside Streamlit and in GitHub Actions.
    """
    val = os.environ.get(key, "").strip()
    if val:
        return val
    try:
        import streamlit as st
        if key in st.secrets:
            val = str(st.secrets[key]).strip()
            if val:
                os.environ[key] = val   # cache for subsequent calls
                return val
    except Exception:
        pass
    return default


# ── Status checks ─────────────────────────────────────────────────────────────

def is_connected() -> bool:
    """True if UPSTOX_TOKEN is present (token exists, may or may not be valid)."""
    return bool(_secret("UPSTOX_TOKEN"))


def credentials_complete() -> bool:
    """True if API key + secret are present (minimum for OAuth login URL)."""
    return bool(_secret("UPSTOX_API_KEY") and _secret("UPSTOX_API_SECRET"))


def totp_credentials_complete() -> bool:
    """True if all TOTP credentials are present for fully automated login."""
    required = ["UPSTOX_USERNAME", "UPSTOX_PASSWORD", "UPSTOX_PIN",
                "UPSTOX_TOTP_SECRET", "UPSTOX_API_KEY", "UPSTOX_API_SECRET"]
    return all(_secret(k) for k in required)


# ── Manual OAuth login URL (fallback if TOTP not configured) ──────────────────

def get_login_url() -> str:
    """Returns Upstox OAuth login URL for manual browser login."""
    api_key      = _secret("UPSTOX_API_KEY")
    redirect_uri = _secret("UPSTOX_REDIRECT_URI", "https://localhost")
    if not api_key:
        raise ValueError("UPSTOX_API_KEY is not set in Streamlit secrets.")
    params = {
        "client_id":     api_key,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(auth_code: str) -> dict:
    """Exchange one-time auth_code (from OAuth callback) for access_token."""
    payload = {
        "code":          auth_code,
        "client_id":     _secret("UPSTOX_API_KEY"),
        "client_secret": _secret("UPSTOX_API_SECRET"),
        "redirect_uri":  _secret("UPSTOX_REDIRECT_URI", "https://localhost"),
        "grant_type":    "authorization_code",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept":       "application/json",
    }
    resp = requests.post(TOKEN_URL, data=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"Token exchange failed ({resp.status_code}): {resp.text[:400]}")

    data = resp.json()
    expires_at = (datetime.now() + timedelta(hours=23, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    result = {
        "access_token": data.get("access_token", ""),
        "expires_at":   expires_at,
    }
    _save_token_cache(result)
    log.info("Manual OAuth token exchange successful.")
    return result


# ── TOTP Auto-login ───────────────────────────────────────────────────────────

def generate_token_via_totp() -> dict:
    """
    Fully automated token generation using TOTP credentials.
    No browser, no manual steps. Uses the `upstox-totp` library.

    Returns:
        {"access_token": "...", "expires_at": "2026-03-15T03:30:00"}

    Raises:
        ValueError if TOTP credentials are missing or login fails.
    """
    try:
        from upstox_totp import UpstoxTOTP
        from pydantic import SecretStr
    except ImportError:
        raise ValueError(
            "upstox-totp library not installed. "
            "Add 'upstox-totp' to requirements.txt and redeploy."
        )

    if not totp_credentials_complete():
        missing = [k for k in ["UPSTOX_USERNAME", "UPSTOX_PASSWORD", "UPSTOX_PIN",
                                "UPSTOX_TOTP_SECRET", "UPSTOX_API_KEY", "UPSTOX_API_SECRET"]
                   if not _secret(k)]
        raise ValueError(
            f"TOTP credentials incomplete. Missing: {', '.join(missing)}. "
            "Add them to Streamlit secrets and GitHub secrets."
        )

    log.info("Generating Upstox token via TOTP auto-login …")

    try:
        upx = UpstoxTOTP(
            username     = _secret("UPSTOX_USERNAME"),
            password     = SecretStr(_secret("UPSTOX_PASSWORD")),
            pin_code     = SecretStr(_secret("UPSTOX_PIN")),
            totp_secret  = SecretStr(_secret("UPSTOX_TOTP_SECRET")),
            client_id    = _secret("UPSTOX_API_KEY"),
            client_secret= SecretStr(_secret("UPSTOX_API_SECRET")),
            redirect_uri = _secret("UPSTOX_REDIRECT_URI", "https://localhost"),
        )

        response = upx.app_token.get_access_token()

        if not response.success or not response.data:
            raise ValueError(f"TOTP login failed: {response}")

        access_token = response.data.access_token
        # Upstox tokens expire at 3:30 AM next day
        now = datetime.now()
        expiry = now.replace(hour=3, minute=30, second=0, microsecond=0)
        if now >= expiry:
            expiry = expiry + timedelta(days=1)
        expires_at = expiry.strftime("%Y-%m-%dT%H:%M:%S")

        result = {"access_token": access_token, "expires_at": expires_at}

        # Update env so current process uses new token immediately
        os.environ["UPSTOX_TOKEN"]        = access_token
        os.environ["UPSTOX_TOKEN_EXPIRY"] = expires_at

        _save_token_cache(result)
        log.info(f"TOTP token generated. User: {response.data.user_name}. Expires: {expires_at}")
        return result

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"TOTP auto-login failed: {e}") from e


# ── Get valid token (used by portfolio.py and data_fetcher.py) ────────────────

def get_valid_token() -> str:
    """
    Returns a valid UPSTOX_TOKEN.
    - If current token is valid (not expired), returns it.
    - If expired and TOTP credentials available, auto-refreshes via TOTP.
    - If expired and no TOTP, raises ValueError with instructions.
    """
    access_token = _secret("UPSTOX_TOKEN")
    expiry_str   = _secret("UPSTOX_TOKEN_EXPIRY")

    # Check if current token is still valid
    if access_token and expiry_str:
        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M:%S")
            if datetime.now() < expiry - timedelta(minutes=30):
                return access_token   # still valid
            log.info("Token expiring soon — auto-refreshing via TOTP …")
        except ValueError:
            pass

    # Token missing or expired — try TOTP auto-refresh
    if totp_credentials_complete():
        result = generate_token_via_totp()
        return result["access_token"]

    # No TOTP credentials — check if we have a token anyway (may still be valid)
    if access_token:
        log.warning("Token may be expired but no TOTP credentials for auto-refresh. Using existing token.")
        return access_token

    raise ValueError(
        "UPSTOX_TOKEN is missing and TOTP auto-refresh is not configured. "
        "Either add TOTP credentials (UPSTOX_USERNAME, UPSTOX_PASSWORD, UPSTOX_PIN, "
        "UPSTOX_TOTP_SECRET) for auto-refresh, or manually update UPSTOX_TOKEN in secrets."
    )


# ── GitHub Secrets updater ────────────────────────────────────────────────────

def update_github_secret(secret_name: str, secret_value: str) -> bool:
    """Push a single secret value to GitHub repository secrets."""
    try:
        import base64
        from nacl import encoding, public as nacl_public
    except ImportError:
        log.warning("pynacl not installed — cannot update GitHub secrets.")
        return False

    github_token = os.environ.get("GH_PAT_TOKEN", "")
    github_repo  = os.environ.get("GITHUB_REPO", "")

    if not github_token or not github_repo:
        log.warning("GH_PAT_TOKEN or GITHUB_REPO not set — skipping GitHub secret update.")
        return False

    headers = {
        "Authorization":        f"Bearer {github_token}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Get repo public key
    key_resp = requests.get(
        f"https://api.github.com/repos/{github_repo}/actions/secrets/public-key",
        headers=headers, timeout=15
    )
    if key_resp.status_code != 200:
        log.error(f"Failed to get GitHub public key: {key_resp.status_code}")
        return False

    pub_key_data = key_resp.json()
    pub_key_bytes = base64.b64decode(pub_key_data["key"])
    sealed = nacl_public.SealedBox(nacl_public.PublicKey(pub_key_bytes))
    encrypted = base64.b64encode(sealed.encrypt(secret_value.encode())).decode()

    put_resp = requests.put(
        f"https://api.github.com/repos/{github_repo}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": pub_key_data["key_id"]},
        timeout=15,
    )
    success = put_resp.status_code in (201, 204)
    if success:
        log.info(f"GitHub secret {secret_name} updated ✅")
    else:
        log.error(f"Failed to update {secret_name}: {put_resp.status_code}")
    return success


def update_streamlit_secret(secret_name: str, secret_value: str) -> bool:
    """
    Streamlit Community Cloud has no public API for updating secrets.
    The dashboard instead auto-refreshes its own token via TOTP when
    get_valid_token() detects expiry — no external update needed.
    This function is a no-op kept for interface compatibility.
    """
    log.debug(f"Streamlit secret update skipped for {secret_name} — dashboard self-refreshes via TOTP.")
    return True


def refresh_and_push_token() -> str:
    """
    Full daily refresh flow:
    1. Generate new token via TOTP
    2. Push UPSTOX_TOKEN + UPSTOX_TOKEN_EXPIRY to GitHub Secrets
    3. Push to Streamlit secrets (if configured)
    Returns the new access token.
    """
    log.info("="*60)
    log.info("Daily Upstox Token Refresh")
    log.info("="*60)

    result = generate_token_via_totp()
    token      = result["access_token"]
    expires_at = result["expires_at"]

    log.info(f"New token generated. Expires: {expires_at}")

    # Push to GitHub
    update_github_secret("UPSTOX_TOKEN",        token)
    update_github_secret("UPSTOX_TOKEN_EXPIRY",  expires_at)

    # Streamlit dashboard self-refreshes via TOTP when token expires — no push needed

    log.info("Token refresh complete ✅")
    return token


# ── Token cache ───────────────────────────────────────────────────────────────

def _save_token_cache(token_data: dict) -> None:
    try:
        TOKEN_CACHE.parent.mkdir(exist_ok=True)
        with open(TOKEN_CACHE, "w") as f:
            json.dump(token_data, f, indent=2)
    except Exception as e:
        log.debug(f"Token cache save failed: {e}")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "refresh":
        # python upstox_auth.py refresh
        token = get_valid_token()
        print(f"✅ Token: {token[:30]}…")

    elif cmd == "totp":
        # python upstox_auth.py totp   — generate fresh token via TOTP
        result = generate_token_via_totp()
        print(f"✅ Token: {result['access_token'][:30]}…")
        print(f"   Expires: {result['expires_at']}")

    elif cmd == "daily":
        # python upstox_auth.py daily  — called by GitHub Actions cron
        refresh_and_push_token()

    else:
        print("Usage:")
        print("  python upstox_auth.py refresh  — get/validate current token")
        print("  python upstox_auth.py totp     — generate fresh token via TOTP")
        print("  python upstox_auth.py daily    — full refresh + push to GitHub/Streamlit")
