import paramiko
import os
import time

PI4B_IP = "192.168.0.86"
PI500_IP = "192.168.0.130"

def deploy_pi4b():
    print("=== Deploying Git Updates to Pi 4B (192.168.0.86) ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        try:
            ssh.connect(PI4B_IP, username='carson', timeout=5)
        except Exception:
            ssh.connect(PI4B_IP, username='carson', password='raspberry', timeout=5)
        
        # Git pull in /home/carson/aux_servo_interface
        stdin, stdout, stderr = ssh.exec_command("cd /home/carson/aux_servo_interface && git fetch origin && git reset --hard origin/main")
        print("Git Pull STDOUT:", stdout.read().decode())

        # Restart touchscreen_ui.py
        ssh.exec_command("fuser -k 8082/tcp || pkill -9 -f touchscreen_ui.py || true")
        time.sleep(1.0)
        ssh.exec_command("nohup python3 /home/carson/aux_servo_interface/touchscreen_ui.py > /home/carson/aux_servo_interface/touchscreen_ui.log 2>&1 &")
        print("Restarted touchscreen_ui.py on Pi 4B.")

        ssh.close()
    except Exception as e:
        print(f"Pi 4B Deploy Error: {e}")

def deploy_pi500():
    print("\n=== Deploying Updates to Pi 500 (192.168.0.130) ===")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        try:
            ssh.connect(PI500_IP, username='user', timeout=5)
        except Exception:
            ssh.connect(PI500_IP, username='user', password='raspberry', timeout=5)

        sftp = ssh.open_sftp()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        for fname in ["aux_daemon.py", "aux_servo_controller.py", "pokeball_teleop_driver.py"]:
            local_p = os.path.join(script_dir, fname)
            if os.path.exists(local_p):
                sftp.put(local_p, f"/home/user/{fname}")
                print(f"Uploaded {fname} to Pi 500")

        os.makedirs("static", exist_ok=True)
        try: sftp.mkdir("/home/user/static")
        except Exception: pass
        
        local_html = os.path.join(script_dir, "static", "gantry_ui.html")
        if os.path.exists(local_html):
            sftp.put(local_html, "/home/user/static/gantry_ui.html")
            print("Uploaded gantry_ui.html to Pi 500")

        sftp.close()
        ssh.exec_command("sudo systemctl restart aux_daemon.service || (pkill -f aux_daemon.py; nohup python3 /home/user/aux_daemon.py > /home/user/aux_daemon.log 2>&1 &)")
        print("Restarted aux_daemon.py on Pi 500.")

        ssh.close()
    except Exception as e:
        print(f"Pi 500 Deploy Error: {e}")

def main():
    deploy_pi4b()
    deploy_pi500()

if __name__ == "__main__":
    main()
