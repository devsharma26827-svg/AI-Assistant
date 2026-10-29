"""
diagnose_gemini_live.py - Standalone Network & Handshake Diagnostic Tool for Gemini Realtime.

Tests the Gemini Realtime WebSocket connection directly via google-genai, bypassing LiveKit,
to verify network stability, TLS handshake timing, latency, and session establishment.
Runs 5 sequential connection attempts and outputs a detailed performance and reliability summary.
"""

import os
import sys
import time
import asyncio
from dotenv import load_dotenv

# Ensure utf-8 encoding on Windows console
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load local environment
load_dotenv(".env.local", override=True)
load_dotenv(".env", override=False)

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview").strip()
NUM_ATTEMPTS = 5

if not API_KEY:
    print("\n[!] Error: Neither GEMINI_API_KEY nor GOOGLE_API_KEY found in .env.local or environment.")
    print("Please set your Gemini API key and try again.\n")
    sys.exit(1)

# Ensure certifi CA bundle is used on Windows
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from google import genai
from google.genai import types


async def run_single_attempt(attempt_idx: int) -> dict:
    """Run a single handshake and roundtrip test against Gemini Live."""
    print(f"\n[Attempt {attempt_idx}/{NUM_ATTEMPTS}] Connecting to {MODEL}...")
    
    client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1alpha"})
    
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
    )

    t_start = time.perf_counter()
    handshake_ms = 0.0
    first_response_ms = 0.0
    success = False
    error_msg = None

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            t_connected = time.perf_counter()
            handshake_ms = (t_connected - t_start) * 1000.0
            print(f"  [OK] Handshake established in {handshake_ms:.1f} ms")

            # Send a minimal test message
            t_send = time.perf_counter()
            test_content = types.Content(
                role="user",
                parts=[types.Part.from_text(text="Respond with the single word 'Ready'.")]
            )
            await session.send_client_content(turns=[test_content], turn_complete=True)

            # Receive the first response chunk
            async for resp in session.receive():
                if resp.server_content and resp.server_content.model_turn:
                    t_first_byte = time.perf_counter()
                    first_response_ms = (t_first_byte - t_send) * 1000.0
                    print(f"  [OK] First response received in {first_response_ms:.1f} ms (Total turn: {(t_first_byte - t_start)*1000:.1f} ms)")
                    success = True
                    break

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_msg = str(exc)
        print(f"  [FAIL] Connection failed: {error_msg}")

    return {
        "attempt": attempt_idx,
        "success": success,
        "handshake_ms": handshake_ms if success else None,
        "first_response_ms": first_response_ms if success else None,
        "total_ms": (handshake_ms + first_response_ms) if success else None,
        "error": error_msg,
    }


async def main():
    print("=" * 70)
    print("   CYNTHIA - GEMINI REALTIME DIAGNOSTIC TOOL")
    print("=" * 70)
    print(f"Target Model:     {MODEL}")
    masked_key = f"{API_KEY[:8]}...{API_KEY[-4:]}" if len(API_KEY) > 12 else "***"
    print(f"API Key:          {masked_key}")
    print(f"Test Rounds:      {NUM_ATTEMPTS}")
    print("=" * 70)

    results = []

    try:
        for i in range(1, NUM_ATTEMPTS + 1):
            res = await run_single_attempt(i)
            results.append(res)
            if i < NUM_ATTEMPTS:
                # Short breather between attempts
                await asyncio.sleep(0.5)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n\n[!] Diagnostic interrupted by user (Ctrl+C). Generating partial report...")

    # Summary Report
    successful_runs = [r for r in results if r["success"]]
    total_runs = len(results)
    success_rate = (len(successful_runs) / total_runs * 100.0) if total_runs > 0 else 0.0

    print("\n" + "=" * 70)
    print("                     DIAGNOSTIC SUMMARY REPORT")
    print("=" * 70)
    print(f"Total Attempts:      {total_runs}")
    print(f"Successful:          {len(successful_runs)} / {total_runs} ({success_rate:.1f}%)")

    if successful_runs:
        handshakes = [r["handshake_ms"] for r in successful_runs]
        responses = [r["first_response_ms"] for r in successful_runs]
        totals = [r["total_ms"] for r in successful_runs]

        avg_hs = sum(handshakes) / len(handshakes)
        min_hs = min(handshakes)
        max_hs = max(handshakes)

        avg_resp = sum(responses) / len(responses)
        avg_tot = sum(totals) / len(totals)

        print(f"Handshake Latency:   Avg: {avg_hs:.1f} ms  |  Min: {min_hs:.1f} ms  |  Max: {max_hs:.1f} ms")
        print(f"Response Latency:    Avg: {avg_resp:.1f} ms")
        print(f"Total Turn Latency:  Avg: {avg_tot:.1f} ms")

        # Network health assessment
        print("-" * 70)
        if success_rate == 100.0 and avg_hs < 2500:
            print("[+] Network Status: EXCELLENT. Gemini Live connection is stable and responsive.")
        elif success_rate >= 80.0:
            print("[~] Network Status: MODERATE. Occasional drops or higher latency observed.")
            print("    The self-healing supervisor and ResilientRealtimeModel will absorb these drops.")
        else:
            print("[!] Network Status: UNSTABLE. High packet loss or frequent handshake failures.")
            print("    Consider switching hotspot band (5GHz vs 2.4GHz) or checking mobile signal.")
    else:
        print("[!] Network Status: CRITICAL. 0% success rate. Gemini Live handshake failed completely.")
        for r in results:
            if r["error"]:
                print(f"    - Attempt {r['attempt']}: {r['error']}")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting diagnose_gemini_live.py.")
