import subprocess
import json
import time

def run_ssh(host, cmd):
    res = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=no', host, cmd], capture_output=True, text=True)
    return res.stdout.strip(), res.stderr.strip(), res.returncode

def main():
    print("=== 1. Checking Pi 500 API & Beat Studio ===")
    out, err, code = run_ssh('user@192.168.0.130', 'curl -s http://127.0.0.1:8085/api/status')
    status = json.loads(out)
    print(f"Status OK: {status.get('status')}, Hardware Connected: {status.get('hardware_connected')}, Bus Voltage: {status.get('bus_voltage')}V")
    
    print("\n=== 2. Testing Choreography Compilation on Pi 500 ===")
    test_compilation_cmd = (
        "/home/user/so101/.venv/bin/python -c \""
        "import sys, json; "
        "sys.path.insert(0, '/home/user/so101/pi500'); "
        "from beat_studio import compile_default_choreography; "
        "m = json.load(open('/home/user/so101/library/beat_bandit/manifest.json')); "
        "t_id = list(m.keys())[0]; "
        "track = m[t_id]; "
        "analysis = track.get('analysis', track); "
        "duration = float(track.get('duration', analysis.get('duration', 30.0))); "
        "res = compile_default_choreography(analysis, duration); "
        "print('Successfully compiled track ' + str(t_id) + ' (' + str(track.get('title', '')) + ')'); "
        "print('Total Blocks: ' + str(len(res['blocks']))); "
        "[print('  [' + b['id'] + '] ' + str(b['start_sec']) + 's -> ' + str(b['end_sec']) + 's | Vocal: ' + str(b['is_vocal']) + ' | Gantry: ' + str(b['gantry_mode']) + ' | Pedestal: ' + str(b['pedestal_mode']) + ' | Spine: ' + str(b['spine_pattern']) + ' | Bounce: ' + str(b['bounce_modifier']['target'])) for b in res['blocks'][:6]]"
        "\""
    )
    out, err, code = run_ssh('user@192.168.0.130', test_compilation_cmd)
    print(out)
    if err:
        print("Compilation Error:", err)

    print("\n=== 3. Checking Pi 4B Backend & Static Files ===")
    out, err, code = run_ssh('carson@192.168.0.86', 'curl -s http://127.0.0.1:8082/api/status')
    print("Pi 4B HTTP status code / response length:", len(out))

    print("\n=== 4. Checking Mac Mini Neural Daemon ===")
    out, err, code = run_ssh('twinpeakstownie@192.168.0.149', 'curl -s http://127.0.0.1:8086/api/health')
    print("Mac Mini Health:", out)

    print("\n=== 5. Testing Hardware Bi-Directional Cycle (State 2 & 3) ===")
    cycle_cmd = (
        "/home/user/so101/.venv/bin/python -c \""
        "import sys, time; "
        "sys.path.insert(0, '/home/user/so101/pi500'); "
        "from aux_servo_controller import AuxiliaryServoController; "
        "c = AuxiliaryServoController('/dev/ttyACM0'); "
        "p_orig = c.read_pos(7); "
        "print('1. Origin State -> Pos: ' + str(p_orig) + ' ticks'); "
        "c.set_torque(7, True); "
        "c.write_goal_raw(7, p_orig + 170, speed=400); "
        "time.sleep(0.6); "
        "p_a = c.read_pos(7); "
        "print('2. Target A (+15 deg / +170 ticks) -> Pos: ' + str(p_a) + ' ticks (delta: ' + str(p_a - p_orig) + ')'); "
        "c.write_goal_raw(7, p_orig - 170, speed=400); "
        "time.sleep(0.8); "
        "p_b = c.read_pos(7); "
        "print('3. Target B (-15 deg / -170 ticks) -> Pos: ' + str(p_b) + ' ticks (delta: ' + str(p_b - p_orig) + ')'); "
        "c.write_goal_raw(7, p_orig, speed=400); "
        "time.sleep(0.6); "
        "p_final = c.read_pos(7); "
        "print('4. Returned Origin -> Pos: ' + str(p_final) + ' ticks (delta from origin: ' + str(p_final - p_orig) + ')'); "
        "\""
    )
    out, err, code = run_ssh('user@192.168.0.130', cycle_cmd)
    print(out)
    if err:
        print('Cycle Error / Log:', err)


if __name__ == '__main__':
    main()
