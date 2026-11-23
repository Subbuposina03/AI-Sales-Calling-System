"""
Call Management Module for AI Sales Calling Agent
Supports:
1. Reusable function `make_outbound_call(...)` for Flask backend
2. CLI invocation for testing: `python call.py <phone_number>`
3. Simulation mode for testing without placing real Twilio calls
"""

import os
import re
import sys
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv()


def normalize_phone_number(phone: str, default_country_code: str = "+91") -> str:
    """
    Sanitize and normalize phone number into standard E.164 format.
    E.g. "9876543210" with default "+91" -> "+919876543210"
    "+91 98765 43210" -> "+919876543210"
    """
    if not phone:
        return ""
    # Strip spaces, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if not cleaned.startswith("+"):
        if cleaned.startswith("0"):
            cleaned = cleaned[1:]
        cleaned = f"{default_country_code}{cleaned}"
    return cleaned


def validate_e164_phone(phone: str) -> bool:
    """
    Validate that phone number conforms to ITU E.164 format:
    Starts with '+', followed by country code and 7-15 digits.
    """
    pattern = r"^\+[1-9]\d{7,14}$"
    return bool(re.match(pattern, phone))


def make_outbound_call(
    to_phone_number: str,
    webhook_url: str = None,
    simulate: bool = None
) -> dict:
    """
    Initiate an outbound voice call to the target phone number.

    Args:
        to_phone_number: Destination phone number (E.164 format)
        webhook_url: Public webhook URL for Twilio to reach /voice.
                     If None, resolves from PUBLIC_BASE_URL or VOICE_WEBHOOK_URL.
        simulate: If True, simulates the call without dialing Twilio.
                  If None, reads SIMULATE_MODE from environment.

    Returns:
        dict: {
            "success": bool,
            "call_sid": str or None,
            "status": str ("started", "simulated", "failed"),
            "message": str,
            "error_code": int or None
        }
    """
    # Load configuration from environment
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    env_webhook = os.getenv("VOICE_WEBHOOK_URL", "").strip()

    # Determine effective webhook URL
    effective_webhook = webhook_url
    if not effective_webhook:
        if public_base_url:
            effective_webhook = f"{public_base_url}/voice"
        elif env_webhook:
            effective_webhook = env_webhook

    # Determine simulation mode
    if simulate is None:
        simulate = os.getenv("SIMULATE_MODE", "").strip().lower() in ("1", "true", "yes")

    # Clean and validate phone number
    normalized_number = normalize_phone_number(to_phone_number)
    if not validate_e164_phone(normalized_number):
        return {
            "success": False,
            "call_sid": None,
            "status": "failed",
            "message": f"Invalid phone number format: '{to_phone_number}'. Must include country code, e.g. +919876543210.",
            "error_code": 400
        }

    # Verify webhook URL is present
    if not effective_webhook:
        return {
            "success": False,
            "call_sid": None,
            "status": "failed",
            "message": "Public webhook URL is not configured. Set PUBLIC_BASE_URL or VOICE_WEBHOOK_URL in environment.",
            "error_code": 500
        }

    # Simulation mode
    if simulate:
        print(f"[SIMULATION] Outbound call simulated from {from_number or '+10000000000'} to {normalized_number}")
        print(f"[SIMULATION] Target webhook: {effective_webhook}")
        # Optionally probe the webhook if reachable
        webhook_resp_body = None
        try:
            form_data = urllib.parse.urlencode({
                "CallSid": "SIMULATED_CALL_SID_12345",
                "From": normalized_number,
                "To": from_number or "+10000000000",
                "CallStatus": "in-progress",
            }).encode("utf-8")
            req = urllib.request.Request(
                effective_webhook,
                data=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                webhook_resp_body = resp.read().decode("utf-8")
        except Exception as exc:
            # If webhook is local or not answering, simulation still succeeds
            webhook_resp_body = f"Webhook probe: {exc}"

        return {
            "success": True,
            "call_sid": "SIMULATED_CALL_SID_12345",
            "status": "simulated",
            "message": f"Simulation successful: call simulated to {normalized_number}.",
            "webhook_preview": webhook_resp_body,
            "error_code": None
        }

    # Check Twilio credentials for real call
    if not account_sid or not auth_token or not from_number:
        missing = []
        if not account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not from_number:
            missing.append("TWILIO_FROM_NUMBER")
        return {
            "success": False,
            "call_sid": None,
            "status": "failed",
            "message": f"Missing Twilio credentials: {', '.join(missing)}. Please configure them in environment variables.",
            "error_code": 500
        }

    # Initiate real outbound call via Twilio Voice API
    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        call = client.calls.create(
            to=normalized_number,
            from_=from_number,
            url=effective_webhook,
            method="POST"
        )
        return {
            "success": True,
            "call_sid": call.sid,
            "status": "started",
            "message": f"Call initiated successfully to {normalized_number}. Your phone should ring shortly!",
            "error_code": None
        }
    except Exception as exc:
        err_msg = str(exc)
        code = getattr(exc, "code", None)

        # Handle specific common Twilio errors with user-friendly messages
        if code == 21219 or "unverified" in err_msg.lower():
            user_friendly = (
                "Twilio Trial Restriction (Error 21219): Trial accounts can only call numbers "
                "verified in your Twilio Console (Phone Numbers > Verified Caller IDs). "
                "Please verify this phone number in your Twilio account or upgrade to full account."
            )
        elif code == 21614:
            user_friendly = "Twilio Error (21614): This destination number cannot receive voice calls."
        elif code == 20003:
            user_friendly = "Twilio Authentication Error (20003): Invalid Account SID or Auth Token."
        elif code == 21214:
            user_friendly = "Twilio Error (21214): 'To' phone number cannot be reached."
        else:
            user_friendly = f"Failed to initiate Twilio call: {err_msg}"

        return {
            "success": False,
            "call_sid": None,
            "status": "failed",
            "message": user_friendly,
            "error_code": code or 500
        }


# ==========================================
# CLI Execution Support (Backward Compatible)
# ==========================================
if __name__ == "__main__":
    simulate_flag = "--simulate"
    args = [arg for arg in sys.argv[1:] if arg != simulate_flag]
    cli_simulate = simulate_flag in sys.argv or os.getenv("SIMULATE_MODE", "").lower() in ("1", "true", "yes")

    if len(args) > 0:
        target_phone = args[0].strip()
    else:
        default_number = os.getenv("STUDENT_PHONE_NUMBER", "").strip()
        if default_number:
            entered = input(f"Enter the phone number to call [{default_number}]: ").strip()
            target_phone = entered or default_number
        else:
            target_phone = input("Enter the phone number to call (with country code, e.g. +919876543210): ").strip()

    result = make_outbound_call(target_phone, simulate=cli_simulate)
    print("\n" + "=" * 50)
    print(f"Result: {result['status'].upper()}")
    print(f"Message: {result['message']}")
    if result.get("call_sid"):
        print(f"Call SID: {result['call_sid']}")
    print("=" * 50 + "\n")
    if not result["success"]:
        sys.exit(1)
