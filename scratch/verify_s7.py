import sys, time
sys.path.insert(0, '/home/user/so101/pi500')
from aux_servo_controller import AuxiliaryServoController

ctrl = AuxiliaryServoController(port='/dev/ttyACM0')

def read_pos(sid=7):
    with ctrl.bus_lock:
        pkt = [0xFF, 0xFF, sid, 4, 2, 56, 2]
        res = ctrl._send_and_read(pkt, expected_res_len=7)
        if res and len(res) >= 7:
            return res[5] | (res[6] << 8)
        return None

def read_offset(sid=7):
    with ctrl.bus_lock:
        pkt = [0xFF, 0xFF, sid, 4, 2, 31, 2]
        res = ctrl._send_and_read(pkt, expected_res_len=7)
        if res and len(res) >= 7:
            return (res[5] | (res[6] << 8)) & 0x0FFF
        return None

pos = read_pos(7)
off = read_offset(7)
print('READ_POS_7:', pos)
print('READ_OFFSET_7:', off)
