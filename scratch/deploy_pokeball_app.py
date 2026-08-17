import paramiko
import os

PI500_IP = "192.168.0.130"
LOCAL_FILE = "pi500/pokeball_app.py"
REMOTE_FILE = "/home/user/so101/pi500/pokeball_app.py"

def deploy_to_pi500():
    print(f"Deploying {LOCAL_FILE} to Pi 500 ({PI500_IP}:{REMOTE_FILE})...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(PI500_IP, username="user", timeout=5)
        sftp = client.open_sftp()
        sftp.put(LOCAL_FILE, REMOTE_FILE)
        sftp.close()
        print("SFTP Transfer Successful!")

        # Verify deployed file content line
        stdin, stdout, stderr = client.exec_command(f"grep -n 'smw_vine' {REMOTE_FILE}")
        out = stdout.read().decode('utf-8', errors='replace')
        print("Remote File Verification (grep smw_vine):")
        print(out.strip())

    except Exception as e:
        print("Deployment Error:", e)
    finally:
        client.close()

if __name__ == "__main__":
    deploy_to_pi500()
