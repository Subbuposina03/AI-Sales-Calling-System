"""
Auto-Tunnel and Twilio Webhook Sync Manager
Eliminates the need for manual ngrok terminal commands.
When running locally:
1. Detects existing ngrok tunnel or automatically spawns local ngrok.exe in the background.
2. Extracts public HTTPS URL.
3. Automatically syncs Twilio phone number voice webhook to the new public URL.
"""

import os
import subprocess
import time
import urllib.request
import json
import atexit

ngrok_process = None


def get_active_ngrok_url():
    """Check if an ngrok tunnel is already active on localhost:4040."""
    try:
        req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            for tunnel in data.get("tunnels", []):
                public_url = tunnel.get("public_url", "")
                if public_url.startswith("https://"):
                    return public_url
                elif public_url.startswith("http://"):
                    return public_url.replace("http://", "https://")
    except Exception:
        pass
    return None


def sync_twilio_webhook(public_url):
    """
    Automatically update Twilio phone number voice webhook to public_url/voice
    so the user never has to log in and change URLs in Twilio Console manually.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()

    if not all([account_sid, auth_token, from_number, public_url]):
        return False

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        webhook_target = f"{public_url.rstrip('/')}/voice"

        incoming_numbers = client.incoming_phone_numbers.list(phone_number=from_number)
        if incoming_numbers:
            incoming_numbers[0].update(
                voice_url=webhook_target,
                voice_method="POST"
            )
            print(f"✅ [Twilio Auto-Sync] Phone number {from_number} voice webhook set to: {webhook_target}")
            return True
    except Exception as exc:
        print(f"ℹ️ [Twilio Auto-Sync] Notice: Webhook sync via API skipped ({exc})")
    return False


def start_auto_tunnel(port=5000):
    """
    Automatically start ngrok in the background if running locally and PUBLIC_BASE_URL is not set.
    Returns the public HTTPS URL (e.g. 'https://xxxx.ngrok-free.dev').
    """
    global ngrok_process

    # If running on Render or other cloud platform, don't use ngrok
    if os.getenv("RENDER") or os.getenv("DYNO") or os.getenv("K_SERVICE"):
        return os.getenv("PUBLIC_BASE_URL", "")

    # Check if a non-ngrok permanent public URL is provided
    existing_url = os.getenv("PUBLIC_BASE_URL", "").strip()
    if existing_url and "onrender.com" in existing_url:
        return existing_url

    # Check if ngrok is already running on port 4040
    active_url = get_active_ngrok_url()
    if active_url:
        print(f"🔗 [Auto-Tunnel] Detected existing ngrok tunnel: {active_url}")
        os.environ["PUBLIC_BASE_URL"] = active_url
        sync_twilio_webhook(active_url)
        return active_url

    # Locate ngrok.exe in the workspace directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ngrok_path = os.path.join(base_dir, "ngrok.exe")
    if not os.path.exists(ngrok_path):
        ngrok_path = "ngrok"

    # Set auth token if configured in .env
    token = os.getenv("NGROK_AUTH_TOKEN", "").strip()
    if token:
        try:
            subprocess.run([ngrok_path, "config", "add-authtoken", token], capture_output=True, timeout=5)
        except Exception:
            pass

    # Launch ngrok in the background without creating a new window
    try:
        print(f"🚀 [Auto-Tunnel] Spawning background ngrok tunnel for port {port}...")
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        ngrok_process = subprocess.Popen(
            [ngrok_path, "http", str(port), "--log=stdout"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo
        )

        def cleanup():
            global ngrok_process
            if ngrok_process and ngrok_process.poll() is None:
                ngrok_process.terminate()

        atexit.register(cleanup)

        # Wait for tunnel initialization
        for _ in range(12):
            time.sleep(0.5)
            url = get_active_ngrok_url()
            if url:
                print(f"🎉 [Auto-Tunnel] Public HTTPS Webhook established: {url}")
                os.environ["PUBLIC_BASE_URL"] = url
                sync_twilio_webhook(url)
                return url

    except Exception as exc:
        print(f"ℹ️ [Auto-Tunnel] Could not auto-launch ngrok ({exc})")

    return os.getenv("PUBLIC_BASE_URL", "")
