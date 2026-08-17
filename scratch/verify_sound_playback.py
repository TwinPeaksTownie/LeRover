import paramiko

def verify_mario_coin_sound():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print("Connecting to Pi 4B (192.168.0.86) to verify mario coin sound...")
        client.connect('192.168.0.86', username='carson', password='raspberry', timeout=5)

        commands = [
            ("CHECK MARIO SOUNDS DIR", "ls -la /home/carson/mario_sounds"),
            ("TOUCH-UI LOGS (POST REQUEST LOG)", "journalctl -u touch-ui.service -n 15 --no-pager"),
            ("PLAY COIN WAV DIRECTLY VIA PAPLAY", "paplay /home/carson/mario_sounds/smw_coin.wav 2>&1 || aplay /home/carson/mario_sounds/smw_coin.wav 2>&1")
        ]

        for title, cmd in commands:
            print(f"=== {title} ===")
            stdin, stdout, stderr = client.exec_command(cmd)
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            if out:
                print(out.strip().encode('ascii', errors='replace').decode())
            if err:
                print("STDERR:", err.strip().encode('ascii', errors='replace').decode())
            print("-" * 50)

    except Exception as e:
        print("Error verifying sound:", e)
    finally:
        client.close()

if __name__ == "__main__":
    verify_mario_coin_sound()
