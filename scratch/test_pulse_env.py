import os
import subprocess

PULSE_ENV = dict(os.environ)
PULSE_ENV["XDG_RUNTIME_DIR"] = "/run/user/1000"
PULSE_ENV["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"

res = subprocess.run(["paplay", "/home/carson/mario_sounds/smw_coin.wav"], env=PULSE_ENV, capture_output=True, text=True)
print("Returncode:", res.returncode)
print("Stdout:", res.stdout)
print("Stderr:", res.stderr)
