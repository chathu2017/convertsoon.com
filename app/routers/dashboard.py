"""
Dashboard Router - Secure Admin Panel Endpoints
Protected by Hidden URL + HTTP Basic Auth
"""

import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.services.dashboard_service import dashboard_service

# 1. Setup Templates
templates = Jinja2Templates(directory="templates")

# 2. Setup Security
security = HTTPBasic()

# 3. Setup Router with Secret Prefix
# URL eka hadenne: /<ADMIN_SECRET_URL>/... widiyata
router = APIRouter(
    prefix=f"/{settings.ADMIN_SECRET_URL}",
    tags=["Admin Dashboard"]
)

# --- SECURITY DEPENDENCY ---
def get_current_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Validates Username & Password securely.
    Uses secrets.compare_digest to prevent timing attacks.
    """
    correct_username = secrets.compare_digest(credentials.username, settings.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# =========================================================
# 1. FRONTEND PAGE (HTML)
# =========================================================
@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, username: str = Depends(get_current_admin)):
    """
    Renders the secure dashboard HTML page.
    Dependency ensures login prompt appears first.
    """
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": username,
        "admin_url": settings.ADMIN_SECRET_URL
    })

# =========================================================
# 2. API ENDPOINTS (DATA FOR CHARTS)
# =========================================================
@router.get("/api/health/history")
async def get_health_history(username: str = Depends(get_current_admin)):
    return JSONResponse(dashboard_service.get_health_history())

@router.get("/api/stats")
async def get_stats(username: str = Depends(get_current_admin)):
    """Returns Job Counts, Success Rates & Weekly Trends"""
    data = dashboard_service.get_dashboard_stats()
    return JSONResponse(data)

@router.get("/api/health")
async def get_health(username: str = Depends(get_current_admin)):
    """Returns Live Server CPU / RAM / Disk Usage"""
    data = dashboard_service.get_system_health()
    return JSONResponse(data)

@router.get("/api/logs")
async def get_logs(source: str = "web", username: str = Depends(get_current_admin)):
    """
    Returns last 300 lines of server logs.
    Accepts 'source' query param (e.g., ?source=worker-1) to fetch specific logs.
    """
    logs = dashboard_service.get_server_logs(source=source, limit=300)
    return JSONResponse({"logs": logs})