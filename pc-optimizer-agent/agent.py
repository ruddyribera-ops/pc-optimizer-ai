"""
PC Optimizer Agent - Local client that runs on Windows and communicates with the cloud backend.
Place this file on the Windows machine you want to optimize.
"""

import os
import sys
import time
import logging
import json
import platform
import subprocess
import requests
import uuid
from datetime import datetime

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

API_URL = "https://pc-optimizer-ai-production-9984.up.railway.app"
LOCAL_API_URL = "http://localhost:8000"


class Agent:
    def __init__(self, api_url=None):
        self.api_url = api_url or LOCAL_API_URL
        self.device_id = self.get_or_create_device_id()
        self.hostname = platform.node()
        self.is_windows = platform.system() == "Windows"
        logger.info(f"Agent initialized for device: {self.hostname} ({self.device_id})")

    def get_or_create_device_id(self):
        device_file = os.path.join(os.path.dirname(__file__), ".device_id")
        if os.path.exists(device_file):
            with open(device_file, "r") as f:
                return f.read().strip()
        device_id = f"agent_{uuid.uuid4().hex[:12]}"
        with open(device_file, "w") as f:
            f.write(device_id)
        return device_id

    def register(self):
        try:
            response = requests.post(
                f"{self.api_url}/register",
                json={
                    "device_id": self.device_id,
                    "api_key": "local_agent",
                    "hostname": self.hostname,
                },
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"Registered with backend: {response.json()}")
                return True
            else:
                logger.error(f"Registration failed: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False

    def send_heartbeat(self):
        try:
            requests.post(
                f"{self.api_url}/status", json={"device_id": self.device_id}, timeout=5
            )
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

    def get_pending_commands(self):
        try:
            response = requests.get(
                f"{self.api_url}/device/{self.device_id}/pending", timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Get commands error: {e}")
        return []

    def report_result(self, command_id, task, result):
        try:
            requests.post(
                f"{self.api_url}/result",
                json={
                    "device_id": self.device_id,
                    "task": task,
                    "command_id": command_id,
                    "result": result,
                },
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Report result error: {e}")

    def get_system_info(self):
        if not self.is_windows:
            return {"error": "Not running on Windows"}

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    """
                    $os = Get-CimInstance Win32_OperatingSystem
                    $cpu = Get-CimInstance Win32_Processor
                    @{
                        hostname = $env:COMPUTERNAME
                        os = $os.Caption
                        os_version = $os.Version
                        total_ram_gb = [math]::Round($os.TotalVisibleMemorySize/1MB, 2)
                        free_ram_gb = [math]::Round($os.FreePhysicalMemory/1MB, 2)
                        cpu = $cpu.Name
                    } | ConvertTo-Json -Compress
                """,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return json.loads(result.stdout.strip())
        except Exception as e:
            logger.error(f"Get system info error: {e}")
        return {"error": "Failed to get system info"}

    def get_disk_space(self):
        if not self.is_windows:
            return [{"error": "Not running on Windows"}]

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    """
                    Get-PSDrive -PSProvider FileSystem | 
                    Where-Object {$_.Free -gt 0} |
                    Select-Object Name, @{N='Used(GB)';E={[math]::Round($_.Used/1GB,2)}}, @{N='Free(GB)';E={[math]::Round($_.Free/1GB,2)}} | 
                    ConvertTo-Json -Compress
                """,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout.strip())
                return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.error(f"Get disk space error: {e}")
        return [{"error": "Failed to get disk space"}]

    def cleanup_temp_files(self):
        if not self.is_windows:
            return {"success": False, "error": "Not running on Windows"}

        import shutil

        results = []
        temp_paths = [
            os.environ.get("TEMP", ""),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
        ]

        for path in temp_paths:
            if os.path.exists(path):
                try:
                    count = 0
                    size_freed = 0
                    for item in os.listdir(path):
                        item_path = os.path.join(path, item)
                        try:
                            if os.path.isfile(item_path):
                                size_freed += os.path.getsize(item_path)
                                os.remove(item_path)
                                count += 1
                            elif os.path.isdir(item_path):
                                size_freed += self._get_dir_size(item_path)
                                shutil.rmtree(item_path, ignore_errors=True)
                                count += 1
                        except:
                            pass
                    results.append(
                        f"Cleaned {count} items from {path}, freed {size_freed / (1024**2):.1f} MB"
                    )
                except Exception as e:
                    results.append(f"Error cleaning {path}: {e}")

        return {"success": True, "results": results}

    def _get_dir_size(self, path):
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except:
                        pass
        except:
            pass
        return total

    def cleanup_browser_cache(self):
        if not self.is_windows:
            return {"success": False, "error": "Not running on Windows"}

        import shutil

        results = []
        base = os.environ.get("LOCALAPPDATA", "")

        browsers = {
            "Chrome": os.path.join(
                base, "Google", "Chrome", "User Data", "Default", "Cache"
            ),
            "Edge": os.path.join(
                base, "Microsoft", "Edge", "User Data", "Default", "Cache"
            ),
        }

        for browser, cache_path in browsers.items():
            if os.path.exists(cache_path):
                try:
                    size_before = self._get_dir_size(cache_path)
                    shutil.rmtree(cache_path, ignore_errors=True)
                    os.makedirs(cache_path, exist_ok=True)
                    results.append(f"{browser}: freed {size_before / (1024**2):.1f} MB")
                except Exception as e:
                    results.append(f"{browser} error: {e}")

        return (
            {"success": True, "results": results}
            if results
            else {"success": False, "error": "No browser caches found"}
        )

    def empty_recycle_bin(self):
        if not self.is_windows:
            return {"success": False, "error": "Not running on Windows"}

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Clear-RecycleBin -Force -ErrorAction SilentlyContinue; 'Recycle bin emptied'",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {"success": result.returncode == 0, "output": result.stdout.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def flush_memory(self):
        if not self.is_windows:
            return {"success": False, "error": "Not running on Windows"}

        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "[System.GC]::Collect(); [System.GC]::WaitForPendingFinalizers(); [System.GC]::Collect(); 'Memory flushed'",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {"success": result.returncode == 0, "output": result.stdout.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_task(self, task):
        task_handlers = {
            "get_system_info": self.get_system_info,
            "get_disk_space": self.get_disk_space,
            "cleanup_temp_files": self.cleanup_temp_files,
            "cleanup_browser_cache": self.cleanup_browser_cache,
            "empty_recycle_bin": self.empty_recycle_bin,
            "cleanup_ram": self.flush_memory,
        }

        if task in task_handlers:
            return task_handlers[task]()
        else:
            return {"success": False, "error": f"Unknown task: {task}"}

    def run_interactive(self):
        print("\n" + "=" * 50)
        print("PC Optimizer Agent - Interactive Mode")
        print("=" * 50)
        print(f"Device ID: {self.device_id}")
        print(f"Hostname: {self.hostname}")
        print(f"Backend: {self.api_url}")
        print(f"Status: {'Connected' if self.register() else 'Not connected'}")
        print("=" * 50 + "\n")

        while True:
            print("\nAvailable tasks:")
            print("1. Get System Info")
            print("2. Get Disk Space")
            print("3. Clean Temp Files")
            print("4. Clean Browser Cache")
            print("5. Empty Recycle Bin")
            print("6. Flush Memory")
            print("7. Send Heartbeat")
            print("0. Exit")

            choice = input("\nSelect task (0-7): ").strip()

            if choice == "0":
                print("Goodbye!")
                break

            task_map = {
                "1": "get_system_info",
                "2": "get_disk_space",
                "3": "cleanup_temp_files",
                "4": "cleanup_browser_cache",
                "5": "empty_recycle_bin",
                "6": "cleanup_ram",
                "7": "heartbeat",
            }

            if choice not in task_map:
                print("Invalid choice")
                continue

            task = task_map[choice]

            if task == "heartbeat":
                self.send_heartbeat()
                print("Heartbeat sent")
                continue

            print(f"\nExecuting: {task}...")
            result = self.execute_task(task)
            print(f"Result: {json.dumps(result, indent=2)}")

            if self.register():
                self.report_result(None, task, result)


def main():
    # Default to Railway URL, can override via command line
    if len(sys.argv) > 1:
        api_url = sys.argv[1]
    else:
        api_url = API_URL  # Use Railway by default

    agent = Agent(api_url)

    if "--interactive" in sys.argv:
        agent.run_interactive()
    else:
        print("PC Optimizer Agent")
        print(f"Device: {agent.hostname}")
        print(f"Device ID: {agent.device_id}")

        if agent.register():
            print("Registered with backend successfully")

            print("\nFetching system info...")
            info = agent.get_system_info()
            print(f"System: {json.dumps(info, indent=2)}")

            print("\nFetching disk space...")
            disk = agent.get_disk_space()
            print(f"Disk: {json.dumps(disk, indent=2)}")
        else:
            print("Failed to register with backend")
            print(
                "Make sure the backend is running or use --interactive for local testing"
            )


if __name__ == "__main__":
    main()
