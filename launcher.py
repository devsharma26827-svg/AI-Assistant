import os
import time
import socket
import qrcode
import threading
import subprocess
import webbrowser

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def start_ecosystem():
    print("🚀 Starting Jarvis Ecosystem...")
    
    # Start Server (Hidden/Minimised)
    # We use 'start' to run in separate windows but minimized if possible, or just standard separate windows
    subprocess.run('start "Jarvis Brain" /min cmd /k ".\\venv311\\Scripts\\python.exe device_server.py"', shell=True)
    time.sleep(2)
    
    # Start PC Client
    subprocess.run('start "PC Client" /min cmd /k ".\\venv311\\Scripts\\python.exe pc_client.py"', shell=True)
    
    # Generate Local QR Logic
    ip = get_local_ip()
    local_url = f"http://{ip}:8000/mobile"
    
    print("\n" + "="*40)
    print("🏠 LOCAL CONNECTION (Same WiFi)")
    print("="*40)
    print(f"URL: {local_url}")
    qr_local = qrcode.QRCode()
    qr_local.add_data(local_url)
    qr_local.print_ascii(invert=True)
    
    # Generate Remote QR Logic (Ngrok)
    try:
        from pyngrok import ngrok
        # Open a HTTP tunnel on the default port 8000
        public_url = ngrok.connect(8000).public_url
        mobile_public_url = f"{public_url}/mobile"
        
        print("\n" + "="*40)
        print("🌍 REMOTE CONNECTION (4G/5G/Anywhere)")
        print("="*40)
        print(f"URL: {mobile_public_url}")
        print("(Note: Ngrok sessions expire. Restart launcher to renew.)")
        
        qr_remote = qrcode.QRCode()
        qr_remote.add_data(mobile_public_url)
        qr_remote.print_ascii(invert=True)
    except Exception as e:
        print(f"\n❌ Remote Tunnel Failed: {e}")
        error_str = str(e)
        if "ERR_NGROK_108" in error_str or "account" in error_str.lower():
            print("\n" + "!"*40)
            print("MISSING NGROK AUTH TOKEN")
            print("To use Remote Access, you need a free Ngrok account.")
            print("1. Go to https://dashboard.ngrok.com/get-started/your-authtoken")
            print("2. Copy your token.")
            print("!"*40 + "\n")
            
            token = input("Paste your Authtoken here (or press Enter to skip): ").strip()
            if token:
                try:
                    from pyngrok import ngrok, conf
                    ngrok.set_auth_token(token)
                    print("✅ Token saved! Retrying connection...")
                    
                    # Retry connect
                    public_url = ngrok.connect(8000).public_url
                    mobile_public_url = f"{public_url}/mobile"
                    print(f"URL: {mobile_public_url}")
                    
                    qr_remote = qrcode.QRCode()
                    qr_remote.add_data(mobile_public_url)
                    qr_remote.print_ascii(invert=True)
                except Exception as ex:
                    print(f"Retry failed: {ex}")
        else:
             print("Run 'ngrok config add-authtoken <token>' manually if needed.")
    
    print("\n✅ System Running. Press Ctrl+C to stop.")

if __name__ == "__main__":
    start_ecosystem()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting launcher...")

