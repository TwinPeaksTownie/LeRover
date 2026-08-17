import paramiko

def check_pi4b():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print("Connecting to Pi 4B (192.168.0.86)...")
        client.connect('192.168.0.86', username='carson', password='raspberry', timeout=5)
        print("Connected!\n")

        commands = [
            ("FILES IN /home/carson/touch_ui", "ls -la /home/carson/touch_ui"),
            ("RUNNING PROCESSES", "ps aux | grep -E 'python|touch|main|audio|aplay|pulse|pipewire|wireplumber' | grep -v grep"),
            ("TOUCH-UI SERVICE STATUS", "systemctl status touch-ui.service --no-pager"),
            ("JOURNALCTL LOGS (LAST 30 LINES)", "journalctl -u touch-ui.service -n 30 --no-pager"),
            ("ALSA PLAYBACK DEVICES (aplay -l)", "aplay -l"),
            ("PULSE/PIPEWIRE SOUND CARDS (pactl list sinks short)", "pactl list sinks short 2>&1 || wpctl status 2>&1 || true"),
            ("AUDIO VOLUMES (amixer)", "amixer scontrols 2>&1 || true"),
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
        print("Error connecting/executing on Pi 4B:", e)
    finally:
        client.close()

if __name__ == "__main__":
    check_pi4b()
