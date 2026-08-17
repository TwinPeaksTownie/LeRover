import sys, time
sys.path.insert(0, '/home/user/so101/pi500')
from aux_servo_controller import AuxiliaryServoController

ctrl = AuxiliaryServoController(port='/dev/ttyACM0')
pos7 = ctrl.read_pos(7)
vol7 = ctrl.read_voltage(7)
print('HW_POS_7:', pos7)
print('HW_VOL_7:', vol7)
