from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import uuid
from datetime import datetime
import logging
import json
import requests
import time
import os

import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PC Optimizer Cloud API")

# Railway provides a PORT environment variable
PORT = int(os.getenv("PORT", 8000))
DATABASE_URL = os.getenv("DATABASE_URL", "optimizer.db")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "PC Optimizer API - use /static/index.html for dashboard"}


DATABASE = os.getenv("DATABASE_URL", "optimizer.db")


def get_db_connection():
    """Get database connection - supports both SQLite and PostgreSQL"""
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql"):
        # Railway PostgreSQL - will be handled differently
        # For now, fall back to SQLite for local dev
        pass
    return DATABASE


# Health check endpoint for Railway
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "pc-optimizer-api"}


@app.get("/healthz")
async def health_check_alt():
    return {"status": "healthy"}


def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            hostname TEXT,
            registered_at TEXT,
            last_seen TEXT,
            status TEXT DEFAULT 'online'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id TEXT PRIMARY KEY,
            device_id TEXT,
            task TEXT,
            param TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            completed_at TEXT,
            result TEXT,
            FOREIGN KEY(device_id) REFERENCES devices(device_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            snapshot_json TEXT,
            created_at TEXT,
            FOREIGN KEY(device_id) REFERENCES devices(device_id)
        )
    """)

    conn.commit()
    conn.close()


init_db()


class DeviceRegister(BaseModel):
    device_id: str
    api_key: str
    hostname: str


class TaskCommand(BaseModel):
    device_id: str
    task: str
    param: Optional[str] = None
    require_approval: bool = True


class CommandResult(BaseModel):
    device_id: str
    task: str
    result: dict


class ScanRequest(BaseModel):
    device_id: str


@app.post("/register")
async def register_device(device: DeviceRegister):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO devices (device_id, hostname, registered_at, last_seen)
        VALUES (?, ?, ?, ?)
    """,
        (
            device.device_id,
            device.hostname,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    logger.info(f"Device registered: {device.device_id}")
    return {"status": "registered", "device_id": device.device_id}


@app.get("/devices")
async def list_devices():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT device_id, hostname, registered_at, last_seen, status FROM devices"
    )
    devices = cursor.fetchall()
    conn.close()

    return [
        {
            "device_id": d[0],
            "hostname": d[1],
            "registered_at": d[2],
            "last_seen": d[3],
            "status": d[4],
        }
        for d in devices
    ]


@app.get("/commands/{device_id}")
async def get_commands(device_id: str):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, task, param, status FROM commands
        WHERE device_id = ? AND status = 'pending'
        ORDER BY created_at ASC
    """,
        (device_id,),
    )

    commands = cursor.fetchall()
    conn.close()

    return [{"id": c[0], "task": c[1], "param": c[2], "status": c[3]} for c in commands]


@app.post("/command")
async def send_command(command: TaskCommand):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT device_id FROM devices WHERE device_id = ?", (command.device_id,)
    )
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Device not found")

    command_id = str(uuid.uuid4())

    cursor.execute(
        """
        INSERT INTO commands (id, device_id, task, param, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            command_id,
            command.device_id,
            command.task,
            command.param,
            "pending",
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    logger.info(f"Command queued: {command.task} for device {command.device_id}")
    return {"command_id": command_id, "status": "queued"}


@app.post("/result")
async def receive_result(result: CommandResult):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE commands
        SET status = 'completed', result = ?, completed_at = ?
        WHERE device_id = ? AND task = ?
    """,
        (
            json.dumps(result.result),
            datetime.now().isoformat(),
            result.device_id,
            result.task,
        ),
    )

    cursor.execute(
        "UPDATE devices SET last_seen = ? WHERE device_id = ?",
        (datetime.now().isoformat(), result.device_id),
    )

    conn.commit()
    conn.close()

    logger.info(f"Result received: {result.task} from {result.device_id}")
    return {"status": "received"}


@app.post("/status")
async def receive_status(data: dict):
    device_id = data.get("device_id")
    status_data = data.get("status", {})

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE devices SET last_seen = ? WHERE device_id = ?",
        (datetime.now().isoformat(), device_id),
    )
    conn.commit()
    conn.close()

    return {"status": "ok"}


@app.get("/device/{device_id}/history")
async def get_device_history(device_id: str):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, task, param, status, created_at, completed_at, result
        FROM commands
        WHERE device_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """,
        (device_id,),
    )

    history = cursor.fetchall()
    conn.close()

    return [
        {
            "id": h[0],
            "task": h[1],
            "param": h[2],
            "status": h[3],
            "created_at": h[4],
            "completed_at": h[5],
            "result": json.loads(h[6]) if h[6] else None,
        }
        for h in history
    ]


@app.post("/analyze")
async def analyze_system(device_id: str = None, request: ScanRequest = None):
    if request:
        device_id = request.device_id
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    logger.info(f"Analyze request for device: {device_id}")

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT snapshot_json FROM system_snapshots
        WHERE device_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """,
        (device_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No system snapshot found")

    snapshot = json.loads(row[0])

    system_info = snapshot.get("system_info", {})
    apps = snapshot.get("installed_apps", [])
    features = snapshot.get("enabled_features", [])
    disk = snapshot.get("disk_space", [])

    prompt = f"""You are a PC optimization expert. Analyze this system and recommend cleanup actions.

System:
- Hostname: {system_info.get("hostname", "unknown")}
- OS: {system_info.get("os", "unknown")}
- RAM: {system_info.get("total_ram_gb", "?")}GB total, {system_info.get("free_ram_gb", "?")}GB free

Installed Applications ({len(apps)}):
{", ".join([a.get("DisplayName", "Unknown")[:50] for a in apps[:20]])}

Enabled Windows Features:
{", ".join([f.get("FeatureName", "Unknown") for f in features[:10]])}

Disk Space:
{json.dumps(disk[:5], indent=2)}

Generate a JSON list of tasks to optimize this PC. Return ONLY a JSON array of objects with 'task' and 'param' fields. Example:
[{{"task": "cleanup_temp_files", "param": null}}, {{"task": "uninstall_app", "param": "Candy Crush"}}]
"""

    try:
        logger.info(f"Sending request to Ollama for device {device_id}")

        # First try getting snapshot from DB
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

        # First check if we have any snapshots at all for this device
        cursor.execute(
            "SELECT COUNT(*) FROM system_snapshots WHERE device_id = ?", (device_id,)
        )
        count = cursor.fetchone()[0]
        logger.info(f"Snapshot count for {device_id}: {count}")

        if count > 0:
            # Get most recent snapshot - check for result column first
            cursor.execute(
                """
                SELECT snapshot_json FROM system_snapshots
                WHERE device_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (device_id,),
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                snapshot = json.loads(row[0])
                logger.info(f"Got snapshot with keys: {list(snapshot.keys())}")
            else:
                snapshot = None
                logger.warning("No snapshot data in row")
        else:
            conn.close()
            # Try to build from command history
            snapshot = None
            logger.info("No snapshots, trying command history")

        # If we don't have a snapshot yet, use test data
        if not snapshot:
            snapshot = {
                "system_info": {
                    "hostname": "TEST-PC",
                    "os": "Windows 11",
                    "total_ram_gb": 16,
                    "free_ram_gb": 8,
                    "cpu": "Intel",
                },
                "installed_apps": [
                    {"DisplayName": "Edge"},
                    {"DisplayName": "Code"},
                    {"DisplayName": "Candy Crush"},
                ],
                "enabled_features": [{"FeatureName": "XboxGameMonitoring"}],
                "disk_space": [{"Name": "C:", "Free(GB)": 100}],
            }

        system_info = snapshot.get("system_info", {})
        apps = snapshot.get("installed_apps", [])
        features = snapshot.get("enabled_features", [])
        disk = snapshot.get("disk_space", [])

        prompt = f"""You are a PC optimization expert. Analyze this system and recommend cleanup actions.

System:
- Hostname: {system_info.get("hostname", "unknown")}
- OS: {system_info.get("os", "unknown")}
- RAM: {system_info.get("total_ram_gb", "?")}GB total, {system_info.get("free_ram_gb", "?")}GB free

Installed Applications ({len(apps)}):
{", ".join([a.get("DisplayName", "Unknown")[:50] for a in apps[:20]])}

Enabled Windows Features:
{", ".join([f.get("FeatureName", "Unknown") for f in features[:10]])}

Disk Space:
{json.dumps(disk[:5], indent=2)}

Generate a JSON list of tasks to optimize this PC. Return ONLY a JSON array with task and param fields.
"""

        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "gemma4:e2b", "prompt": prompt, "stream": False},
            timeout=120,
        )
        logger.info(f"Ollama response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            ai_response = data.get("response", "")
            logger.info(f"AI Response: {ai_response[:500]}")

            # Strip markdown code blocks if present
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0]
            elif "```" in ai_response:
                try:
                    ai_response = ai_response.split("```")[1].split("```")[0]
                except:
                    pass

            ai_response = ai_response.strip()
            logger.info(f"Cleaned AI Response: {ai_response[:300]}")

            try:
                tasks = json.loads(ai_response)
                # Map AI task names to agent task names
                mapped_tasks = []
                task_mapping = {
                    "disk cleanup": "cleanup_temp_files",
                    "cleanup temp files": "cleanup_temp_files",
                    "cleanup temporary files": "cleanup_temp_files",
                    "temp file cleanup": "cleanup_temp_files",
                    "browser cache": "cleanup_browser_cache",
                    "browser cache cleanup": "cleanup_browser_cache",
                    "windows update cache": "cleanup_windows_update_cache",
                    "recycle bin": "empty_recycle_bin",
                    "empty recycle bin": "empty_recycle_bin",
                    "telemetry": "disable_windows_telemetry",
                    "disable telemetry": "disable_windows_telemetry",
                    "xbox": "disable_xbox_features",
                    "xbox features": "disable_xbox_features",
                    "game mode": "disable_xbox_features",
                    "cortana": "disable_cortana",
                    "advertising id": "disable_advertising_id",
                    "application review": "get_installed_apps",
                    "app review": "get_installed_apps",
                    "uninstall app": "uninstall_app",
                    "uninstall application": "uninstall_app",
                }

                for t in tasks:
                    task_name = t.get("task", "").lower()
                    param = t.get("param")

                    # Check if we have a direct mapping
                    mapped_name = None
                    for key, value in task_mapping.items():
                        if key in task_name:
                            mapped_name = value
                            break

                    if mapped_name:
                        mapped_tasks.append({"task": mapped_name, "param": param})
                    else:
                        logger.warning(f"Could not map task: {t.get('task')}")

                return {"analysis": "success", "recommended_tasks": mapped_tasks}
            except json.JSONDecodeError as ex:
                logger.error(f"JSON parse error: {ex}")
                return {
                    "analysis": "error",
                    "message": "Failed to parse AI response",
                    "raw": ai_response[:500],
                }
        else:
            logger.error(f"Ollama error: {response.text}")
            return {"analysis": "error", "message": "Ollama API failed"}

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return {"analysis": "error", "message": str(e)}


async def receive_snapshot(device_id: str = None, data: dict = None):
    if data is None:
        raise HTTPException(status_code=400, detail="JSON body required")
    if not device_id:
        device_id = data.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO system_snapshots (device_id, snapshot_json, created_at)
        VALUES (?, ?, ?)
    """,
        (device_id, json.dumps(data), datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()

    return {"status": "saved"}


@app.post("/execute/{device_id}/{task}")
async def execute_task_direct(device_id: str, task: str, param: str = None):
    """Execute a task directly on the server (for testing/single PC use)"""
    import subprocess
    import sys
    import os

    # Try to find agent directory - works locally but not on Railway
    possible_paths = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "pc-optimizer-agent"),
        os.path.join(os.getcwd(), "pc-optimizer-agent"),
        os.path.join(os.path.dirname(__file__), "..", "pc-optimizer-agent"),
    ]

    agent_dir = None
    for path in possible_paths:
        if os.path.exists(path):
            agent_dir = path
            break

    if agent_dir:
        sys.path.insert(0, agent_dir)

    try:
        # Try to import from agent - will fail on Railway
        from tasks import execute_task

        # Also get disk space for the meters
        disk_result = execute_task("get_disk_space")

        result = execute_task(task, param)

        # Include disk info in result
        if disk_result and task != "get_disk_space":
            result["disk_space"] = disk_result

        # Also report the result
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

        command_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO commands (id, device_id, task, param, status, created_at, completed_at, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                command_id,
                device_id,
                task,
                param,
                "completed",
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                json.dumps(result),
            ),
        )

        conn.commit()
        conn.close()

        return {"success": True, "task": task, "result": result}
    except ImportError as e:
        # On Railway - return mock data for demo purposes
        logger.warning(f"Agent not available on Railway - using mock data. Error: {e}")

        # Generate mock system info for demonstration
        if task == "get_system_info":
            result = {
                "hostname": f"device-{device_id[:8]}",
                "os": "Windows 11 Pro",
                "os_version": "10.0.22631",
                "total_ram_gb": 16.0,
                "free_ram_gb": 8.5,
                "cpu": "Intel Core i7-12700K",
            }
        elif task == "get_disk_space":
            result = [
                {"Name": "C", "Used(GB)": 125.5, "Free(GB)": 74.5},
                {"Name": "D", "Used(GB)": 250.0, "Free(GB)": 750.0},
            ]
        elif "cleanup" in task:
            result = {
                "success": True,
                "results": [
                    f"Simulated {task} - 500MB freed",
                    "Cache cleared successfully",
                    "Temp files removed",
                ],
            }
        elif "disable" in task:
            result = {
                "success": True,
                "results": [f"Simulated {task} - Settings applied"],
            }
        else:
            result = {"success": True, "message": f"Task {task} simulated on Railway"}

        # Store in database
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            command_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO commands (id, device_id, task, param, status, created_at, completed_at, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    command_id,
                    device_id,
                    task,
                    param,
                    "completed",
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    json.dumps(result),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as db_err:
            logger.error(f"DB write failed: {db_err}")

        return {"success": True, "task": task, "result": result, "simulated": True}

    except Exception as e:
        logger.error(f"Direct execution failed: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
