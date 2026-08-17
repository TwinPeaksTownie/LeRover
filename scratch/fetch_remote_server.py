import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

stdin, stdout, stderr = client.exec_command("ls -la /home/carson/touch_ui/")
print("=== /home/carson/touch_ui/ contents ===")
print(stdout.read().decode())

stdin, stdout, stderr = client.exec_command("cat /home/carson/touch_ui/server.py")
content = stdout.read().decode()
print(f"=== /home/carson/touch_ui/server.py ({len(content)} bytes) ===")

client.close()

with open("i:/aux_servo_interface/scratch/remote_pi4b_server.py", "w") as f:
    f.write(content)
print("Saved remote server.py to scratch/remote_pi4b_server.py")
