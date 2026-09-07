import board
import digitalio
import storage
import usb_hid
import usb_midi

# Safety override switch:
# Connect pin A0 to GND with a jumper wire to force CIRCUITPY to mount for firmware updates.
jumper = digitalio.DigitalInOut(board.A0)
jumper.direction = digitalio.Direction.INPUT
jumper.pull = digitalio.Pull.UP

if jumper.value:  # Pin is HIGH (normal operating mode, no jumper to GND)
    storage.disable_usb_drive()
    usb_hid.disable()
    usb_midi.disable()
