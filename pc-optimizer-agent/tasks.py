import os
import shutil
import json
from executor import Executor

executor = Executor()


TASKS = {
    "get_system_info": {
        "description": "Get system information",
        "function": lambda: executor.get_system_info(),
    },
    "get_installed_apps": {
        "description": "List all installed applications",
        "function": lambda: executor.get_installed_apps(),
    },
    "get_enabled_features": {
        "description": "Get enabled Windows optional features",
        "function": lambda: executor.get_enabled_windows_features(),
    },
    "get_disk_space": {
        "description": "Get disk space information",
        "function": lambda: executor.get_disk_space(),
    },
    "get_startup_apps": {
        "description": "Get startup applications",
        "function": lambda: executor.get_startup_apps(),
    },
    "cleanup_temp_files": {
        "description": "Clean temporary files",
        "function": lambda: _cleanup_temp_files(),
    },
    "cleanup_browser_cache": {
        "description": "Clean browser caches",
        "function": lambda: _cleanup_browser_cache(),
    },
    "cleanup_windows_update_cache": {
        "description": "Clean Windows Update cache",
        "function": lambda: _cleanup_windows_update_cache(),
    },
    "cleanup_ram": {
        "description": "Free up RAM memory",
        "function": lambda: _cleanup_ram(),
    },
    "empty_recycle_bin": {
        "description": "Empty recycle bin",
        "function": lambda: _empty_recycle_bin(),
    },
    "disable_windows_telemetry": {
        "description": "Disable Windows telemetry",
        "function": lambda: _disable_telemetry(),
    },
    "disable_xbox_features": {
        "description": "Disable Xbox gaming features",
        "function": lambda: _disable_xbox_features(),
    },
    "disable_cortana": {
        "description": "Disable Cortana",
        "function": lambda: _disable_cortana(),
    },
    "disable_advertising_id": {
        "description": "Disable advertising ID",
        "function": lambda: _disable_advertising_id(),
    },
    "disable_startup_item": {
        "description": "Disable startup item",
        "function": lambda params: _disable_startup_item(params),
        "requires_param": True,
    },
    "uninstall_app": {
        "description": "Uninstall application by name",
        "function": lambda app_name: _uninstall_app(app_name),
        "requires_param": True,
    },
    "disable_feature": {
        "description": "Disable Windows optional feature",
        "function": lambda feature_name: _disable_feature(feature_name),
        "requires_param": True,
    },
    "collect_snapshot": {
        "description": "Collect full system snapshot",
        "function": lambda: _collect_snapshot(),
    },
    "strengthen_privacy": {
        "description": "Strengthen Windows privacy settings",
        "function": lambda: _strengthen_privacy(),
    },
}


def _cleanup_temp_files():
    paths = [os.environ.get("TEMP", ""), "C:\\Windows\\Temp", "C:\\Windows\\Prefetch"]
    results = []
    for path in paths:
        if os.path.exists(path):
            try:
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path, ignore_errors=True)
                    except:
                        pass
                results.append(f"Cleaned {path}")
            except Exception as e:
                results.append(f"Error cleaning {path}: {str(e)}")
    return {"success": True, "results": results}


def _cleanup_browser_cache():
    results = []
    base_paths = os.environ.get("LOCALAPPDATA", "")

    chrome_cache = os.path.join(base_paths, "Google\\Chrome\\User Data\\Default\\Cache")
    if os.path.exists(chrome_cache):
        try:
            shutil.rmtree(chrome_cache, ignore_errors=True)
            results.append("Chrome cache cleared")
        except Exception as e:
            results.append(f"Chrome error: {str(e)}")

    edge_cache = os.path.join(base_paths, "Microsoft\\Edge\\User Data\\Default\\Cache")
    if os.path.exists(edge_cache):
        try:
            shutil.rmtree(edge_cache, ignore_errors=True)
            results.append("Edge cache cleared")
        except Exception as e:
            results.append(f"Edge error: {str(e)}")

    return {"success": True, "results": results}


def _cleanup_windows_update_cache():
    cmd = "Remove-Item -Path C:\\Windows\\SoftwareDistribution\\Download\\* -Recurse -Force -ErrorAction SilentlyContinue"
    result = executor.run_powershell(cmd)
    return result


def _empty_recycle_bin():
    cmd = "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"
    result = executor.run_powershell(cmd)
    return result


def _disable_telemetry():
    cmds = [
        "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection' -Name 'AllowTelemetry' -Value 0 -Type DWord -Force",
        "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Privacy' -Name 'TailoredExperiencesWithDiagnosticDataEnabled' -Value 0 -Type DWord -Force",
        "Set-ItemProperty - Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Diagnostics\\DiagTrack' -Name 'AutoSapEnabled' -Value 0 -Type DWord -Force",
    ]
    results = []
    for cmd in cmds:
        result = executor.run_powershell(cmd)
        results.append(result)
    return {"success": True, "results": results}


def _disable_xbox_features():
    cmds = [
        "Get-AppxPackage -AllUsers *Xbox* | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue",
        "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\GameXaml' -Name 'EnableGameXaml' -Value 0 -Type DWord -Force",
    ]
    results = []
    for cmd in cmds:
        result = executor.run_powershell(cmd)
        results.append(result)
    return {"success": True, "results": results}


def _disable_cortana():
    cmd = "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\Windows Search' -Name 'AllowCortana' -Value 0 -Type DWord -Force"
    result = executor.run_powershell(cmd)
    return result


def _disable_advertising_id():
    cmd = "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\AdvertisingInfo' -Name 'Enabled' -Value 0 -Type DWord -Force"
    result = executor.run_powershell(cmd)
    return result


def _uninstall_app(app_name):
    apps = executor.get_installed_apps()
    for app in apps:
        if app.get("DisplayName", "").lower() == app_name.lower():
            uninstall_string = app.get("UninstallString")
            if uninstall_string:
                if "msiexec" in uninstall_string.lower():
                    result = executor.run_powershell(
                        f"Start-Process msiexec.exe -ArgumentList '/x{uninstall_string.split('msiexec.exe')[1].strip()}' -Wait -WindowStyle Hidden"
                    )
                else:
                    result = executor.run_powershell(
                        f"Start-Process cmd.exe -ArgumentList '/c {uninstall_string}' -Wait -WindowStyle Hidden"
                    )
                return result
    return {"success": False, "error": "App not found"}


def _disable_feature(feature_name):
    cmd = f"Disable-WindowsOptionalFeature -Online -FeatureName {feature_name} -NoRestart -WarningAction SilentlyContinue"
    result = executor.run_powershell(cmd)
    return result


def _collect_snapshot():
    snapshot = {
        "system_info": executor.get_system_info(),
        "installed_apps": executor.get_installed_apps(),
        "enabled_features": executor.get_enabled_windows_features(),
        "disk_space": executor.get_disk_space(),
    }
    return {"success": True, "snapshot": snapshot}


def _cleanup_ram():
    results = []
    result = executor.flush_memory()
    results.append(f"Memory flush: {result.get('output', 'done')}")

    cmd = "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 Name, @{N='MB';E={[math]::Round($_.WorkingSet64/1MB,2)}} | ConvertTo-Json"
    result = executor.run_powershell(cmd)
    if result["success"]:
        try:
            top_processes = json.loads(result["output"])
            results.append(f"Top memory consumers identified")
        except:
            pass

    return {"success": True, "results": results}


def _disable_startup_item(params):
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except:
            params = {"name": params, "location": "Registry"}

    name = params.get("name")
    location = params.get("location", "Registry")

    if not name:
        return {"success": False, "error": "Name is required"}

    result = executor.disable_startup_item(name, location)
    return result


def _strengthen_privacy():
    cmds = [
        "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection' -Name 'AllowTelemetry' -Value 0 -Type DWord -Force",
        "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Privacy' -Name 'TailoredExperiencesWithDiagnosticDataEnabled' -Value 0 -Type DWord -Force",
        "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Diagnostics\\DiagTrack' -Name 'AutoSapEnabled' -Value 0 -Type DWord -Force",
        "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\location' -Name 'Value' -Value 'Deny' -Type String -Force",
        "Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\webcam' -Name 'Value' -Value 'Deny' -Type String -Force",
    ]
    results = []
    for cmd in cmds:
        result = executor.run_powershell(cmd)
        results.append(
            {"success": result["success"], "output": result.get("output", "")}
        )

    return {"success": True, "results": results}


def execute_task(task_name, param=None):
    if task_name not in TASKS:
        return {"success": False, "error": f"Unknown task: {task_name}"}

    task = TASKS[task_name]
    if task.get("requires_param", False):
        if param is None:
            return {"success": False, "error": f"Task {task_name} requires a parameter"}
        return task["function"](param)
    else:
        return task["function"]()
