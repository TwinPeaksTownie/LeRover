#!/usr/bin/env python3
"""Centralized Network Resolver and Mode Manager for SO-101 Robotics System.
Dynamically resolves target IPs prioritizing direct Ethernet bus (10.0.0.x)
with automatic fallback to Wi-Fi subnets (192.168.0.x) or mDNS hostnames.
Consumes config/network_config.json.
"""

import json
import logging
import os
import socket
import subprocess
import time
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("network_resolver")

_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_CONFIG_LOAD_TIME: float = 0.0
_IP_CACHE: Dict[str, Tuple[str, float]] = {}
CACHE_TTL_SEC: float = 2.5

DEFAULT_CONFIG = {
    "direct_ethernet": {
        "pi500_ip": "10.0.0.1",
        "pi4b_ip": "10.0.0.2",
        "subnet": "10.0.0.0/24"
    },
    "wifi_defaults": {
        "pi500_ip": "192.168.0.130",
        "pi4b_ip": "192.168.0.86",
        "mac_ip": "192.168.0.149",
        "pi500_host": "pi500.local",
        "pi4b_host": "raspberrypi.local",
        "mac_host": "mac-mini.local"
    },
    "ports": {
        "pi4b_http": 8082,
        "pi4b_video": 8083,
        "pi4b_audio_udp": 5004,
        "pi500_http": 8085,
        "mac_http": 8086,
        "teleop_zmq": 5555,
        "teleop_zmq_heartbeat": 5556
    },
    "wifi_modes": {
        "priority_list": [
            {"mode_name": "IPHONE_HOTSPOT", "ssid": "iPhone", "psk": "!H829palms", "max_retries": 2, "retry_delay_sec": 5, "is_cloud_enabled": True},
            {"mode_name": "HOME_WIFI", "ssid": "Maestas Mansion", "psk": "12290217", "max_retries": 2, "retry_delay_sec": 5, "is_cloud_enabled": True}
        ],
        "fallback_mode": {
            "mode_name": "OFFLINE_DIRECT_ETH",
            "description": "Standalone Direct Ethernet Bus (Local Only)",
            "is_cloud_enabled": False
        }
    },
    "auth": {
        "pi500_user": "user",
        "pi4b_user": "carson",
        "mac_user": "twinpeakstownie"
    }
}


def find_config_path() -> str:
    search_paths = [
        os.environ.get("NETWORK_CONFIG_PATH", ""),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "network_config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "network_config.json"),
        "/home/carson/touch_ui/config/network_config.json",
        "/home/user/so101/config/network_config.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "network_config.json"),
        "/home/carson/touch_ui/network_config.json",
        "/home/user/so101/pi500/network_config.json",
    ]
    for p in search_paths:
        if p and os.path.exists(p):
            return p
    return ""


def load_network_config() -> Dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_LOAD_TIME
    now = time.time()
    if _CONFIG_CACHE is not None and (now - _CONFIG_LOAD_TIME) < 10.0:
        return _CONFIG_CACHE

    cfg_path = find_config_path()
    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                res = dict(DEFAULT_CONFIG)
                res.update(loaded)
                _CONFIG_CACHE = res
                _CONFIG_LOAD_TIME = now
                return _CONFIG_CACHE
        except Exception as e:
            logger.warning("Failed reading %s: %s, using defaults", cfg_path, e)

    _CONFIG_CACHE = dict(DEFAULT_CONFIG)
    _CONFIG_LOAD_TIME = now
    return _CONFIG_CACHE


def is_socket_open(ip: str, port: int, timeout: float = 0.15) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def is_host_pingable(ip: str, timeout_sec: int = 1) -> bool:
    try:
        cmd = ["ping", "-n", "1", "-w", str(timeout_sec * 1000), ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", str(timeout_sec), ip]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return res.returncode == 0
    except Exception:
        return False


def resolve_target(candidates: List[Tuple[str, Optional[int]]], cache_key: str) -> str:
    now = time.time()
    if cache_key in _IP_CACHE:
        cached_ip, ts = _IP_CACHE[cache_key]
        if (now - ts) < CACHE_TTL_SEC:
            return cached_ip

    for ip, port in candidates:
        if not ip:
            continue
        if port is not None:
            if is_socket_open(ip, port, timeout=0.15):
                _IP_CACHE[cache_key] = (ip, now)
                return ip
        else:
            if is_host_pingable(ip, timeout_sec=1):
                _IP_CACHE[cache_key] = (ip, now)
                return ip

    if candidates and candidates[0][0]:
        fallback_ip = candidates[0][0]
        _IP_CACHE[cache_key] = (fallback_ip, now)
        return fallback_ip

    raise RuntimeError(f"Network resolution failed for '{cache_key}'. No candidate addresses configured.")


def get_pi500_ip(prefer_port: Optional[int] = 8085) -> str:
    cfg = load_network_config()
    eth_ip = cfg.get("direct_ethernet", {}).get("pi500_ip", "10.0.0.1")
    wifi_ip = cfg.get("wifi_defaults", {}).get("pi500_ip", "192.168.0.130")
    m_host = cfg.get("wifi_defaults", {}).get("pi500_host", "pi500.local")

    candidates: List[Tuple[str, Optional[int]]] = [
        (eth_ip, prefer_port),
        (eth_ip, 22),
        (wifi_ip, prefer_port),
        (wifi_ip, 22),
        (m_host, prefer_port),
        (eth_ip, None),
        (wifi_ip, None)
    ]
    return resolve_target(candidates, "pi500_ip")


def get_pi4b_ip(prefer_port: Optional[int] = 8082) -> str:
    cfg = load_network_config()
    eth_ip = cfg.get("direct_ethernet", {}).get("pi4b_ip", "10.0.0.2")
    wifi_ip = cfg.get("wifi_defaults", {}).get("pi4b_ip", "192.168.0.86")
    m_host = cfg.get("wifi_defaults", {}).get("pi4b_host", "raspberrypi.local")

    candidates: List[Tuple[str, Optional[int]]] = [
        (eth_ip, prefer_port),
        (eth_ip, 22),
        (wifi_ip, prefer_port),
        (wifi_ip, 22),
        (m_host, prefer_port),
        (eth_ip, None),
        (wifi_ip, None)
    ]
    return resolve_target(candidates, "pi4b_ip")


def get_mac_ip(prefer_port: Optional[int] = 8086) -> str:
    cfg = load_network_config()
    wifi_ip = cfg.get("wifi_defaults", {}).get("mac_ip", "192.168.0.149")
    m_host = cfg.get("wifi_defaults", {}).get("mac_host", "mac-mini.local")

    candidates: List[Tuple[str, Optional[int]]] = [
        (wifi_ip, prefer_port),
        (wifi_ip, 22),
        (m_host, prefer_port),
        (wifi_ip, None)
    ]
    return resolve_target(candidates, "mac_ip")


def get_pc_ip(prefer_port: Optional[int] = 8058) -> str:
    cfg = load_network_config()
    wifi_ip = cfg["wifi_defaults"]["pc_ip"]
    m_host = cfg["wifi_defaults"]["pc_host"]

    candidates: List[Tuple[str, Optional[int]]] = [
        (wifi_ip, prefer_port),
        (m_host, prefer_port),
        (wifi_ip, None)
    ]
    return resolve_target(candidates, "pc_ip")


def get_ports() -> Dict[str, int]:
    cfg = load_network_config()
    return cfg.get("ports", DEFAULT_CONFIG["ports"])


def get_active_connection_mode() -> Dict[str, Any]:
    """Determines the current operating connection mode."""
    active_ssid = ""
    if os.name != 'nt':
        try:
            res = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], capture_output=True, text=True, timeout=1.5)
            for line in res.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 3 and parts[1] == "802-11-wireless" and "wlan" in parts[2]:
                    active_ssid = parts[0]
                    break
        except Exception:
            pass

    cfg = load_network_config()
    modes = cfg.get("wifi_modes", {}).get("priority_list", [])

    for m in modes:
        if active_ssid and (m.get("ssid") == active_ssid or active_ssid in m.get("ssid", "")):
            return {
                "mode": m.get("mode_name", "ONLINE_WIFI"),
                "ssid": active_ssid,
                "is_cloud_enabled": m.get("is_cloud_enabled", True),
                "is_offline": False,
                "pi500_ip": get_pi500_ip(),
                "pi4b_ip": get_pi4b_ip()
            }

    if active_ssid:
        return {
            "mode": "CUSTOM_WIFI",
            "ssid": active_ssid,
            "is_cloud_enabled": True,
            "is_offline": False,
            "pi500_ip": get_pi500_ip(),
            "pi4b_ip": get_pi4b_ip()
        }

    return {
        "mode": "OFFLINE_DIRECT_ETH",
        "ssid": None,
        "is_cloud_enabled": False,
        "is_offline": True,
        "pi500_ip": get_pi500_ip(),
        "pi4b_ip": get_pi4b_ip()
    }


if __name__ == "__main__":
    print("Pi 500 IP:", get_pi500_ip())
    print("Pi 4B IP:", get_pi4b_ip())
    print("Mac IP:", get_mac_ip())
    print("Ports:", get_ports())
    print("Active Mode:", get_active_connection_mode())
