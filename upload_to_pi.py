import paramiko
import os
import time

PI500_IP = "192.168.0.130"
username = "user"
password = "raspberry"

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(PI500_IP, username=username, password=password, timeout=5)
        sftp = ssh.open_sftp()
        
        # Upload pc_gantry_spinner_web.py
        local_web = r"I:\pc_gantry_spinner_web.py"
        remote_web = "/home/user/pc_gantry_spinner_web.py"
        sftp.put(local_web, remote_web)
        print("Uploaded pc_gantry_spinner_web.py")
        
        # Upload HTML
        os.makedirs("static", exist_ok=True)
        try:
            sftp.mkdir("/home/user/static")
        except Exception:
            pass
        sftp.put(r"I:\static\gantry_ui.html", "/home/user/static/gantry_ui.html")
        print("Uploaded gantry_ui.html")
        
        # Upload aux_servo_controller.py
        local_aux = r"I:\aux_servo_controller.py"
        remote_aux = "/home/user/aux_servo_controller.py"
        sftp.put(local_aux, remote_aux)
        print("Uploaded aux_servo_controller.py")
        
        # Upload calibration_aux.json
        if os.path.exists(r"I:\calibration_aux.json"):
            sftp.put(r"I:\calibration_aux.json", "/home/user/calibration_aux.json")
            print("Uploaded calibration_aux.json")
        
        sftp.close()

        # Restart running web server so new calibration file is loaded into memory
        ssh.exec_command("pkill -f pc_gantry_spinner_web.py")
        time.sleep(1)
        ssh.exec_command("nohup python3 /home/user/pc_gantry_spinner_web.py > /home/user/web.log 2>&1 &")
        print("Restarted pc_gantry_spinner_web.py on Pi 500.")

    except Exception as e:
        print(f"SSH Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
