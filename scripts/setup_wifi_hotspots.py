#!/usr/bin/env python3
"""Configures trusted Wi-Fi networks (e.g. iPhone Hotspot) on Pi 4B and Pi 500 using NetworkManager."""

import json
import os
import sys
import paramiko

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "wifi_networks.json")

HOSTS = [
    {"name": "Pi 4B", "ip": "192.168.0.86", "user": "carson", "pass": "raspberry", "sudo": True},
]


def load_wifi_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Config file not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def configure_host(host, networks):
    print(f"\n--- Configuring Wi-Fi on {host['name']} ({host['ip']}) ---")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if host["pass"]:
            client.connect(host["ip"], username=host["user"], password=host["pass"], timeout=5)
        else:
            client.connect(host["ip"], username=host["user"], timeout=5)
    except Exception as e:
        print(f"[OFFLINE] Could not connect to {host['name']}: {e} (Host is powered off)")
        return False

    for net in networks:
        ssid = net["ssid"]
        psk = net["psk"]
        priority = net.get("priority", 10)
        print(f"  Adding network profile: SSID='{ssid}', Priority={priority}")

        # Delete existing profile if present
        del_cmd = f"sudo nmcli connection delete '{ssid}' 2>/dev/null || true"
        if host["sudo"] and host["pass"]:
            del_cmd = f"echo {host['pass']} | sudo -S nmcli connection delete '{ssid}' 2>/dev/null || true"
        client.exec_command(del_cmd)

        # Add Wi-Fi connection profile with autoconnect
        add_cmd = (
            f"sudo nmcli connection add type wifi ifname wlan0 con-name '{ssid}' ssid '{ssid}' "
            f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{psk}' "
            f"connection.autoconnect yes connection.autoconnect-priority {priority}"
        )
        if host["sudo"] and host["pass"]:
            add_cmd = (
                f"echo {host['pass']} | sudo -S nmcli connection add type wifi ifname wlan0 con-name '{ssid}' ssid '{ssid}' "
                f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{psk}' "
                f"connection.autoconnect yes connection.autoconnect-priority {priority}"
            )

        _, stdout, stderr = client.exec_command(add_cmd)
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        if out:
            print(f"  [OK] {out}")
        if err and "password" not in err.lower():
            print(f"  [WARNING] {err}")

    client.close()
    return True


def main():
    config = load_wifi_config()
    networks = config.get("networks", [])
    if not networks:
        print("No networks defined in config.")
        return

    print(f"Found {len(networks)} network(s) in configuration.")
    for host in HOSTS:
        configure_host(host, networks)


if __name__ == "__main__":
    main()
