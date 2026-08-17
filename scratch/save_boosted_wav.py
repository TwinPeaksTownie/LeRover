import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

sftp = client.open_sftp()
sftp.get("/home/carson/mario_sounds/smw_shell_ricochet.wav", "i:/aux_servo_interface/scratch/smw_shell_ricochet_boosted.wav")
sftp.close()
client.close()
print("Saved boosted WAV to i:/aux_servo_interface/scratch/smw_shell_ricochet_boosted.wav")
