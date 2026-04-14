"""
PC Optimizer Cloud - FastAPI Backend
Clean architecture with extracted templates and proper configuration
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime, select

# ============================================================================
# Configuration
# ============================================================================


class Config:
    """Application configuration with validation"""

    # API URL for frontend (can be overridden via env)
    API_URL = os.getenv("API_URL", "https://pc-optimizer-ai.onrender.com")

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    # CORS - Whitelist specific domains for security
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "https://pc-optimizer-ai.onrender.com,http://localhost:3000,http://localhost:8000",
    ).split(",")

    # Port
    PORT = int(os.getenv("PORT", 8000))

    @classmethod
    def get_db_url(cls) -> str:
        """Get validated database URL"""
        if not cls.is_valid_database_url(cls.DATABASE_URL):
            if os.path.exists("/tmp") or os.name != "nt":
                return "sqlite+aiosqlite:////tmp/optimizer.db"
            return "sqlite+aiosqlite:///optimizer.db"

        if cls.DATABASE_URL.startswith("postgresql://"):
            return cls.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        if cls.DATABASE_URL.startswith("sqlite://"):
            return cls.DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://")
        return cls.DATABASE_URL

    @staticmethod
    def is_valid_database_url(url: str) -> bool:
        """Validate database URL format"""
        if not url:
            return False
        invalid_patterns = [
            "host",
            "port",
            "username",
            "password",
            "your-",
            "undefined",
            "null",
        ]
        url_lower = url.lower()
        return not any(p in url_lower for p in invalid_patterns) and (
            url.startswith("postgresql://") or url.startswith("sqlite://")
        )


# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Database Setup
# ============================================================================

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


# Database engine and session
async_engine = None
AsyncSessionLocal = None


def get_db_engine():
    global async_engine, AsyncSessionLocal
    if async_engine is None:
        db_url = Config.get_db_url()
        logger.info(f"Database URL: {db_url[:50]}...")

        engine_kwargs = {"echo": False}
        if not db_url.startswith("sqlite"):
            engine_kwargs.update(
                {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}
            )

        async_engine = create_async_engine(db_url, **engine_kwargs)
        AsyncSessionLocal = sessionmaker(
            async_engine, class_=AsyncSession, expire_on_commit=False
        )
    return async_engine


async def init_db():
    engine = get_db_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")


# ============================================================================
# Pydantic Models
# ============================================================================


class DeviceRegister(BaseModel):
    device_id: str
    api_key: str
    hostname: str


class TaskCommand(BaseModel):
    device_id: str
    task: str
    param: Optional[str] = None
    require_approval: bool = True


class ScanRequest(BaseModel):
    device_id: Optional[str] = None


class CommandResult(BaseModel):
    device_id: str
    task: str
    result: dict
    command_id: Optional[str] = None


class SystemInfo(BaseModel):
    device_id: str
    hostname: str
    os: str
    os_version: Optional[str] = None
    architecture: Optional[str] = None
    processor: Optional[str] = None
    cpu_cores: Optional[int] = None
    total_ram_gb: Optional[float] = None
    free_ram_gb: Optional[float] = None
    used_ram_gb: Optional[float] = None
    ram_percent: Optional[float] = None
    cpu_percent: Optional[float] = None
    disk_space: Optional[list] = None
    boot_time: Optional[str] = None
    timestamp: Optional[str] = None


# In-memory storage for latest system info
latest_system_info: dict = {}


# ============================================================================
# FastAPI App
# ============================================================================


# Use traditional startup_event instead of lifespan to avoid issues
app = FastAPI(
    title="PC Optimizer AI",
    description="Cloud dashboard for PC optimization with AI recommendations",
    version="2.0.0",
)


@app.on_event("startup")
async def startup():
    """Initialize database on startup"""
    await init_db()
    logger.info("PC Optimizer API started")


# CORS - Whitelist specific origins for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ============================================================================
# Health Check Endpoints
# ============================================================================


@app.get("/health", tags=["health"])
async def health_check():
    """Basic health check"""
    return {"status": "ok", "service": "pc-optimizer-api", "version": "2.0.0"}


@app.get("/healthz", tags=["health"])
async def health_check_alt():
    """Kubernetes-compatible health check"""
    return {"status": "healthy"}


@app.get("/ready", tags=["health"])
async def readiness_check():
    """Readiness check - verifies database connectivity"""
    try:
        await init_db()
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}


# ============================================================================
# Template & Static Files
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

if os.path.exists(STATIC_DIR):
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse, tags=["ui"])
async def root():
    """Serve the dashboard - reads from template file"""
    template_path = os.path.join(TEMPLATES_DIR, "index.html")

    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        # Replace API_URL placeholder with actual value
        html_content = html_content.replace("{{API_URL}}", Config.API_URL)
        return HTMLResponse(content=html_content)

    return HTMLResponse(content="<h1>Template not found</h1>", status_code=500)


# ============================================================================
# Device Management
# ============================================================================


@app.get("/devices", tags=["devices"])
async def get_devices():
    """List all registered devices"""
    async with AsyncSessionLocal() as session:
        stmt = select(Device).order_by(Device.last_seen.desc())
        result = await session.execute(stmt)
        devices = result.scalars().all()
        return [
            {
                "device_id": d.device_id,
                "hostname": d.hostname,
                "registered_at": d.registered_at.isoformat()
                if d.registered_at
                else None,
                "last_seen": d.last_seen.isoformat() if d.last_seen else None,
                "status": d.status,
            }
            for d in devices
        ]


@app.post("/register", tags=["devices"])
async def register_device(data: DeviceRegister):
    """Register or update a device"""
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == data.device_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.hostname = data.hostname
            existing.last_seen = datetime.now()
            existing.status = "online"
            await session.commit()
            logger.info(f"Device updated: {data.device_id}")
            return {
                "status": "registered",
                "device_id": data.device_id,
                "updated": True,
            }
        else:
            new_device = Device(
                device_id=data.device_id, hostname=data.hostname, status="online"
            )
            session.add(new_device)
            await session.commit()
            logger.info(f"New device registered: {data.device_id}")
            return {
                "status": "registered",
                "device_id": data.device_id,
                "updated": False,
            }


@app.post("/result", tags=["devices"])
async def receive_result(result: CommandResult):
    """Receive task execution result from agent"""
    async with AsyncSessionLocal() as session:
        if result.command_id:
            stmt = select(Command).where(Command.id == result.command_id)
        else:
            stmt = select(Command).where(
                Command.device_id == result.device_id,
                Command.task == result.task,
                Command.status == "pending",
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


@app.post("/status", tags=["devices"])
async def receive_status(data: dict):
    """Receive device heartbeat/status"""
    device_id = data.get("device_id")
    is_agent = data.get("is_agent", False)
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == device_id)
        device = (await session.execute(stmt)).scalar_one_or_none()
        if device:
            device.last_seen = datetime.now()
            device.status = "online" if is_agent else device.status
            await session.commit()
    return {"status": "ok", "is_agent": is_agent}


@app.get("/device/{device_id}/agent-status", tags=["devices"])
async def get_agent_status(device_id: str):
    """Check if agent is online (last_seen < 30 seconds)"""
    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == device_id)
        device = (await session.execute(stmt)).scalar_one_or_none()

        if not device:
            return {"agent_online": False, "message": "Device not registered"}

        now = datetime.now()
        last_seen = device.last_seen
        time_diff = (now - last_seen).total_seconds() if last_seen else 999
        agent_online = time_diff < 30

        return {
            "agent_online": agent_online,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "time_since_seen": time_diff,
            "device_id": device_id,
            "hostname": device.hostname,
        }


@app.get("/device/{device_id}/history", tags=["devices"])
async def get_device_history(device_id: str):
    """Get command history for a device"""
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


# ============================================================================
# System Info
# ============================================================================


@app.post("/device/{device_id}/system-info", tags=["system"])
async def receive_system_info(device_id: str, info: SystemInfo):
    """Receive real system info from local scanner"""
    global latest_system_info
    info_dict = info.model_dump(exclude_none=True)
    latest_system_info[device_id] = info_dict
    logger.info(
        f"Received system info from {device_id}: RAM {info_dict.get('ram_percent')}%"
    )

    async with AsyncSessionLocal() as session:
        stmt = select(Device).where(Device.device_id == device_id)
        device = (await session.execute(stmt)).scalar_one_or_none()
        if device:
            device.last_seen = datetime.now()
            device.status = "online"
            await session.commit()
        else:
            new_device = Device(
                device_id=device_id, hostname=info.hostname, status="online"
            )
            session.add(new_device)
            await session.commit()

    return {"status": "received", "device_id": device_id}


@app.get("/device/{device_id}/system-info", tags=["system"])
async def get_device_system_info(device_id: str):
    """Get latest system info for a device"""
    if device_id in latest_system_info:
        return latest_system_info[device_id]
    return {"error": "No system info available. Run local-scanner.py on this device."}


# ============================================================================
# Task Execution
# ============================================================================


@app.post("/execute/{device_id}/{task}", tags=["tasks"])
async def execute_task_direct(device_id: str, task: str, param: str = None):
    """Execute optimization task - uses local agent if available, falls back to mock"""
    import subprocess
    import sys

    # Find agent directory
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "pc-optimizer-agent"),
        os.path.join(os.getcwd(), "pc-optimizer-agent"),
    ]
    agent_dir = next((p for p in possible_paths if os.path.exists(p)), None)

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
            logger.warning(f"Agent import failed: {e}")

    # Fallback to mock data
    logger.warning("Using mock data - agent not available")
    if task == "get_system_info":
        result = {
            "hostname": f"device-{device_id[:8]}",
            "os": "Windows 11 Pro",
            "total_ram_gb": 16.0,
            "free_ram_gb": 8.5,
        }
    elif task == "get_disk_space":
        result = [{"Name": "C", "Used(GB)": 125.5, "Free(GB)": 74.5}]
    elif "cleanup" in task:
        result = {"success": True, "results": [f"Simulated {task} - 500MB freed"]}
    elif "disable" in task:
        result = {"success": True, "results": [f"Simulated {task} - Settings applied"]}
    else:
        result = {"success": True, "message": f"Task {task} simulated"}

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


# ============================================================================
# AI Analysis
# ============================================================================


@app.post("/analyze", tags=["ai"])
async def analyze_system(
    device_id: Optional[str] = None, request: Optional[ScanRequest] = None
):
    """AI-powered system analysis and optimization recommendations"""
    if request:
        device_id = request.device_id
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

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
        raise HTTPException(
            status_code=404,
            detail="No system snapshot found. Run local-scanner.py first.",
        )

    snapshot = json.loads(snapshot_row.snapshot_json)
    system_info = snapshot.get("system_info", {})
    apps = snapshot.get("installed_apps", [])
    features = snapshot.get("enabled_features", [])

    prompt = f"""Analyze this PC and recommend optimization tasks.

System: {system_info.get("hostname", "Unknown")} - {system_info.get("os", "Unknown")}
RAM: {system_info.get("total_ram_gb", "?")}GB total

Return a JSON array of tasks: [{{"task": "cleanup_temp_files", "param": null}}]

Available tasks: cleanup_temp_files, cleanup_browser_cache, empty_recycle_bin, disable_windows_telemetry, disable_xbox_features, cleanup_ram"""

    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    if not GOOGLE_API_KEY:
        return {
            "analysis": "error",
            "message": "Google API key not configured. Set GOOGLE_API_KEY environment variable.",
        }

    try:
        import google.genai as genai

        client = genai.Client(api_key=GOOGLE_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite", contents=prompt
        )

        ai_response = response.text.strip()
        if "```json" in ai_response:
            ai_response = ai_response.split("```json")[1].split("```")[0]

        tasks = json.loads(ai_response)
        task_mapping = {
            "disk cleanup": "cleanup_temp_files",
            "temp file": "cleanup_temp_files",
            "browser cache": "cleanup_browser_cache",
            "recycle bin": "empty_recycle_bin",
            "telemetry": "disable_windows_telemetry",
            "xbox": "disable_xbox_features",
            "ram cleanup": "cleanup_ram",
            "memory": "cleanup_ram",
        }

        mapped_tasks = []
        for t in tasks:
            task_name = t.get("task", "").lower()
            mapped_name = next(
                (v for k, v in task_mapping.items() if k in task_name), None
            )
            if mapped_name:
                mapped_tasks.append({"task": mapped_name, "param": t.get("param")})

        return {"analysis": "success", "recommended_tasks": mapped_tasks}
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {"analysis": "error", "message": str(e)}


# ============================================================================
# Snapshot
# ============================================================================


@app.post("/snapshot", tags=["system"])
async def receive_snapshot(data: dict):
    """Receive system snapshot from local scanner"""
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


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=Config.PORT)
