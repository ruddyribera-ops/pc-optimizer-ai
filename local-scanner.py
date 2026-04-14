#!/usr/bin/env python3
"""
PC Optimizer Local Scanner
Gathers real system information and sends to the cloud dashboard.
Run this on your PC to see real-time data.
"""

import socket
import platform
import os
import json
import time
import uuid
import requests
from datetime import datetime

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("Tip: Install psutil for real data - pip install psutil")


def get_device_id():
    """Get or create a unique device ID"""
    config_dir = os.path.expanduser("~/.pc-optimizer")
    id_file = os.path.join(config_dir, ".device_id")
    
    if os.path.exists(id_file):
        with open(id_file, "r") as f:
            return f.read().strip()
    
    os.makedirs(config_dir, exist_ok=True)
    device_id = "device_" + str(uuid.uuid4())[:8] + "_" + str(int(time.time()))
    
    with open(id_file, "w") as f:
        f.write(device_id)
    
    return device_id


def get_system_info():
    """Gather real system information"""
    info = {
        "device_id": get_device_id(),
        "hostname": socket.gethostname(),
        "os": platform.system() + " " + platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "cpu_cores": os.cpu_count() or 0,
        "timestamp": datetime.now().isoformat()
    }
    
    if HAS_PSUTIL:
        # Real RAM data
        mem = psutil.virtual_memory()
        info["total_ram_gb"] = round(mem.total / (1024**3), 1)
        info["free_ram_gb"] = round(mem.available / (1024**3), 1)
        info["used_ram_gb"] = round(mem.used / (1024**3), 1)
        info["ram_percent"] = mem.percent
        
        # Real disk data
        disk_info = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_info.append({
                    "drive": part.device,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "percent": usage.percent
                })
            except:
                pass
        info["disk_space"] = disk_info
        
        # CPU usage
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        
        # Boot time
        info["boot_time"] = datetime.fromtimestamp(psutil.boot_time()).isoformat()
    
    return info


def send_to_cloud(api_url, data):
    """Send system info to cloud API"""
    try:
        response = requests.post(
            f"{api_url}/device/{data['device_id']}/system-info",
            json=data,
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending to cloud: {e}")
        return False


def main():
    print("=" * 50)
    print("PC Optimizer Local Scanner")
    print("=" * 50)
    
    # Get API URL - default to local, can be changed
    api_url = os.environ.get("OPTIMIZER_API_URL", "http://localhost:8000")
    
    print(f"\nAPI URL: {api_url}")
    print("Getting system info...")
    
    # Get real system data
    info = get_system_info()
    
    print("\n--- Your Real System Data ---")
    print(f"Hostname: {info.get('hostname')}")
    print(f"OS: {info.get('os')}")
    
    if HAS_PSUTIL:
        print(f"RAM: {info.get('used_ram_gb')}GB / {info.get('total_ram_gb')}GB ({info.get('ram_percent')}%)")
        print(f"CPU: {info.get('cpu_percent')}%")
        
        if info.get("disk_space"):
            for disk in info["disk_space"]:
                print(f"Disk {disk['drive']}: {disk['used_gb']}GB / {disk['total_gb']}GB ({disk['percent'}%)")
    else:
        print("\nNote: Install psutil for real data")
        print("pip install psutil")
    
    print("\n" + "-" * 50)
    
    # Send to cloud
    print("Sending to cloud dashboard...")
    
    success = send_to_cloud(api_url, info)
    
    if success:
        print("✓ Data sent to dashboard!")
        print(f"\nDevice ID: {info['device_id']}")
        print("\nOpen your dashboard to see real data!")
    else:
        print("Could not reach cloud. Running in local mode.")
    
    print("\nPress Ctrl+C to exit")
    
    # Keep running and send updates
    print("\nSending live updates every 30 seconds...")
    
    while True:
        try:
            time.sleep(30)
            info = get_system_info()
            send_to_cloud(api_url, info)
            print(f"✓ Updated at {datetime.now().strftime('%H:%M:%S')} - RAM: {info.get('ram_percent')}%")
        except KeyboardInterrupt:
            print("\nScanner stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()