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
_HOTSPOT_CACHE: Optional[Tuple[bool, float]] = None

DEFAULT_CONFIG: Dict[str, Any] = {
    "topology_mode": "STANDALONE_PI4B",
    "endpoints": {
        "master_backend": {
            "host": "127.0.0.1",
            "port": 8085
        },
        "touch_ui": {
            "host": "127.0.0.1",
            "port": 8082
        },
        "mac_teleop": {
            "host": "192.168.0.149",
            "port": 8086
        },
        "voice_bridge": {
            "host": "192.168.0.194",
            "port": 8058
        }
    },
    "hardware": {
        "serial_port": "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B41532189-if00",
        "baudrate": 1000000,
        "rover_serial_port": "/dev/serial/by-id/usb-Adafruit_KB2040_DF643CF013303739-if00",
        "rover_baudrate": 115200,
        "serial_retry_attempts": 3,
        "reconnect_timeout_sec": 1.5,
        "bus_reconnect_max_attempts": 5,
        "bus_reconnect_backoff_sec": 0.25
    },
    "direct_ethernet": {
        "pi500_ip": "10.0.0.1",
        "pi4b_ip": "10.0.0.2",
        "subnet": "10.0.0.0/24"
    },
    "wifi_defaults": {
        "pi500_ip": "192.168.0.130",
        "pi4b_ip": "192.168.0.86",
        "mac_ip": "192.168.0.149",
        "pc_ip": "192.168.0.194",
        "pi500_host": "pi500.local",
        "pi4b_host": "raspberrypi.local",
        "mac_host": "mac-mini.local",
        "pc_host": "workstation.local"
    },
    "ports": {
        "pi4b_http": 8082,
        "pi4b_video": 8083,
        "pi4b_audio_udp": 5004,
        "pi500_http": 8085,
        "mac_http": 8086,
        "voice_bridge_http": 8058,
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


def validate_network_config(cfg: Dict[str, Any]) -> None:
    """Validates mandatory network configuration schema fail-fast."""
    required_sections = ["topology_mode", "endpoints", "hardware", "direct_ethernet", "wifi_defaults", "ports", "wifi_modes", "auth"]
    for sec in required_sections:
        if sec not in cfg:
            raise KeyError(f"Missing required section '{sec}' in network configuration")

    if cfg["topology_mode"] not in ["STANDALONE_PI4B", "DUAL_NODE"]:
        raise ValueError(f"Invalid topology_mode '{cfg['topology_mode']}'. Permitted: ['STANDALONE_PI4B', 'DUAL_NODE']")

    for k in ["master_backend", "touch_ui", "mac_teleop", "voice_bridge"]:
        if k not in cfg["endpoints"]:
            raise KeyError(f"Missing required key 'endpoints.{k}' in network configuration")
        for sub_k in ["host", "port"]:
            if sub_k not in cfg["endpoints"][k]:
                raise KeyError(f"Missing required key 'endpoints.{k}.{sub_k}' in network configuration")

    for k in ["serial_port", "baudrate", "rover_serial_port", "rover_baudrate", "serial_retry_attempts", "reconnect_timeout_sec", "bus_reconnect_max_attempts", "bus_reconnect_backoff_sec"]:
        if k not in cfg["hardware"]:
            raise KeyError(f"Missing required key 'hardware.{k}' in network configuration")

    for k in ["pi500_ip", "pi4b_ip", "subnet"]:
        if k not in cfg["direct_ethernet"]:
            raise KeyError(f"Missing required key 'direct_ethernet.{k}' in network configuration")

    for k in ["pi500_ip", "pi4b_ip", "mac_ip", "pc_ip", "pi500_host", "pi4b_host", "mac_host", "pc_host"]:
        if k not in cfg["wifi_defaults"]:
            raise KeyError(f"Missing required key 'wifi_defaults.{k}' in network configuration")

    for k in ["pi4b_http", "pi4b_video", "pi4b_audio_udp", "pi500_http", "mac_http", "voice_bridge_http", "teleop_zmq", "teleop_zmq_heartbeat", "servo_studio_http"]:
        if k not in cfg["ports"]:
            raise KeyError(f"Missing required key 'ports.{k}' in network configuration")

    if "priority_list" not in cfg["wifi_modes"]:
        raise KeyError("Missing required key 'wifi_modes.priority_list' in network configuration")

    for idx, m in enumerate(cfg["wifi_modes"]["priority_list"]):
        for mk in ["mode_name", "ssid", "is_cloud_enabled"]:
            if mk not in m:
                raise KeyError(f"Missing required key '{mk}' in wifi_modes.priority_list[{idx}]")


def find_config_path() -> str:
    if "NETWORK_CONFIG_PATH" in os.environ and os.environ["NETWORK_CONFIG_PATH"]:
        return os.environ["NETWORK_CONFIG_PATH"]
    search_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "network_config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "network_config.json"),
        "/home/carson/touch_ui/config/network_config.json",
        "/home/carson/so101/config/network_config.json",
        "/home/user/so101/config/network_config.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "network_config.json"),
        "/home/carson/touch_ui/network_config.json",
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
    if not cfg_path:
        res = dict(DEFAULT_CONFIG)
        validate_network_config(res)
        _CONFIG_CACHE = res
        _CONFIG_LOAD_TIME = now
        return _CONFIG_CACHE

    with open(cfg_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise TypeError(f"Network config at {cfg_path} must be a JSON object, got {type(loaded).__name__}")
    res = dict(DEFAULT_CONFIG)
    res.update(loaded)
    validate_network_config(res)
    _CONFIG_CACHE = res
    _CONFIG_LOAD_TIME = now
    return _CONFIG_CACHE


def find_secrets_path() -> str:
    if "SECRETS_CONFIG_PATH" in os.environ and os.environ["SECRETS_CONFIG_PATH"]:
        return os.environ["SECRETS_CONFIG_PATH"]
    search_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "secrets.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "secrets.json"),
        "/home/carson/touch_ui/config/secrets.json",
        "/home/user/so101/config/secrets.json",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets.json"),
        "/home/carson/touch_ui/secrets.json",
    ]
    for p in search_paths:
        if p and os.path.exists(p):
            return p
    return ""


def get_home_public_ip() -> Optional[str]:
    if "HOME_PUBLIC_IP" in os.environ and os.environ["HOME_PUBLIC_IP"].strip():
        return os.environ["HOME_PUBLIC_IP"].strip()
    sec_path = find_secrets_path()
    if sec_path and os.path.exists(sec_path):
        try:
            with open(sec_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "home_public_ip" in data and data["home_public_ip"]:
                    return str(data["home_public_ip"]).strip()
        except Exception as e:
            logger.warning("Error reading secrets from %s: %s", sec_path, e)
    return None


def get_interface_ip(ifname: str = "wlan0") -> Optional[str]:
    """Dynamically resolves IPv4 address of a network interface (e.g. wlan0, eth0)."""
    if os.name != 'nt':
        try:
            res = subprocess.run(
                ["ip", "-4", "-o", "addr", "show", ifname],
                capture_output=True, text=True, timeout=1.0
            )
            for line in res.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    return parts[3].split("/")[0]
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError) as err:
            logger.warning("Subprocess error resolving IP for interface %s: %s", ifname, err)
            return None
        except Exception as err:
            logger.error("Unexpected error in get_interface_ip(%s): %s", ifname, err, exc_info=True)
            return None
    return None


def get_active_ssid() -> str:
    """Returns the SSID/connection name of the active wireless interface."""
    if os.name != 'nt':
        try:
            res = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"],
                capture_output=True, text=True, timeout=1.5
            )
            for line in res.stdout.strip().splitlines():
                parts = line.split(":")
                if len(parts) >= 3 and parts[1] == "802-11-wireless" and "wlan" in parts[2]:
                    return parts[0].strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError) as err:
            logger.warning("Subprocess error resolving active SSID: %s", err)
            return ""
        except Exception as err:
            logger.error("Unexpected error in get_active_ssid: %s", err, exc_info=True)
            return ""
    return ""


def is_hotspot_active() -> bool:
    """Determines whether the system is connected via a cellular Wi-Fi hotspot.
    Checks active SSID, hotspot profiles in network_config.json, and wlan0 IP subnet.
    Caches the result for CACHE_TTL_SEC to avoid subprocess latency.
    """
    global _HOTSPOT_CACHE
    now = time.time()
    if _HOTSPOT_CACHE is not None and (now - _HOTSPOT_CACHE[1]) < CACHE_TTL_SEC:
        return _HOTSPOT_CACHE[0]

    active = False
    ssid = get_active_ssid()
    if ssid:
        cfg = load_network_config()
        for m in cfg["wifi_modes"]["priority_list"]:
            if m["mode_name"] == "IPHONE_HOTSPOT" and (m["ssid"] == ssid or ssid in m["ssid"]):
                active = True
                break
        if not active and any(k in ssid.lower() for k in ["iphone", "hotspot", "pixel"]):
            active = True

    if not active:
        wlan_ip = get_interface_ip("wlan0")
        if wlan_ip:
            if wlan_ip.startswith("172.20.10.") or (not wlan_ip.startswith("192.168.") and not wlan_ip.startswith("127.")):
                active = True

    _HOTSPOT_CACHE = (active, now)
    return active


def is_socket_open(ip: str, port: int, timeout: Optional[float] = None) -> bool:
    hotspot = is_hotspot_active()
    # Strictly forbid any 192.168. or .local calls when on hotspot
    if hotspot and (ip.startswith("192.168.") or ip.endswith(".local")):
        return False

    if timeout is None:
        timeout = 0.6 if hotspot else 0.15

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except (socket.timeout, OSError) as err:
        logger.debug("Socket probe to %s:%d failed: %s", ip, port, err)
        return False
    except Exception as err:
        logger.error("Unexpected error in is_socket_open(%s:%d): %s", ip, port, err, exc_info=True)
        return False


def is_host_pingable(ip: str, timeout_sec: int = 1) -> bool:
    if is_hotspot_active() and (ip.startswith("192.168.") or ip.endswith(".local")):
        return False
    try:
        cmd = ["ping", "-n", "1", "-w", str(timeout_sec * 1000), ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", str(timeout_sec), ip]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return res.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError) as err:
        logger.warning("Ping subprocess error for %s: %s", ip, err)
        return False
    except Exception as err:
        logger.error("Unexpected error in is_host_pingable(%s): %s", ip, err, exc_info=True)
        return False


def resolve_target(candidates: List[Tuple[str, Optional[int]]], cache_key: str) -> str:
    now = time.time()
    hotspot = is_hotspot_active()
    probe_timeout = 0.6 if hotspot else 0.15

    # Strictly strip all 192.168. and .local candidates when hotspot is active
    if hotspot:
        candidates = [c for c in candidates if not c[0].startswith("192.168.") and not c[0].endswith(".local")]

    if not candidates:
        raise RuntimeError(f"Network resolution failed for '{cache_key}'. No valid candidates available while on Wi-Fi hotspot.")

    if cache_key in _IP_CACHE:
        cached_ip, ts = _IP_CACHE[cache_key]
        if (now - ts) < CACHE_TTL_SEC:
            if not (hotspot and (cached_ip.startswith("192.168.") or cached_ip.endswith(".local"))):
                return cached_ip

    for ip, port in candidates:
        if not ip:
            continue
        if port is not None:
            if is_socket_open(ip, port, timeout=probe_timeout):
                _IP_CACHE[cache_key] = (ip, now)
                return ip
        else:
            if is_host_pingable(ip, timeout_sec=1):
                _IP_CACHE[cache_key] = (ip, now)
                return ip

    if candidates and candidates[0][0]:
        fallback_ip = candidates[0][0]
        if hotspot and (fallback_ip.startswith("192.168.") or fallback_ip.endswith(".local")):
            raise RuntimeError(f"Network resolution failed for '{cache_key}': fallback '{fallback_ip}' is prohibited on hotspot.")
        _IP_CACHE[cache_key] = (fallback_ip, now)
        return fallback_ip

    raise RuntimeError(f"Network resolution failed for '{cache_key}'. No candidate addresses reachable.")


def get_master_backend_ip() -> str:
    cfg = load_network_config()
    if cfg["topology_mode"] == "STANDALONE_PI4B":
        return str(cfg["endpoints"]["master_backend"]["host"])
    return get_pi500_ip(prefer_port=int(cfg["endpoints"]["master_backend"]["port"]))


def get_touch_ui_ip() -> str:
    cfg = load_network_config()
    if cfg["topology_mode"] == "STANDALONE_PI4B":
        return str(cfg["endpoints"]["touch_ui"]["host"])
    return get_pi4b_ip(prefer_port=int(cfg["endpoints"]["touch_ui"]["port"]))


def get_hardware_serial_port() -> str:
    cfg = load_network_config()
    return str(cfg["hardware"]["serial_port"])


def get_hardware_baudrate() -> int:
    cfg = load_network_config()
    return int(cfg["hardware"]["baudrate"])


def get_rover_serial_port() -> str:
    cfg = load_network_config()
    return str(cfg["hardware"]["rover_serial_port"])


def get_rover_baudrate() -> int:
    cfg = load_network_config()
    return int(cfg["hardware"]["rover_baudrate"])


def get_serial_retry_attempts() -> int:
    cfg = load_network_config()
    return int(cfg["hardware"]["serial_retry_attempts"])


def get_reconnect_timeout_sec() -> float:
    cfg = load_network_config()
    return float(cfg["hardware"]["reconnect_timeout_sec"])


def get_bus_reconnect_max_attempts() -> int:
    cfg = load_network_config()
    return int(cfg["hardware"]["bus_reconnect_max_attempts"])


def get_bus_reconnect_backoff_sec() -> float:
    cfg = load_network_config()
    return float(cfg["hardware"]["bus_reconnect_backoff_sec"])


def get_backend_host(prefer_port: Optional[int] = 8085) -> str:
    cfg = load_network_config()
    topology_mode = cfg["topology_mode"]
    if topology_mode not in ["STANDALONE_PI4B", "DUAL_NODE"]:
        raise KeyError(f"Invalid topology_mode '{topology_mode}'. Expected 'STANDALONE_PI4B' or 'DUAL_NODE'")
    if topology_mode == "STANDALONE_PI4B":
        return str(cfg["endpoints"]["master_backend"]["host"])
    eth_ip = cfg["direct_ethernet"]["pi500_ip"]

    if is_hotspot_active():
        candidates: List[Tuple[str, Optional[int]]] = [
            (eth_ip, prefer_port),
            (eth_ip, 22),
            (eth_ip, None)
        ]
        return resolve_target(candidates, "pi500_ip")

    wifi_ip = cfg["wifi_defaults"]["pi500_ip"]
    m_host = cfg["wifi_defaults"]["pi500_host"]

    candidates = [
        (eth_ip, prefer_port),
        (eth_ip, 22),
        (wifi_ip, prefer_port),
        (wifi_ip, 22),
        (m_host, prefer_port),
        (eth_ip, None),
        (wifi_ip, None)
    ]
    return resolve_target(candidates, "pi500_ip")


def get_backend_url(path: str = "/api/status", port: int = 8085) -> str:
    host = get_backend_host(prefer_port=port)
    clean_path = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{clean_path}"


def get_pi500_ip(prefer_port: Optional[int] = 8085) -> str:
    """Transitional backward-compatible alias for get_backend_host."""
    return get_backend_host(prefer_port=prefer_port)


def get_pi4b_ip(prefer_port: Optional[int] = 8082) -> str:
    cfg = load_network_config()
    topology_mode = cfg["topology_mode"]
    if topology_mode not in ["STANDALONE_PI4B", "DUAL_NODE"]:
        raise KeyError(f"Invalid topology_mode '{topology_mode}'. Expected 'STANDALONE_PI4B' or 'DUAL_NODE'")
    if topology_mode == "STANDALONE_PI4B":
        return str(cfg["endpoints"]["touch_ui"]["host"])
    eth_ip = cfg["direct_ethernet"]["pi4b_ip"]

    if is_hotspot_active():
        candidates: List[Tuple[str, Optional[int]]] = [
            (eth_ip, prefer_port),
            (eth_ip, 22),
            (eth_ip, None)
        ]
        return resolve_target(candidates, "pi4b_ip")

    wifi_ip = cfg["wifi_defaults"]["pi4b_ip"]
    m_host = cfg["wifi_defaults"]["pi4b_host"]

    candidates = [
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
    pub_ip = get_home_public_ip()
    if is_hotspot_active():
        if not pub_ip:
            raise RuntimeError("Wi-Fi hotspot active but 'home_public_ip' not configured in secrets.json")
        candidates: List[Tuple[str, Optional[int]]] = [
            (pub_ip, prefer_port),
            (pub_ip, None)
        ]
        return resolve_target(candidates, "mac_ip")

    cfg = load_network_config()
    wifi_ip = cfg["wifi_defaults"]["mac_ip"]
    m_host = cfg["wifi_defaults"]["mac_host"]

    candidates = [
        (wifi_ip, prefer_port),
        (m_host, prefer_port),
    ]
    if pub_ip:
        candidates.append((pub_ip, prefer_port))
    candidates.extend([
        (wifi_ip, 22),
        (wifi_ip, None)
    ])
    return resolve_target(candidates, "mac_ip")


def get_pc_ip(prefer_port: Optional[int] = 8058) -> str:
    if is_hotspot_active():
        raise RuntimeError("PC workstation is unreachable while on Wi-Fi hotspot.")
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
    return cfg["ports"]


def get_active_connection_mode() -> Dict[str, Any]:
    """Determines the current operating connection mode."""
    active_ssid = get_active_ssid()
    cfg = load_network_config()
    modes = cfg["wifi_modes"]["priority_list"]

    for m in modes:
        if active_ssid and (m["ssid"] == active_ssid or active_ssid in m["ssid"]):
            return {
                "mode": m["mode_name"],
                "ssid": active_ssid,
                "is_cloud_enabled": m["is_cloud_enabled"],
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
    print("Hotspot Active:", is_hotspot_active())
    print("Pi 500 IP:", get_pi500_ip())
    print("Pi 4B IP:", get_pi4b_ip())
    print("Mac IP:", get_mac_ip())
    print("Ports:", get_ports())
    print("Active Mode:", get_active_connection_mode())
