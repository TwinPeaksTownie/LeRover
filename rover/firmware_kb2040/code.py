import board
import rp2pio
import array
import time
import digitalio
import neopixel_write
import pwmio
import busio
import analogio
import usb_cdc

# NeoPixel setup
pixel_pin = digitalio.DigitalInOut(board.NEOPIXEL)
pixel_pin.direction = digitalio.Direction.OUTPUT

def set_pixel(color):
    g, r, b = color[1], color[0], color[2]
    neopixel_write.neopixel_write(pixel_pin, bytearray([g, r, b]))

# PWM setup at 50Hz for ESCs (D6 = Left Motor, D7 = Right Motor)
motor1_pwm = pwmio.PWMOut(board.D6, frequency=50, duty_cycle=4915)
motor2_pwm = pwmio.PWMOut(board.D7, frequency=50, duty_cycle=4915)

def set_pulse_width(pwm, microseconds):
    microseconds = max(1000, min(2000, microseconds))
    duty = int((microseconds / 20000.0) * 65535)
    pwm.duty_cycle = duty

# Hardware UART Init on board.TX/RX at 115200 baud with expanded buffer
uart = None
try:
    uart = busio.UART(board.TX, board.RX, baudrate=115200, timeout=0.001, receiver_buffer_size=256)
except Exception:
    uart = None

# Analog distance sensor on A3 (pure telemetry readout only)
dist_sensor = analogio.AnalogIn(board.A3)

# PIO program for S.BUS RX on D5
program_data = array.array("H", [0x20A0, 0xEA27, 0x4001, 0x0642, 0x2020])
sm = rp2pio.StateMachine(
    program_data,
    frequency=800000,
    first_in_pin=board.D5,
    in_pin_count=1,
    auto_push=True,
    push_threshold=8,
    in_shift_right=True,
)

# Light Control Output Pin (D8)
light_pin = None
try:
    light_pin = digitalio.DigitalInOut(board.D8)
    light_pin.direction = digitalio.Direction.OUTPUT
    light_pin.value = True  # Default Idle HIGH
except Exception:
    light_pin = None

light_pulse_until = 0.0

def decode_sbus(packet):
    if len(packet) < 25 or packet[0] != 0x0F:
        return None
    channels = [0] * 16
    channels[0]  = ((packet[1]       | packet[2] << 8) & 0x07FF)
    channels[1]  = ((packet[2] >> 3  | packet[3] << 5) & 0x07FF)
    channels[2]  = ((packet[3] >> 6  | packet[4] << 2 | packet[5] << 10) & 0x07FF)
    channels[3]  = ((packet[5] >> 1  | packet[6] << 7) & 0x07FF)
    channels[4]  = ((packet[6] >> 4  | packet[7] << 4) & 0x07FF)
    channels[5]  = ((packet[7] >> 7  | packet[8] << 1 | packet[9] << 9) & 0x07FF)
    channels[6]  = ((packet[9] >> 2  | packet[10] << 6) & 0x07FF)
    channels[7]  = ((packet[10] >> 5 | packet[11] << 3) & 0x07FF)
    return channels

# State variables
packet_buf = bytearray()
last_valid_packet_time = 0.0
latest_channels = [1000] * 16
sbus_active = False

web_left_pulse = 1500
web_right_pulse = 1500
last_web_command_time = 0.0
cmd_buf = bytearray()
buf = bytearray(1)
last_print_time = 0.0
rc_switch_counter = 0

while True:
    now = time.monotonic()
    
    # 1. Read S.BUS serial data from remote controller
    while sm.in_waiting > 0:
        sm.readinto(buf)
        packet_buf.append(buf[0] ^ 0xFF)
    if len(packet_buf) > 100:
        packet_buf = packet_buf[-50:]
    while len(packet_buf) >= 25:
        if packet_buf[0] == 0x0F:
            packet = packet_buf[:25]
            if (packet[24] & 0x0F) == 0x00 or packet[24] == 0x00:
                res = decode_sbus(packet)
                if res:
                    latest_channels = res
                    last_valid_packet_time = now
                packet_buf = packet_buf[25:]
            else:
                packet_buf = packet_buf[1:]
        else:
            packet_buf = packet_buf[1:]
            
    # Hold S.BUS active status for 1.5s
    sbus_active = (now - last_valid_packet_time) < 1.5
    
    # 2. Read commands from Raspberry Pi via USB CDC or Hardware UART (CMD:left,right,slider,pulse)
    # 2a. USB CDC Console
    if usb_cdc.console and usb_cdc.console.in_waiting > 0:
        cdc_chunk = usb_cdc.console.read(usb_cdc.console.in_waiting)
        if cdc_chunk:
            cmd_buf.extend(cdc_chunk)

    # 2b. Hardware UART
    if uart:
        uart_chunk = uart.read(64)
        if uart_chunk:
            cmd_buf.extend(uart_chunk)

    if len(cmd_buf) > 128:
        cmd_buf = cmd_buf[-64:]

    while b'\n' in cmd_buf:
        idx = cmd_buf.find(b'\n')
        line_bytes = cmd_buf[:idx]
        cmd_buf = cmd_buf[idx + 1:]
        try:
            line = str(bytes(line_bytes), 'utf-8').strip()
            if line.startswith("CMD:"):
                vals = line.split(":")[1].split(",")
                web_left_pulse = int(vals[0])
                web_right_pulse = int(vals[1])
                last_web_command_time = now
                if len(vals) > 3 and int(vals[3]) == 1:
                    light_pulse_until = now + 0.20  # 200ms pulse
        except Exception:
            continue
                    
    web_active = (now - last_web_command_time) < 1.0
    
    # 3. Read distance sensor for TELEMETRY ONLY (never alters motor outputs)
    raw_dist = dist_sensor.value
    
    # 4. Debounced Mode Determination
    if sbus_active:
        if latest_channels[4] > 1000:
            rc_switch_counter = min(5, rc_switch_counter + 1)
        else:
            rc_switch_counter = max(0, rc_switch_counter - 1)
    else:
        rc_switch_counter = 0

    if rc_switch_counter >= 3:
        mode = "RC"
    else:
        mode = "WEB"
        
    # 5. Output calculation (Left & Right Drivetrain PWM)
    left_out = 1500
    right_out = 1500
    
    if mode == "RC":
        # Remote Controller Arcade Drive (Channel 1 = Steering, Channel 2 = Throttle)
        ch1 = max(172, min(1811, latest_channels[0]))
        ch2 = max(172, min(1811, latest_channels[1]))
        steering = (ch1 - 992) / 820.0
        throttle = (ch2 - 992) / 820.0
        left_val = max(-1.0, min(1.0, throttle + steering))
        right_val = max(-1.0, min(1.0, throttle - steering))
        left_out = 1500 - int(left_val * 400)
        right_out = 1500 + int(right_val * 400)
    elif mode == "WEB":
        if web_active:
            left_out = web_left_pulse
            right_out = web_right_pulse
            
    # 6. Apply PWM outputs directly to Wheel Motor ESCs (D6 & D7)
    set_pulse_width(motor1_pwm, left_out)
    set_pulse_width(motor2_pwm, right_out)
    
    # 6.5 Apply Light Control Output Pulse on D8
    is_pulsing = now < light_pulse_until
    if light_pin:
        if is_pulsing:
            light_pin.direction = digitalio.Direction.OUTPUT
            light_pin.value = False  # Short to GND (simulates button press)
        else:
            light_pin.direction = digitalio.Direction.INPUT  # High-impedance float

    # 7. NeoPixel LED Status
    if mode == "RC":
        set_pixel((0, 0, 255)) # Solid Blue = Manual Remote Control
    elif mode == "WEB":
        if web_active:
            set_pixel((0, 255, 0)) # Solid Green = Active Web/Host Drive Control
        else:
            set_pixel((0, 50, 0))  # Dim Green = Web Standby / Armed
    else:
        set_pixel((255, 0, 0)) # Red = Idle
        
    # 8. Telemetry Printout (every 100ms over USB CDC and UART)
    if (now - last_print_time) > 0.10:
        last_print_time = now
        stat_line = f"STAT:{mode},{left_out},{right_out},{1 if sbus_active else 0},{1 if web_active else 0},{latest_channels[0]},{latest_channels[1]},{latest_channels[4]},{raw_dist},{1 if is_pulsing else 0}\n"
        if usb_cdc.console:
            try:
                usb_cdc.console.write(stat_line.encode('utf-8'))
            except Exception:
                pass
        if uart:
            try:
                uart.write(stat_line.encode('utf-8'))
            except Exception:
                uart = None
