import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=5)

debug_script = """
import sys
sys.path.insert(0, '/home/user/so101/pi500')
print("Importing modules...")
from robot_backend import RobotBackend
from app_manager import AppManager
from teleop_control_loop import TeleopControlApp
from servo_studio_app import ServoStudioApp
from pokeball_app import PokeballApp
from api_server import create_master_http_server
print("Modules imported.")

print("Connecting backend...")
backend = RobotBackend(port='/dev/ttyACM0', robot_id='follower')
backend.connect()
print("Backend connected.")

print("Initializing AppManager...")
app_mgr = AppManager(backend)
app_mgr.register_app(TeleopControlApp)
app_mgr.register_app(ServoStudioApp)
app_mgr.register_app(PokeballApp)
print("AppManager initialized.")

print("Creating HTTP server...")
server = create_master_http_server('0.0.0.0', 8085, backend, app_mgr)
print("HTTP server created.")
"""

sftp = client.open_sftp()
with sftp.open("/tmp/debug_step.py", "w") as f:
    f.write(debug_script)
sftp.close()

stdin, stdout, stderr = client.exec_command("fuser -k 8085/tcp 2>/dev/null; fuser -k /dev/ttyACM0 2>/dev/null; /home/user/so101/.venv/bin/python /tmp/debug_step.py")
print("STDOUT:\n" + stdout.read().decode())
print("STDERR:\n" + stderr.read().decode())

client.close()
