import json
import threading
import time
import socket
import logging

# Kivy Imports
import kivy
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, Line
from kivy.utils import get_color_from_hex

# WebSocket
import websocket # pip install websocket-client

# --- CONFIG ---
SERVER_IP = "10.133.83.26" # AUTO-DETECTED
PORT = 8000
DEVICE_ID = "android_gui_01"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("JarvisNode")

class JarvisUI(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.orientation = 'vertical'
        self.padding = 20
        self.spacing = 15
        
        # Background
        with self.canvas.before:
            Color(0, 0, 0, 1) # Black
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

        # 1. HEADER (Status)
        self.header = BoxLayout(size_hint_y=0.15)
        self.status_label = Label(
            text="DISCONNECTED", 
            color=(1, 0, 0, 1), 
            font_size='24sp', 
            bold=True
        )
        self.header.add_widget(self.status_label)
        self.add_widget(self.header)

        # 2. LOG CONSOLE
        self.scroll = ScrollView(size_hint_y=0.45, do_scroll_x=False)
        self.console = Label(
            text="[System Initialized]...", 
            size_hint_y=None, 
            markup=True,
            halign='left', 
            valign='top',
            color=(0, 0.8, 0, 1) # Matrix Green
        )
        self.console.bind(texture_size=self.console.setter('size'))
        self.console.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        self.scroll.add_widget(self.console)
        
        # Console Background
        with self.scroll.canvas.before:
            Color(0.1, 0.1, 0.1, 1)
            Rectangle(size=self.scroll.size, pos=self.scroll.pos)
            
        self.add_widget(self.scroll)

        # 3. CONTROLS (Buttons)
        self.controls = GridLayout(cols=2, spacing=10, size_hint_y=0.3)
        
        btn_style = {'background_color': (0.1, 0.1, 0.3, 1), 'color': (0, 1, 1, 1), 'bold': True}
        
        self.btn_ping = Button(text="PING BRAIN", **btn_style)
        self.btn_ping.bind(on_press=self.send_ping)
        self.controls.add_widget(self.btn_ping)

        self.btn_popup = Button(text="SEND POPUP TO PC", **btn_style)
        self.btn_popup.bind(on_press=self.cmd_popup_pc)
        self.controls.add_widget(self.btn_popup)
        
        self.btn_lock = Button(text="LOCK PC (Future)", **btn_style) # Future capability
        self.controls.add_widget(self.btn_lock)
        
        self.btn_reconnect = Button(text="RECONNECT", background_color=(0, 0.5, 0, 1))
        self.btn_reconnect.bind(on_press=self.app.connect_ws)
        self.controls.add_widget(self.btn_reconnect)

        self.add_widget(self.controls)
        
        # 4. IP INPUT (Bottom)
        self.ip_box = BoxLayout(size_hint_y=0.1, spacing=10)
        self.ip_input = TextInput(text=SERVER_IP, multiline=False, foreground_color=(1,1,1,1), background_color=(0.2,0.2,0.2,1))
        self.ip_input.bind(text=self.update_ip)
        self.ip_box.add_widget(Label(text="IP:", size_hint_x=0.2))
        self.ip_box.add_widget(self.ip_input)
        self.add_widget(self.ip_box)

    def _update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def log(self, msg):
        Clock.schedule_once(lambda dt: self._append_log(msg))

    def _append_log(self, msg):
        self.console.text += f"\n> {msg}"
        if len(self.console.text) > 5000:
            self.console.text = self.console.text[-5000:]
            
    def set_status(self, status, color):
        Clock.schedule_once(lambda dt: self._set_status_safe(status, color))
        
    def _set_status_safe(self, status, color):
        self.status_label.text = status
        self.status_label.color = color

    def update_ip(self, instance, value):
        global SERVER_IP
        SERVER_IP = value

    def send_ping(self, instance):
        self.app.send_json({"type": "ping", "msg": "Hello from GUI"})
        self.log("Sent Ping")

    def cmd_popup_pc(self, instance):
        # We broadcast a request, or send to Brain to route to PC
        # For now, let's assume we send a 'request' to Brain
        msg = {
            "type": "command_request", 
            "target": "pc", 
            "action": "popup", 
            "params": {"text": "Hello from Android App!"}
        }
        self.app.send_json(msg)
        self.log("Requesting Popup on PC...")

class JarvisApp(App):
    def build(self):
        self.ws = None
        self.ws_thread = None
        self.running = True
        self.ui = JarvisUI(self)
        return self.ui

    def on_start(self):
        self.connect_ws(None)

    def on_stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def connect_ws(self, instance):
        if self.ws_thread and self.ws_thread.is_alive():
            return # Already trying
        
        self.ui.log(f"Connecting to {SERVER_IP}...")
        self.ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self.ws_thread.start()

    def _ws_loop(self):
        url = f"ws://{SERVER_IP}:{PORT}/ws/{DEVICE_ID}"
        # websocket.enableTrace(True)
        self.ws = websocket.WebSocketApp(url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.ws.run_forever()

    def on_open(self, ws):
        self.ui.set_status("CONNECTED", (0, 1, 0, 1))
        self.ui.log("WebSocket Opened")
        
        # Register
        reg = {
            "type": "register",
            "device_id": DEVICE_ID,
            "name": "Android GUI",
            "device_type": "mobile",
            "capabilities": ["gui", "vibrate", "toast"],
            "battery": 90,
            "os": "Android"
        }
        ws.send(json.dumps(reg))
        self.ui.log("Sent Registration")

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            self.ui.log(f"Recv: {data.get('type')}")
            
            if data.get("type") == "command":
                self.handle_command(data)
                
        except Exception as e:
            self.ui.log(f"Msg Error: {e}")

    def on_error(self, ws, error):
        self.ui.log(f"Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.ui.set_status("DISCONNECTED", (1, 0, 0, 1))
        self.ui.log("Connection Closed")

    def send_json(self, data):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps(data))
        else:
            self.ui.log("Cannot Send: Offline")

    def handle_command(self, data):
        cmd_id = data.get("command_id")
        action = data.get("action")
        self.ui.log(f"EXEC: {action}")
        
        status = "success"
        output = "Executed GUI Action"
        
        # Integration with Plyer for native features
        try:
            if action == "vibrate":
                try:
                    from plyer import vibrator
                    vibrator.vibrate(1)
                    output = "Vibration success"
                except:
                    output = "Vibration simulated (No plyer)"
                    
        except Exception as e:
            status = "error"
            output = str(e)

        # Send Result
        res = {
            "type": "result", 
            "command_id": cmd_id, 
            "status": status, 
            "output": output
        }
        self.send_json(res)

if __name__ == '__main__':
    JarvisApp().run()
