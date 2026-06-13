import subprocess
import os

def run_command(cmd):
    print(f"--- Running: {cmd} ---")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    except Exception as e:
        print(f"Error: {e}")
    print("\n")

print("1. Testing ADB...")
run_command("adb devices -l")

print("2. Testing WMIC Cameras...")
run_command("wmic path Win32_PnPEntity where \"Caption like '%Camera%' or Caption like '%Webcam%'\" get Caption")

print("3. Testing PowerShell Cameras...")
run_command("powershell Get-PnpDevice -Class 'Camera'")

print("4. Testing Detailed Audio (SoundDevice)...")
try:
    import sounddevice as sd
    print(sd.query_devices())
except ImportError:
    print("sounddevice not installed")
