from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime, select
from sqlalchemy.sql import func
import uuid
from datetime import datetime
import logging
import json
import requests
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PC Optimizer Cloud API")

PORT = int(os.getenv("PORT", 8000))
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///optimizer.db"
    logger.warning("DATABASE_URL not set, using SQLite")

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


def get_async_db_url(url: str) -> str:
    """Convert sync DB URL to async URL"""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    return url


async_engine = None
AsyncSessionLocal = None


def get_db_engine():
    global async_engine, AsyncSessionLocal
    if async_engine is None:
        db_url = get_async_db_url(DATABASE_URL)
        logger.info(f"Connecting to database: {db_url[:50]}...")

        engine_kwargs = {"echo": False}

        if not db_url.startswith("sqlite"):
            engine_kwargs.update(
                {
                    "pool_pre_ping": True,
                    "pool_size": 10,
                    "max_overflow": 20,
                }
            )

        async_engine = create_async_engine(db_url, **engine_kwargs)
        AsyncSessionLocal = sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
    return async_engine


Base = declarative_base()


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True)
    hostname = Column(String)
    registered_at = Column(DateTime, default=datetime.now)
    last_seen = Column(DateTime, default=datetime.now)
    status = Column(String, default="online")


class Command(Base):
    __tablename__ = "commands"

    id = Column(String, primary_key=True)
    device_id = Column(String, nullable=False)
    task = Column(String)
    param = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    result = Column(Text, nullable=True)


class SystemSnapshot(Base):
    __tablename__ = "system_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, nullable=False)
    snapshot_json = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


async def init_db():
    get_db_engine()
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "pc-optimizer-api"}


@app.get("/healthz")
async def health_check_alt():
    return {"status": "healthy"}


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
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == device.device_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.hostname = device.hostname
            existing.last_seen = datetime.now()
        else:
            new_device = Device(
                device_id=device.device_id,
                hostname=device.hostname,
                registered_at=datetime.now(),
                last_seen=datetime.now(),
            )
            session.add(new_device)

        await session.commit()

    logger.info(f"Device registered: {device.device_id}")
    return {"status": "registered", "device_id": device.device_id}


@app.get("/devices")
async def list_devices():
    async with AsyncSessionLocal() as session:
        stmt = select(Device)
        result = await session.execute(stmt)
        devices = result.scalars().all()

    return [
        {
            "device_id": d.device_id,
            "hostname": d.hostname,
            "registered_at": d.registered_at.isoformat() if d.registered_at else None,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
            "status": d.status,
        }
        for d in devices
    ]


@app.get("/commands/{device_id}")
async def get_commands(device_id: str):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Command)
            .where(Command.device_id == device_id, Command.status == "pending")
            .order_by(Command.created_at.asc())
        )
        result = await session.execute(stmt)
        commands = result.scalars().all()

    return [
        {"id": c.id, "task": c.task, "param": c.param, "status": c.status}
        for c in commands
    ]


@app.post("/command")
async def send_command(command: TaskCommand):
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == command.device_id)
        result = await session.execute(stmt)
        device = result.scalar_one_or_none()

        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        command_id = str(uuid.uuid4())
        new_command = Command(
            id=command_id,
            device_id=command.device_id,
            task=command.task,
            param=command.param,
            status="pending",
            created_at=datetime.now(),
        )
        session.add(new_command)
        await session.commit()

    logger.info(f"Command queued: {command.task} for device {command.device_id}")
    return {"command_id": command_id, "status": "queued"}


@app.post("/result")
async def receive_result(result: CommandResult):
    async with AsyncSessionLocal() as session:
        stmt = select(Command).where(
            Command.device_id == result.device_id, Command.task == result.task
        )
        command = (await session.execute(stmt)).scalar_one_or_none()

        if command:
            command.status = "completed"
            command.result = json.dumps(result.result)
            command.completed_at = datetime.now()

        stmt = select(Device).where(Device.device_id == result.device_id)
        device = (await session.execute(stmt)).scalar_one_or_none()
        if device:
            device.last_seen = datetime.now()

        await session.commit()

    logger.info(f"Result received: {result.task} from {result.device_id}")
    return {"status": "received"}


@app.post("/status")
async def receive_status(data: dict):
    device_id = data.get("device_id")
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == device_id)
        device = (await session.execute(stmt)).scalar_one_or_none()
        if device:
            device.last_seen = datetime.now()
            await session.commit()

    return {"status": "ok"}


@app.get("/device/{device_id}/history")
async def get_device_history(device_id: str):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Command)
            .where(Command.device_id == device_id)
            .order_by(Command.created_at.desc())
            .limit(50)
        )
        result = await session.execute(stmt)
        history = result.scalars().all()

    return [
        {
            "id": h.id,
            "task": h.task,
            "param": h.param,
            "status": h.status,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "completed_at": h.completed_at.isoformat() if h.completed_at else None,
            "result": json.loads(h.result) if h.result else None,
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

    async with AsyncSessionLocal() as session:
        stmt = (
            select(SystemSnapshot)
            .where(SystemSnapshot.device_id == device_id)
            .order_by(SystemSnapshot.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        snapshot_row = result.scalar_one_or_none()

    if not snapshot_row:
        raise HTTPException(status_code=404, detail="No system snapshot found")

    snapshot = json.loads(snapshot_row.snapshot_json)

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

    snapshot = {
        "system_info": {
            "hostname": system_info.get("hostname", "TEST-PC"),
            "os": system_info.get("os", "Windows 11"),
            "total_ram_gb": system_info.get("total_ram_gb", 16),
            "free_ram_gb": system_info.get("free_ram_gb", 8),
            "cpu": system_info.get("cpu", "Intel"),
        },
        "installed_apps": [
            {"DisplayName": a.get("DisplayName", "Unknown")} for a in apps[:20]
        ],
        "enabled_features": [
            {"FeatureName": f.get("FeatureName", "Unknown")} for f in features[:10]
        ],
        "disk_space": disk[:5],
    }

    try:
        logger.info(f"Sending request to Ollama for device {device_id}")
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
                }

                for t in tasks:
                    task_name = t.get("task", "").lower()
                    param = t.get("param")

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


@app.post("/snapshot")
async def receive_snapshot(data: dict):
    device_id = data.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    async with AsyncSessionLocal() as session:
        snapshot = SystemSnapshot(
            device_id=device_id,
            snapshot_json=json.dumps(data),
            created_at=datetime.now(),
        )
        session.add(snapshot)
        await session.commit()

    return {"status": "saved"}


@app.post("/execute/{device_id}/{task}")
async def execute_task_direct(device_id: str, task: str, param: str = None):
    import subprocess
    import sys

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
        from tasks import execute_task

        disk_result = execute_task("get_disk_space")
        result = execute_task(task, param)

        if disk_result and task != "get_disk_space":
            result["disk_space"] = disk_result

        async with AsyncSessionLocal() as session:
            command_id = str(uuid.uuid4())
            new_command = Command(
                id=command_id,
                device_id=device_id,
                task=task,
                param=param,
                status="completed",
                created_at=datetime.now(),
                completed_at=datetime.now(),
                result=json.dumps(result),
            )
            session.add(new_command)
            await session.commit()

        return {"success": True, "task": task, "result": result}

    except ImportError as e:
        logger.warning(f"Agent not available on Railway - using mock data. Error: {e}")

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

        try:
            async with AsyncSessionLocal() as session:
                command_id = str(uuid.uuid4())
                new_command = Command(
                    id=command_id,
                    device_id=device_id,
                    task=task,
                    param=param,
                    status="completed",
                    created_at=datetime.now(),
                    completed_at=datetime.now(),
                    result=json.dumps(result),
                )
                session.add(new_command)
                await session.commit()
        except Exception as db_err:
            logger.error(f"DB write failed: {db_err}")

        return {"success": True, "task": task, "result": result, "simulated": True}

    except Exception as e:
        logger.error(f"Direct execution failed: {e}")
        return {"success": False, "error": str(e)}


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Database initialized successfully")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
