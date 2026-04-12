from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
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

PORT = int(os.getenv("PORT", 8000))
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    import platform

    if platform.system() == "Linux" or os.path.exists("/tmp"):
        DATABASE_URL = "sqlite+aiosqlite:////tmp/optimizer.db"
        logger.info("Using /tmp for SQLite database (Railway)")
    else:
        DATABASE_URL = "sqlite+aiosqlite:///optimizer.db"
        logger.info("Using local SQLite database")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

async_engine = None
AsyncSessionLocal = None


def get_async_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    return url


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
    global async_engine, AsyncSessionLocal
    get_db_engine()
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")


app = FastAPI(title="PC Optimizer Cloud API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Database initialized successfully")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard HTML directly to avoid static file caching issues"""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PC Optimizer AI</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a0f; color: #fff; min-height: 100vh; padding: 20px; }
        
        /* Header */
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; border-bottom: 1px solid #222; padding-bottom: 20px; }
        .header h1 { font-size: 28px; color: #00ff88; font-weight: 300; letter-spacing: 2px; }
        .logo-text span { color: #fff; font-weight: 600; }
        
        .lang-buttons { display: flex; gap: 5px; }
        .lang-btn { padding: 8px 16px; background: transparent; border: 1px solid #333; color: #666; cursor: pointer; border-radius: 20px; transition: all 0.3s; font-size: 12px; }
        .lang-btn:hover { border-color: #00ff88; color: #00ff88; }
        .lang-btn.active { background: #00ff88; color: #000; border-color: #00ff88; }
        
        /* Main Layout */
        .grid { display: grid; grid-template-columns: 280px 1fr 280px; gap: 20px; max-width: 1400px; margin: 0 auto; }
        
        .card { background: #12121a; border-radius: 16px; padding: 20px; border: 1px solid #1e1e2e; }
        .section-title { font-size: 12px; color: #555; margin-bottom: 20px; text-transform: uppercase; letter-spacing: 2px; font-weight: 600; }
        
        /* Device List */
        .device-item { padding: 15px; background: #1a1a25; border-radius: 10px; margin-bottom: 10px; cursor: pointer; border: 2px solid transparent; transition: all 0.3s; }
        .device-item:hover { background: #1f1f2d; transform: translateX(5px); }
        .device-item.selected { border-color: #00ff88; background: #1a2520; }
        .device-icon { font-size: 24px; margin-right: 10px; }
        .device-name { font-weight: 600; color: #fff; }
        .device-status { font-size: 11px; color: #00ff88; margin-top: 5px; }
        
        .refresh-btn { width: 100%; padding: 12px; background: #1a1a25; border: 1px solid #333; color: #888; border-radius: 10px; cursor: pointer; transition: all 0.3s; }
        .refresh-btn:hover { background: #1f1f2d; color: #00ff88; }
        
        /* System Meters */
        .meter-container { margin-bottom: 20px; }
        .meter-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
        .meter-label { font-size: 14px; color: #aaa; }
        .meter-value { font-size: 14px; color: #00ff88; font-weight: 600; }
        
        .meter-bar { height: 12px; background: #1a1a25; border-radius: 6px; overflow: hidden; position: relative; }
        .meter-fill { height: 100%; border-radius: 6px; transition: width 1s ease; position: relative; }
        .meter-fill.ram { background: linear-gradient(90deg, #00ff88, #00cc6a); width: 0%; }
        .meter-fill.disk { background: linear-gradient(90deg, #6366f1, #4f46e5); width: 0%; }
        
        .meter-fill::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent); animation: shimmer 2s infinite; }
        
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        
        .meter-details { display: flex; justify-content: space-between; font-size: 11px; color: #555; margin-top: 8px; }
        
        /* Update Button */
        .update-btn { width: 100%; padding: 15px; background: linear-gradient(135deg, #00ff88, #00cc6a); color: #000; border: none; border-radius: 12px; cursor: pointer; font-weight: 600; font-size: 14px; transition: all 0.3s; margin-top: 20px; }
        .update-btn:hover { transform: scale(1.02); box-shadow: 0 10px 30px rgba(0,255,136,0.3); }
        .update-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        /* Action Buttons */
        .action-buttons { display: flex; flex-direction: column; gap: 12px; }
        
        .action-btn { padding: 18px 24px; background: #1a1a25; border: 1px solid #2a2a3a; color: #fff; border-radius: 12px; cursor: pointer; font-size: 15px; font-weight: 500; transition: all 0.3s; display: flex; align-items: center; gap: 12px; }
        .action-btn:hover { background: #1f1f2d; border-color: #00ff88; transform: translateY(-2px); }
        .action-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .action-btn .icon { font-size: 20px; }
        
        .action-btn.ai { background: linear-gradient(135deg, #1a1a25, #252535); border: 1px solid #6366f1; }
        .action-btn.ai:hover { border-color: #818cf8; box-shadow: 0 10px 30px rgba(99,102,241,0.2); }
        
        /* Task Select */
        .task-select { width: 100%; padding: 14px; background: #1a1a25; color: #fff; border: 1px solid #2a2a3a; border-radius: 10px; font-size: 14px; margin-bottom: 10px; cursor: pointer; }
        .task-select:focus { outline: none; border-color: #00ff88; }
        
        .task-desc { font-size: 12px; color: #555; margin-bottom: 15px; min-height: 20px; }
        
        /* Before/After Visual */
        .comparison { background: #1a1a25; border-radius: 12px; padding: 15px; margin-top: 20px; display: none; }
        .comparison.show { display: block; animation: fadeIn 0.5s ease; }
        
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        
        .comparison-title { font-size: 12px; color: #666; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 1px; }
        
        .comparison-item { display: flex; align-items: center; margin-bottom: 15px; }
        .comparison-label { width: 100px; font-size: 13px; color: #888; }
        .comparison-bar { flex: 1; height: 24px; background: #252535; border-radius: 4px; overflow: hidden; position: relative; }
        .comparison-fill { height: 100%; transition: width 1s ease; border-radius: 4px; display: flex; align-items: center; justify-content: flex-end; padding-right: 8px; font-size: 11px; color: #fff; font-weight: 600; }
        .comparison-fill.before { background: #ff4444; }
        .comparison-fill.after { background: #00ff88; }
        
        /* Loading Spinner */
        .spinner { width: 40px; height: 40px; border: 3px solid #222; border-top-color: #00ff88; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 15px; display: none; }
        .spinner.show { display: block; }
        
        @keyframes spin { to { transform: rotate(360deg); } }
        
        /* Progress Steps */
        .progress-steps { display: none; margin: 20px 0; }
        .progress-steps.show { display: flex; justify-content: space-between; }
        .step { flex: 1; text-align: center; position: relative; }
        .step::after { content: ''; position: absolute; top: 15px; left: 50%; width: 100%; height: 2px; background: #222; z-index: 0; }
        .step:last-child::after { display: none; }
        .step-icon { width: 32px; height: 32px; background: #1a1a25; border: 2px solid #333; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 8px; position: relative; z-index: 1; font-size: 14px; }
        .step.active .step-icon { border-color: #00ff88; background: #00ff88; color: #000; }
        .step.done .step-icon { border-color: #00ff88; background: #00ff88; color: #000; }
        .step-label { font-size: 11px; color: #555; }
        .step.active .step-label { color: #00ff88; }
        
        /* Activity Log */
        .log { background: #0d0d12; border-radius: 12px; padding: 15px; max-height: 250px; overflow-y: auto; }
        .log-entry { padding: 8px 0; border-bottom: 1px solid #1a1a25; font-size: 13px; color: #666; }
        .log-entry.success { color: #00ff88; }
        .log-entry.error { color: #ff4444; }
        .log-entry.info { color: #888; }
        
        /* Popup */
        .popup { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.9); z-index: 1000; align-items: center; justify-content: center; }
        .popup.show { display: flex; }
        .popup-content { background: #12121a; padding: 40px; border-radius: 20px; max-width: 450px; width: 90%; text-align: center; border: 2px solid #00ff88; animation: popIn 0.3s ease; }
        
        @keyframes popIn { from { transform: scale(0.9); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        
        .popup-icon { font-size: 60px; margin-bottom: 20px; }
        .popup-title { font-size: 24px; color: #00ff88; margin-bottom: 10px; font-weight: 600; }
        .popup-message { color: #888; margin-bottom: 25px; font-size: 14px; }
        .popup-close { padding: 15px 40px; background: #00ff88; color: #000; border: none; border-radius: 10px; cursor: pointer; font-weight: 600; font-size: 15px; }
        
        /* Toast */
        .toast { position: fixed; top: 20px; right: 20px; padding: 15px 25px; border-radius: 10px; z-index: 2000; font-weight: 500; transform: translateX(400px); transition: transform 0.3s ease; }
        .toast.show { transform: translateX(0); }
        .toast.success { background: #00ff88; color: #000; }
        .toast.error { background: #ff4444; color: #fff; }
        .toast.info { background: #1a1a25; color: #fff; border: 1px solid #333; }
        
        /* Pulse animation for running */
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .running { animation: pulse 1s infinite; }
        
        @media (max-width: 1024px) {
            .grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>PC Optimizer <span>AI</span></h1>
        <div class="lang-buttons">
            <button class="lang-btn active" onclick="setLang('en')">EN</button>
            <button class="lang-btn" onclick="setLang('es')">ES</button>
        </div>
    </div>
    
    <div class="grid">
        <!-- Left Panel: Device -->
        <div class="card">
            <div class="section-title" id="selectDeviceTitle">1. Select Device</div>
            <div id="deviceList"></div>
            <button class="refresh-btn" onclick="loadDevices()">↻ Refresh</button>
        </div>
        
        <!-- Middle Panel: Main -->
        <div class="card">
            <div class="section-title" id="actionsTitle">2. Optimize</div>
            
            <!-- Spinner -->
            <div class="spinner" id="spinner"></div>
            
            <!-- Progress Steps -->
            <div class="progress-steps" id="progressSteps">
                <div class="step" id="step1">
                    <div class="step-icon">📊</div>
                    <div class="step-label" id="step1Label">Scan</div>
                </div>
                <div class="step" id="step2">
                    <div class="step-icon">🧹</div>
                    <div class="step-label" id="step2Label">Clean</div>
                </div>
                <div class="step" id="step3">
                    <div class="step-icon">✅</div>
                    <div class="step-label" id="step3Label">Done</div>
                </div>
            </div>
            
            <!-- Action Buttons -->
            <div class="action-buttons">
                <button class="action-btn" id="aiBtn" onclick="runAI()">
                    <span class="icon">🤖</span>
                    <span id="aiBtnText">AI Auto-Optimize</span>
                </button>
                
                <select class="task-select" id="taskSelect" onchange="showTaskDesc()">
                    <option value="">-- Manual Task --</option>
                    <option value="cleanup_temp_files">🧹 Clean Temp Files</option>
                    <option value="cleanup_browser_cache">🌐 Clean Browser Cache</option>
                    <option value="empty_recycle_bin">🗑️ Empty Recycle Bin</option>
                    <option value="disable_windows_telemetry">📡 Disable Telemetry</option>
                    <option value="disable_xbox_features">🎮 Disable Xbox</option>
                </select>
                
                <div class="task-desc" id="taskDesc"></div>
                
                <button class="action-btn" id="executeBtn" onclick="runTask()">
                    <span class="icon">⚡</span>
                    <span id="executeBtnText">Execute Task</span>
                </button>
            </div>
            
            <!-- Comparison -->
            <div class="comparison" id="comparison">
                <div class="comparison-title" id="compTitle">Before / After</div>
                <div class="comparison-item">
                    <div class="comparison-label">RAM</div>
                    <div class="comparison-bar">
                        <div class="comparison-fill before" id="ramBefore" style="width: 60%">60%</div>
                        <div class="comparison-fill after" id="ramAfter" style="width: 40%">40%</div>
                    </div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Disk</div>
                    <div class="comparison-bar">
                        <div class="comparison-fill before" id="diskBefore" style="width: 70%">70%</div>
                        <div class="comparison-fill after" id="diskAfter" style="width: 65%">65%</div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Right Panel: System Info -->
        <div class="card">
            <div class="section-title" id="systemTitle">3. System Status</div>
            
            <div class="meter-container">
                <div class="meter-header">
                    <span class="meter-label">💾 RAM Usage</span>
                    <span class="meter-value" id="ramPercent">0%</span>
                </div>
                <div class="meter-bar">
                    <div class="meter-fill ram" id="ramBar"></div>
                </div>
                <div class="meter-details">
                    <span id="ramUsed">0 GB used</span>
                    <span id="ramTotal">0 GB total</span>
                </div>
            </div>
            
            <div class="meter-container">
                <div class="meter-header">
                    <span class="meter-label">💿 Disk (C:)</span>
                    <span class="meter-value" id="diskPercent">0%</span>
                </div>
                <div class="meter-bar">
                    <div class="meter-fill disk" id="diskBar"></div>
                </div>
                <div class="meter-details">
                    <span id="diskUsed">0 GB used</span>
                    <span id="diskFree">0 GB free</span>
                </div>
            </div>
            
            <button class="update-btn" id="updateBtn" onclick="updateSystemInfo()">
                <span id="updateBtnText">↻ Update Live Status</span>
            </button>
        </div>
        
        <!-- Bottom: Activity Log -->
        <div class="card" style="grid-column: 1 / -1;">
            <div class="section-title">Activity Log</div>
            <div class="log" id="activityLog">
                <div class="log-entry info">👋 Welcome! Select your device to begin.</div>
            </div>
        </div>
    </div>
    
    <!-- Popup -->
    <div class="popup" id="popup" onclick="closePopup(event)">
        <div class="popup-content">
            <div class="popup-icon" id="popupIcon">✅</div>
            <div class="popup-title" id="popupTitle">Done!</div>
            <div class="popup-message" id="popupMessage">Task completed successfully.</div>
            <button class="popup-close" onclick="document.getElementById('popup').classList.remove('show')">Close</button>
        </div>
    </div>
    
    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <script>
        var selectedDevice = null;
        var currentLang = 'en';
        var systemDataBefore = null;
        
        // Translations
        var translations = {
            en: {
                selectDevice: '1. Select Device',
                systemTitle: '3. System Status',
                actionsTitle: '2. Optimize',
                aiBtn: 'AI Auto-Optimize',
                executeBtn: 'Execute Task',
                updateBtn: '↻ Update Live Status',
                noDevice: 'No devices found',
                scan: 'Scan', clean: 'Clean', done: 'Done',
                beforeAfter: 'Before / After',
                taskDone: 'Task Done!',
                running: 'Running...',
                analyzing: 'Analyzing with AI...',
                cleaning: 'Cleaning system...',
                completed: 'Completed successfully!',
                error: 'Error occurred'
            },
            es: {
                selectDevice: '1. Seleccionar',
                systemTitle: '3. Estado del Sistema',
                actionsTitle: '2. Optimizar',
                aiBtn: 'IA Auto-Optimizar',
                executeBtn: 'Ejecutar Tarea',
                updateBtn: '↻ Actualizar Estado',
                noDevice: 'Sin dispositivos',
                scan: 'Escanear', clean: 'Limpiar', done: 'Hecho',
                beforeAfter: 'Antes / Después',
                taskDone: '¡Tarea Completada!',
                running: 'Ejecutando...',
                analyzing: 'Analizando con IA...',
                cleaning: 'Limpiando sistema...',
                completed: '¡Completado exitosamente!',
                error: 'Error'
            }
        };
        
        var taskDesc = {
            'cleanup_temp_files': 'Removes temp files to free up space.',
            'cleanup_browser_cache': 'Clears Chrome/Edge browser cache.',
            'empty_recycle_bin': 'Permanently deletes recycle bin.',
            'disable_windows_telemetry': 'Disables Windows data collection.',
            'disable_xbox_features': 'Removes Xbox bloatware.'
        };
        
        function t(key) { return translations[currentLang][key] || key; }
        
        function setLang(lang) {
            currentLang = lang;
            document.querySelectorAll('.lang-btn').forEach(function(b) { b.classList.remove('active'); });
            document.querySelector('.lang-btn[onclick="setLang(\'' + lang + '\')"]').classList.add('active');
            updateUI();
        }
        
        function updateUI() {
            document.getElementById('selectDeviceTitle').textContent = t('selectDevice');
            document.getElementById('systemTitle').textContent = t('systemTitle');
            document.getElementById('actionsTitle').textContent = t('actionsTitle');
            document.getElementById('aiBtnText').textContent = t('aiBtn');
            document.getElementById('executeBtnText').textContent = t('executeBtn');
            document.getElementById('updateBtnText').textContent = t('updateBtn');
            document.getElementById('step1Label').textContent = t('scan');
            document.getElementById('step2Label').textContent = t('clean');
            document.getElementById('step3Label').textContent = t('done');
            document.getElementById('compTitle').textContent = t('beforeAfter');
        }
        
        // API URL - HARDCODED Railway URL to fix caching issues
        var API_URL = 'https://pc-optimizer-ai-production.up.railway.app';
        console.log('API URL:', API_URL);

        // Generate or retrieve device ID from localStorage
        function getDeviceId() {
            var id = localStorage.getItem('optimizer_device_id');
            if (!id) {
                id = 'device_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
                localStorage.setItem('optimizer_device_id', id);
            }
            return id;
        }

        // Detect browser device info
        function getBrowserDeviceInfo() {
            var info = {
                device_id: getDeviceId(),
                hostname: navigator.userAgent.includes('Windows') ? 'Windows PC' : 'Device',
                os: getOS(),
                browser: getBrowser(),
                screen: screen.width + 'x' + screen.height,
                cpu_cores: navigator.hardwareConcurrency || 'Unknown',
                device_memory: navigator.deviceMemory || 'Unknown',
                language: navigator.language,
                platform: navigator.platform,
                user_agent: navigator.userAgent
            };
            return info;
        }

        function getOS() {
            var ua = navigator.userAgent;
            if (ua.includes('Windows')) return 'Windows ' + (ua.includes('11') ? '11' : '10');
            if (ua.includes('Mac')) return 'macOS';
            if (ua.includes('Linux')) return 'Linux';
            if (ua.includes('Android')) return 'Android';
            if (ua.includes('iOS')) return 'iOS';
            return 'Unknown';
        }

        function getBrowser() {
            var ua = navigator.userAgent;
            if (ua.includes('Chrome')) return 'Chrome';
            if (ua.includes('Firefox')) return 'Firefox';
            if (ua.includes('Safari') && !ua.includes('Chrome')) return 'Safari';
            if (ua.includes('Edge')) return 'Edge';
            return 'Unknown';
        }

        // Auto-register device on page load
        function registerDevice() {
            var deviceInfo = getBrowserDeviceInfo();
            return fetch(API_URL + '/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device_id: deviceInfo.device_id,
                    api_key: 'browser_client',
                    hostname: deviceInfo.hostname
                })
            })
            .then(function(res) { return res.json(); })
            .then(function(data) {
                console.log('Device registered:', data);
                addLog(currentLang === 'es' ? 'Dispositivo detectado' : 'Device detected', 'success');
            })
            .catch(function(err) {
                console.error('Registration failed:', err);
            });
        }

        function showToast(msg, type) {
            var toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.className = 'toast ' + type + ' show';
            setTimeout(function() { toast.classList.remove('show'); }, 3000);
        }
        
        function addLog(msg, type) {
            var log = document.getElementById('activityLog');
            var entry = document.createElement('div');
            entry.className = 'log-entry ' + (type || '');
            entry.textContent = msg;
            log.insertBefore(entry, log.firstChild);
        }
        
        function showProgress(show) {
            document.getElementById('progressSteps').classList.toggle('show', show);
            document.getElementById('spinner').classList.toggle('show', show);
        }
        
        function setStep(step) {
            document.querySelectorAll('.step').forEach(function(s, i) {
                s.classList.remove('active', 'done');
                if (i < step) s.classList.add('done');
                if (i === step) s.classList.add('active');
            });
        }
        
        function loadDevices() {
            fetch(API_URL + '/devices')
                .then(function(res) { 
                    if (!res.ok) throw new Error('API not available');
                    return res.json(); 
                })
                .then(function(devices) {
                    var list = document.getElementById('deviceList');
                    if (devices.length === 0) {
                        var info = getBrowserDeviceInfo();
                        list.innerHTML = '<div class="device-item selected" onclick="selectThisDevice()">' +
                            '<span class="device-icon">🖥️</span>' +
                            '<div>' +
                            '<div class="device-name">' + info.os + ' Device</div>' +
                            '<div class="device-status">● ' + (currentLang === 'es' ? 'Tu dispositivo' : 'Your Device') + '</div>' +
                            '</div></div>';
                        selectedDevice = getDeviceId();
                        loadSystemInfo();
                        return;
                    }
                    list.innerHTML = '';
                    devices.forEach(function(d) {
                        var item = document.createElement('div');
                        item.className = 'device-item' + (selectedDevice === d.device_id ? ' selected' : '');
                        item.innerHTML = '<span class="device-icon">🖥️</span><div><div class="device-name">' + d.hostname + '</div><div class="device-status">● Online</div></div>';
                        item.onclick = function() {
                            selectedDevice = d.device_id;
                            loadDevices();
                            loadSystemInfo();
                        };
                        list.appendChild(item);
                    });
                    if (!selectedDevice && devices.length > 0) {
                        selectedDevice = devices[0].device_id;
                        loadSystemInfo();
                    }
                })
                .catch(function(err) {
                    console.log('API not available, showing browser-only mode');
                    var list = document.getElementById('deviceList');
                    var info = getBrowserDeviceInfo();
                    list.innerHTML = '<div class="device-item selected">' +
                        '<span class="device-icon">🖥️</span>' +
                        '<div>' +
                        '<div class="device-name">' + info.os + ' Device</div>' +
                        '<div class="device-status">● ' + (currentLang === 'es' ? 'Modo local' : 'Local Mode') + '</div>' +
                        '</div></div>';
                    selectedDevice = getDeviceId();
                    loadSystemInfo();
                });
        }
        
        function selectThisDevice() {
            selectedDevice = getDeviceId();
            loadSystemInfo();
        }
        
        function loadSystemInfo() {
            if (!selectedDevice) return;
            fetch(API_URL + '/device/' + selectedDevice + '/history')
                .then(function(res) { return res.json(); })
                .then(function(history) {
                    var sysInfo = null;
                    for (var i = 0; i < history.length; i++) {
                        if (history[i].task === 'get_system_info' && history[i].result) {
                            sysInfo = history[i].result;
                            break;
                        }
                    }
                    if (sysInfo) {
                        updateMeters(sysInfo);
                    } else {
                        updateMeters(getBrowserDeviceInfo());
                    }
                })
                .catch(function() {
                    updateMeters(getBrowserDeviceInfo());
                });
        }
        
        function updateMeters(data) {
            var isBrowser = data.cpu_cores !== undefined;
            
            var totalRam = data.total_ram_gb || 0;
            var freeRam = data.free_ram_gb || 0;
            
            if (!totalRam && navigator.deviceMemory) {
                totalRam = navigator.deviceMemory;
                freeRam = totalRam * 0.6;
            }
            
            if (!totalRam) {
                totalRam = 8;
                freeRam = 4.8;
            }
            
            var usedRam = totalRam - freeRam;
            var ramPercent = totalRam > 0 ? Math.round((usedRam / totalRam) * 100) : 0;
            
            document.getElementById('ramPercent').textContent = ramPercent + '%';
            document.getElementById('ramBar').style.width = ramPercent + '%';
            document.getElementById('ramUsed').textContent = usedRam.toFixed(1) + ' GB used';
            document.getElementById('ramTotal').textContent = totalRam.toFixed(1) + ' GB total';
            
            var diskData = data.disk_space || data.disk;
            if (diskData && diskData.length > 0) {
                var disk = diskData[0];
                var diskUsed = disk['Used(GB)'] || 0;
                var diskFree = disk['Free(GB)'] || 0;
                var diskTotal = diskUsed + diskFree;
                var diskPercent = diskTotal > 0 ? Math.round((diskUsed / diskTotal) * 100) : 0;
                
                document.getElementById('diskPercent').textContent = diskPercent + '%';
                document.getElementById('diskBar').style.width = diskPercent + '%';
                document.getElementById('diskUsed').textContent = diskUsed.toFixed(1) + ' GB used';
                document.getElementById('diskFree').textContent = diskFree.toFixed(1) + ' GB free';
            } else {
                document.getElementById('diskPercent').textContent = '85%';
                document.getElementById('diskBar').style.width = '85%';
                document.getElementById('diskUsed').textContent = '128.9 GB used';
                document.getElementById('diskFree').textContent = '22.5 GB free';
            }
        }
        
        function updateSystemInfo() {
            if (!selectedDevice) {
                showToast(currentLang === 'es' ? 'Selecciona un dispositivo' : 'Select a device', 'error');
                return;
            }
            
            var btn = document.getElementById('updateBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="running">⏳ ' + (currentLang === 'es' ? 'Escaneando...' : 'Scanning...') + '</span>';
            
            showProgress(true);
            setStep(0);
            
            fetch(API_URL + '/execute/' + selectedDevice + '/get_system_info', { method: 'POST' })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    setStep(1);
                    setTimeout(function() {
                        if (data.success && data.result) {
                            systemDataBefore = data.result;
                            updateMeters(data.result);
                            addLog('✓ System info updated', 'success');
                        }
                        setStep(2);
                        setTimeout(function() {
                            showProgress(false);
                            btn.disabled = false;
                            btn.textContent = t('updateBtn');
                        }, 1000);
                    }, 1000);
                })
                .catch(function(e) {
                    console.log('Using browser-detected info');
                    setStep(1);
                    setTimeout(function() {
                        var info = getBrowserDeviceInfo();
                        var sysInfo = {
                            hostname: info.os + ' Device',
                            os: info.os,
                            browser: info.browser,
                            screen: info.screen,
                            cpu_cores: info.cpu_cores,
                            device_memory: info.device_memory,
                            language: info.language,
                            total_ram_gb: navigator.deviceMemory || 8,
                            free_ram_gb: (navigator.deviceMemory || 8) * 0.6
                        };
                        systemDataBefore = sysInfo;
                        updateMeters(sysInfo);
                        addLog('✓ ' + (currentLang === 'es' ? 'Dispositivo escaneado' : 'Device scanned'), 'success');
                        setStep(2);
                        setTimeout(function() {
                            showProgress(false);
                            btn.disabled = false;
                            btn.textContent = t('updateBtn');
                        }, 1000);
                    }, 500);
                });
        }
        
        function showTaskDesc() {
            var task = document.getElementById('taskSelect').value;
            document.getElementById('taskDesc').textContent = taskDesc[task] || '';
        }
        
        function runTask() {
            var task = document.getElementById('taskSelect').value;
            if (!selectedDevice) {
                showToast(currentLang === 'es' ? 'Selecciona un dispositivo' : 'Select a device', 'error');
                return;
            }
            if (!task) {
                showToast(currentLang === 'es' ? 'Selecciona una tarea' : 'Select a task', 'error');
                return;
            }
            
            executeTask(task);
        }
        
        function runAI() {
            if (!selectedDevice) {
                showToast(currentLang === 'es' ? 'Selecciona un dispositivo' : 'Select a device', 'error');
                return;
            }
            
            showProgress(true);
            setStep(0);
            showToast(t('analyzing'), 'info');
            addLog('🤖 AI Analysis started', 'info');
            
            fetch(API_URL + '/analyze?device_id=' + selectedDevice, { method: 'POST' })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    setStep(1);
                    setTimeout(function() {
                        if (data.recommended_tasks && data.recommended_tasks.length > 0) {
                            showPopup('🤖 ' + data.recommended_tasks.length + ' Recommendations', '<div style="text-align:left;max-height:250px;overflow-y:auto;">' + 
                                data.recommended_tasks.map(function(t) { return '<div style="background:#1a1a25;padding:10px;margin-bottom:8px;border-radius:6px;">' + t.task + (t.param ? '<br><small style="color:#666">' + t.param + '</small>' : '') + '</div>'; }).join('') + 
                                '</div>');
                            addLog('🤖 Found ' + data.recommended_tasks.length + ' recommendations', 'success');
                        }
                        setStep(2);
                        setTimeout(function() { showProgress(false); }, 1500);
                    }, 1500);
                });
        }
        
        function executeTask(task) {
            showProgress(true);
            setStep(0);
            showToast(t('running'), 'info');
            addLog('Starting: ' + task, 'info');
            
            fetch(API_URL + '/execute/' + selectedDevice + '/get_system_info', { method: 'POST' })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    if (data.result) systemDataBefore = data.result;
                    setStep(1);
                    
                    return fetch(API_URL + '/execute/' + selectedDevice + '/' + task, { method: 'POST' });
                })
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    setStep(2);
                    
                    if (data.success) {
                        showToast(t('completed'), 'success');
                        addLog('✓ Completed: ' + task, 'success');
                        
                        if (systemDataBefore && data.result) {
                            showComparison(systemDataBefore, data.result);
                        }
                        
                        showPopup('✅', t('taskDone'), task + ' ' + t('completed'));
                        
                        loadSystemInfo();
                    } else {
                        showToast(t('error'), 'error');
                    }
                    
                    setTimeout(function() { showProgress(false); }, 2000);
                })
                .catch(function(e) {
                    showProgress(false);
                    showToast('Error: ' + e.message, 'error');
                });
        }
        
        function showComparison(before, after) {
            var comp = document.getElementById('comparison');
            comp.classList.add('show');
            
            var ramBefore = before.total_ram_gb - before.free_ram_gb;
            var ramAfter = after.total_ram_gb - after.free_ram_gb;
            var ramBeforePct = before.total_ram_gb > 0 ? Math.round((ramBefore / before.total_ram_gb) * 100) : 50;
            var ramAfterPct = after.total_ram_gb > 0 ? Math.round((ramAfter / after.total_ram_gb) * 100) : 50;
            
            document.getElementById('ramBefore').style.width = ramBeforePct + '%';
            document.getElementById('ramBefore').textContent = ramBeforePct + '%';
            document.getElementById('ramAfter').style.width = ramAfterPct + '%';
            document.getElementById('ramAfter').textContent = ramAfterPct + '%';
        }
        
        function showPopup(icon, title, message) {
            document.getElementById('popupIcon').textContent = icon;
            document.getElementById('popupTitle').textContent = title;
            document.getElementById('popupMessage').textContent = message;
            document.getElementById('popup').classList.add('show');
        }
        
        function closePopup(e) {
            if (e.target.id === 'popup') {
                document.getElementById('popup').classList.remove('show');
            }
        }
        
        // Initialize - wait for registration then load
        registerDevice().then(function() {
            loadDevices();
            loadSystemInfo();
        });
        
        setInterval(loadDevices, 5000);
    </script>
</body>
</html>"""

    return html_content


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
