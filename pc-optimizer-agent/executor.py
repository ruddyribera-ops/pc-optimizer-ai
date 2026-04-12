import subprocess
import json
import logging

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self):
        self.last_output = None
        self.last_error = None

    def run_powershell(self, command, timeout=60):
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            self.last_output = result.stdout.strip()
            self.last_error = result.stderr.strip()
            return {
                "success": result.returncode == 0,
                "output": self.last_output,
                "error": self.last_error,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out", "returncode": -1}
        except Exception as e:
            return {"success": False, "error": str(e), "returncode": -1}

    def run_batch(self, command, timeout=60):
        try:
            result = subprocess.run(
                ["cmd", "/c", command], capture_output=True, text=True, timeout=timeout
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "returncode": -1}

    def get_installed_apps(self):
        cmd = """
        Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName } |
        Select-Object DisplayName, DisplayVersion, Publisher, UninstallString |
        ConvertTo-Json -Compress
        """
        result = self.run_powershell(cmd)
        if result["success"] and result["output"]:
            try:
                apps = json.loads(result["output"])
                return apps if isinstance(apps, list) else [apps]
            except json.JSONDecodeError:
                return []
        return []

    def get_enabled_windows_features(self):
        cmd = "Get-WindowsOptionalFeature -Online | Where-Object { $_.State -eq 'Enabled' } | Select-Object FeatureName, State | ConvertTo-Json -Compress"
        result = self.run_powershell(cmd)
        if result["success"] and result["output"]:
            try:
                features = json.loads(result["output"])
                return features if isinstance(features, list) else [features]
            except json.JSONDecodeError:
                return []
        return []

    def get_disk_space(self):
        cmd = "Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{N='Used(GB)';E={[math]::Round($_.Used/1GB,2)}}, @{N='Free(GB)';E={[math]::Round($_.Free/1GB,2)}} | ConvertTo-Json -Compress"
        result = self.run_powershell(cmd)
        if result["success"] and result["output"]:
            try:
                return json.loads(result["output"])
            except json.JSONDecodeError:
                return []
        return []

    def get_system_info(self):
        cmd = """
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
        """
        result = self.run_powershell(cmd)
        if result["success"] and result["output"]:
            try:
                return json.loads(result["output"])
            except json.JSONDecodeError:
                return {}
        return {}

    def get_startup_apps(self):
        cmd = """
        $startup = @()
        
        $regPaths = @(
            'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',
            'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',
            'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce',
            'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce'
        )
        
        foreach ($path in $regPaths) {
            if (Test-Path $path) {
                Get-ItemProperty $path | ForEach-Object {
                    $_.PSObject.Properties | Where-Object { $_.Name -notlike 'PS*' } | ForEach-Object {
                        $startup += @{
                            Name = $_.Name
                            Path = $_.Value
                            Location = $path
                        }
                    }
                }
            }
        }
        
        $scheduledTasks = Get-ScheduledTask | Where-Object { $_.State -eq 'Ready' } | ForEach-Object {
            $info = Get-ScheduledTaskInfo -TaskName $_.TaskName -ErrorAction SilentlyContinue
            if ($info -and $info.NextRunTime) {
                @{
                    Name = $_.TaskName
                    Path = $_.TaskPath
                    Location = 'ScheduledTask'
                    NextRun = $info.NextRunTime.ToString()
                }
            }
        }
        
        $result = @{
            Registry = $startup
            ScheduledTasks = $scheduledTasks
        }
        
        $result | ConvertTo-Json -Compress
        """
        result = self.run_powershell(cmd)
        if result["success"] and result["output"]:
            try:
                return json.loads(result["output"])
            except json.JSONDecodeError:
                return {"Registry": [], "ScheduledTasks": []}
        return {"Registry": [], "ScheduledTasks": []}

    def flush_memory(self):
        cmd = """
        [System.GC]::Collect()
        [System.GC]::WaitForPendingFinalizers()
        [System.GC]::Collect()
        "Memory flushed"
        """
        result = self.run_powershell(cmd)
        return result

    def disable_startup_item(self, name, location):
        if location == "ScheduledTask":
            cmd = f"Disable-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue"
        else:
            cmd = f"Remove-ItemProperty -Path '{location}' -Name '{name}' -Force -ErrorAction SilentlyContinue"
        result = self.run_powershell(cmd)
        return result
