from pyngrok import ngrok, conf
import sys

print("Testing Ngrok...")
try:
    # Set region if needed, but default is usually fine.
    # conf.get_default().region = "in" 
    
    # Enable verbose logging
    conf.get_default().log_event_callback = lambda log: print(str(log))
    
    url = ngrok.connect(8000).public_url
    print(f"✅ Success! URL: {url}")
    ngrok.kill()
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
