import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=5)

stdin, stdout, stderr = client.exec_command("ps aux | grep python | grep -v grep")
print("Processes:\n" + stdout.read().decode())

stdin, stdout, stderr = client.exec_command("netstat -tlpn 2>/dev/null || ss -tlpn")
print("Listening ports:\n" + stdout.read().decode())

stdin, stdout, stderr = client.exec_command("cat /tmp/so101_master.log")
print("Master log:\n" + stdout.read().decode())

client.close()
