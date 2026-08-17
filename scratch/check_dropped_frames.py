import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """grep -i "Teleop frame dropped" /tmp/so101_master.log | tail -n 50"""
stdin, stdout, stderr = client.exec_command(cmd)
print("DROPPED FRAMES LOG:")
print(stdout.read().decode())

cmd2 = """grep -i -E "error|warn|elbow" /tmp/so101_master.log | tail -n 50"""
stdin, stdout, stderr = client.exec_command(cmd2)
print("RECENT WARNINGS/ERRORS:")
print(stdout.read().decode())

client.close()
