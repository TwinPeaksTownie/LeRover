#include <Arduino.h>
#include <SimpleFOC.h>
#include <Wire.h>

// =============================================================================
// B-G431B-ESC1 SimpleFOC Motor Control Firmware
// Motor: MAD 5010 110KV (14 pole pairs)
// Encoder: AS5600 Magnetic Encoder (Hardware I2C on PB8 SCL / PB7 SDA)
// Communication: Hardware Serial (PB3 TX / PB4 RX @ 115200 baud)
// Parameters sourced from config.json
// =============================================================================

// Motor instance
const int POLE_PAIRS = 14;
BLDCMotor motor = BLDCMotor(POLE_PAIRS);

// 6-PWM Gate Driver for B-G431B-ESC1
BLDCDriver6PWM driver = BLDCDriver6PWM(
    A_PHASE_UH, A_PHASE_UL,
    A_PHASE_VH, A_PHASE_VL,
    A_PHASE_WH, A_PHASE_WL
);

// AS5600 Magnetic Encoder via Hardware I2C
MagneticSensorI2C sensor = MagneticSensorI2C(AS5600_I2C);

// SimpleFOC Commander Interface over Hardware Serial (PB3/PB4)
Commander command = Commander(Serial);

void doTarget(char* cmd) {
    if (!motor.enabled) {
        motor.enable();
    }
    command.scalar(&motor.target, cmd);
}

void doEnable(char* cmd) {
    if (cmd[0] == '0') {
        motor.target = 0.0f;
        motor.disable();
        Serial.println("[FOC] Motor DISABLED");
    } else if (cmd[0] == '1') {
        motor.enable();
        Serial.println("[FOC] Motor ENABLED");
    } else {
        Serial.printf("[FOC] Motor State: %s\n", motor.enabled ? "ENABLED" : "DISABLED");
    }
}

void doStop(char* cmd) {
    (void)cmd;
    motor.target = 0.0f;
    motor.disable();
    Serial.println("[FOC] Emergency STOP: Motor DISABLED");
}

void doMotor(char* cmd) {
    command.motor(&motor, cmd);
}

void doVelocity(char* cmd) {
    (void)cmd;
    Serial.println(motor.shaft_velocity, 3);
}

// Timing for status heartbeat LED
unsigned long last_blink_ms = 0;

void setup() {
    // Status LED (PC6 on B-G431B-ESC1)
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, HIGH);

    // Hardware Serial on ST-Link VCP / External Header (PB3 TX, PB4 RX)
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("==================================================");
    Serial.println("   B-G431B-ESC1 SimpleFOC Motor Controller v1.0   ");
    Serial.println("   Motor: MAD 5010 110KV | Encoder: AS5600 I2C   ");
    Serial.println("   I2C Pins: SCL=PB8 | SDA=PB7 (400 kHz)          ");
    Serial.println("==================================================");

    // 1. Initialize Hardware I2C for AS5600
    Wire.setSCL(PB8);
    Wire.setSDA(PB7);
    Wire.setClock(400000);
    Wire.begin();

    // 2. Initialize Magnetic Sensor
    sensor.init(&Wire);
    motor.linkSensor(&sensor);
    Serial.println("[FOC] AS5600 Sensor linked.");

    // 3. Initialize 6-PWM Gate Driver
    driver.voltage_power_supply = 16.0f;
    driver.voltage_limit = 6.0f;
    if (!driver.init()) {
        Serial.println("[FOC] ERROR: Driver init failed!");
        return;
    }
    motor.linkDriver(&driver);
    Serial.println("[FOC] 6-PWM Driver initialized.");

    // 4. Configure Motor Control Limits & Velocity PID
    motor.voltage_limit = 6.0f;
    motor.velocity_limit = 50.0f;
    motor.voltage_sensor_align = 1.5f;

    // Velocity control mode
    motor.controller = MotionControlType::velocity;
    motor.PID_velocity.P = 0.2f;
    motor.PID_velocity.I = 2.0f;
    motor.PID_velocity.D = 0.0f;
    motor.PID_velocity.output_ramp = 1000.0f;
    motor.LPF_velocity.Tf = 0.01f;

    // 5. Initialize Motor & Field-Oriented Control
    Serial.println("[FOC] Initializing motor...");
    motor.init();

    Serial.println("[FOC] Aligning sensor and motor phases...");
    motor.initFOC();

    // 6. Safe Idle on Boot: Disable gate drivers to ensure zero current & freewheel
    motor.target = 0.0f;
    motor.disable();
    Serial.println("[FOC] Safe Idle: Gate driver de-energized. Coils freewheeling.");

    // 7. Register Serial Commander commands
    command.add('T', doTarget, "target velocity");
    command.add('E', doEnable, "enable/disable motor");
    command.add('S', doStop, "emergency stop");
    command.add('M', doMotor, "motor config");
    command.add('V', doVelocity, "velocity");

    // Silence verbose responses to prevent serial buffer congestion
    command.verbose = VerboseMode::nothing;

    Serial.println("[FOC] SimpleFOC Controller Ready.");
    Serial.println("[FOC] Commands: 'E1' (enable), 'E0'/'S' (disable), 'T<val>' (target), 'V' (velocity)\n");
}

void loop() {
    // High-frequency FOC calculation & PWM execution
    motor.loopFOC();

    // Motion control loop
    motor.move();

    // Process incoming serial commands from Host / ESP32 Gateway
    command.run();

    // Visual heartbeat on LED_BUILTIN:
    // Fast 2Hz blink when motor is active; slow 1Hz pulse when safely idle/disabled
    unsigned long blink_interval = motor.enabled ? 250 : 1000;
    if (millis() - last_blink_ms >= blink_interval) {
        last_blink_ms = millis();
        digitalToggle(LED_BUILTIN);
    }
}
