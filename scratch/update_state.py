import json
from pathlib import Path

state_data = {'7': 2048, '8': 2800}

with open('/home/user/so101/gantry_state.json', 'w') as f:
    json.dump(state_data, f)

with open('/home/user/so101/pi500/gantry_state.json', 'w') as f:
    json.dump(state_data, f)

print('Updated gantry_state.json on Pi 500 to 2048.')
