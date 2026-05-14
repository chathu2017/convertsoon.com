"""
FileConverter - Main FastAPI Application
(Final Version: Secured Analysis, Processing, ZIP Fixes & Low RAM & Multi-File Merge & pSEO Ready & PDF Security & Dashboard & Active-Active Nodes)
"""

import os
import uuid
import logging
import json
import asyncio
import shutil
import time
import zipfile
import io
import glob
import aiofiles
import multiprocessing  # Process Isolation
import psutil         # Process Killing
import httpx          # [NEW] For Cross-Server Communication
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, List, Dict
from app.services.blog_service import blog_service
# Limit image pixel sizes to prevent DoS
from PIL import Image
Image.MAX_IMAGE_PIXELS = 178000000

# Imports for Rate Limiting
import redis.asyncio as redis
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request, Depends, Body, Response, Header
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# PDF Tools Imports
from pypdf import PdfReader, PdfWriter
from pdf2image import convert_from_path
import img2pdf
from PIL import Image

from app.services.queue_service import QueueService
from app.services.storage_service import StorageService
from app.config import settings

# [NEW] Dashboard Imports
from app.routers import dashboard
from app.services.dashboard_service import dashboard_service

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize services
queue_service = QueueService()
storage_service = StorageService()

# Ensure temp directories exist
PDF_TEMP_DIR = os.path.join(settings.TEMP_DIR, "pdf_workspace")
os.makedirs(PDF_TEMP_DIR, exist_ok=True)

# Supported formats for Validation & pSEO
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'tif', 'heic', 'heif', 'svg'}
DOCUMENT_EXTENSIONS = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'html', 'htm', 'odt', 'epub', 'pdf'}
ALL_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS

# Formats list for Sitemap Generation
SITEMAP_IMAGE_FORMATS = ['jpg', 'png', 'webp', 'heic', 'svg', 'bmp', 'tiff', 'pdf' , 'gif']
SITEMAP_DOC_FORMATS = ['doc', 'docx', 'pdf', 'txt', 'odt', 'xlsx']
# Note: 'word' is added to this list implicitly via alias logic later, but for validation we stick to real extensions
ALL_SITEMAP_FORMATS = list(set(SITEMAP_IMAGE_FORMATS + SITEMAP_DOC_FORMATS))

# --- CONCURRENCY CONTROL ---
# UPDATED: Increased to 5 for 6-Core Server Performance
pdf_semaphore = asyncio.Semaphore(2)
analysis_semaphore = asyncio.Semaphore(2)

def perform_sync_cleanup():
    """Synchronous function to delete old files."""
    try:
        logger.info("Starting background cleanup check (Threaded)...")
        dirs_to_clean = [
            os.path.join(settings.TEMP_DIR, "uploads"),
            os.path.join(settings.TEMP_DIR, "outputs"),
            os.path.join(settings.TEMP_DIR, "temp_uploads"),
            os.path.join(settings.TEMP_DIR, "pdf_workspace"),
            PDF_TEMP_DIR
        ]
        # CHANGE: Reduced threshold to 900 seconds (15 minutes) for faster cleanup
        threshold = time.time() - 900
        cleaned_count = 0

        for directory in dirs_to_clean:
            if not os.path.exists(directory):
                continue
            for item_name in os.listdir(directory):
                item_path = os.path.join(directory, item_name)
                try:
                    mtime = os.path.getmtime(item_path)
                    if mtime < threshold:
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                        cleaned_count += 1
                except Exception:
                    pass

        if cleaned_count > 0:
            logger.info(f"Cleanup finished. Removed {cleaned_count} items.")

    except Exception as e:
        logger.error(f"Cleanup thread error: {e}")


async def run_periodic_cleanup():
    while True:
        await asyncio.sleep(10)
        await asyncio.to_thread(perform_sync_cleanup)
        # CHANGE: Run cleanup check every 30 minutes
        await asyncio.sleep(1800)

async def run_health_logger():
    while True:
        await asyncio.sleep(600)  # Every 10 Minutes
        await asyncio.to_thread(dashboard_service.log_server_health)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FileConverter...")
    try:
        await queue_service.connect()
        await storage_service.initialize()
        try:
            redis_connection = redis.from_url(settings.redis_connection_url, encoding="utf-8", decode_responses=True)
            await FastAPILimiter.init(redis_connection)
            logger.info("Rate Limiter Initialized")
        except Exception as e:
            logger.warning(f"Rate Limiter Init Failed (Check Redis): {e}")

        cleanup_task = asyncio.create_task(run_periodic_cleanup())
        
        # --- [NEW] Start Health Logger Task ---
        health_task = asyncio.create_task(run_health_logger())

        logger.info("FileConverter ready!")
        yield
    finally:
        logger.info("Shutting down...")
        
        if 'cleanup_task' in locals():
            cleanup_task.cancel()
            
        # --- [NEW] Stop Health Logger Task ---
        if 'health_task' in locals():
            health_task.cancel()

        try:
            await storage_service.close()
            await queue_service.disconnect()
        except Exception:
            pass
        logger.info("Shutdown complete")


app = FastAPI(
    title="FileConverter",
    description="File conversion service",
    version="3.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# [NEW] Include Dashboard Router
app.include_router(dashboard.router)


# --- Pydantic Models ---
class ZipRequest(BaseModel):
    job_ids: List[str]

class PdfProcessRequest(BaseModel):
    job_id: str
    action: str
    params: Dict


def get_file_extension(filename: str) -> str:
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
    else: return f"{size_bytes / (1024 * 1024):.2f} MB"

def get_readable_format(fmt):
    """Helper for SEO Titles"""
    names = {
        'jpg': 'JPG Image', 'jpeg': 'JPEG Image', 'png': 'PNG Image',
        'pdf': 'PDF Document', 'docx': 'Word Document', 'heic': 'HEIC Photo',
        'word': 'Word Document', # Alias handling for title
        # --- NEW FORMATS ADDED HERE ---
        'gif': 'GIF Image', 'bmp': 'BMP Image', 'tiff': 'TIFF Image',
        'svg': 'SVG Vector', 'webp': 'WebP Image'
    }
    return names.get(fmt, fmt.upper())

# --- PSEO FAQ DATA & HELPER FUNCTION ---
FAQ_DATA = {
    "image": [
        {
            "q": "How do I convert {s} to {t} for free?",
            "a": "Simply upload your <b>{s}</b> files to the box above. Our tool will automatically convert them to high-quality <b>{t}</b> format instantly. No email or signup needed."
        },
        {
            "q": "Does converting {s} to {t} reduce quality?",
            "a": "Our smart converter optimizes the file to ensure the highest possible quality when changing from {s} to {t}. You get clear, crisp images every time."
        }
    ],
    "document": [
        {
            "q": "Will my formatting stay the same from {s} to {t}?",
            "a": "Yes! We use advanced processing to keep your fonts, tables, and layouts intact when converting from <b>{s}</b> to <b>{t}</b>."
        },
        {
            "q": "Is it safe to upload confidential {s} documents?",
            "a": "Absolutely. Your {s} files are encrypted via SSL and automatically deleted from our servers after 30 minutes. Your privacy is guaranteed."
        }
    ],
    "pdf_merge": [
        {"q": "Can I change the order of PDF pages?", "a": "Yes. After uploading, simply drag and drop the pages to rearrange them exactly how you want before merging."},
        {"q": "How many PDF files can I merge at once?", "a": "You can upload and merge up to 10 PDF files simultaneously with our free tool."}
    ],
    "pdf_split": [
        {"q": "Can I extract just one page from a PDF?", "a": "Yes. Click on the specific page you want to extract, and you can download it individually or as part of a smaller PDF."},
        {"q": "Do I need Adobe Acrobat to split PDFs?", "a": "No. You can split, extract, and reorganize PDF pages directly in your browser using ConvertSoon for free."}
    ],
    "pdf_compress": [
        {"q": "How much will the file size decrease?", "a": "It depends on the content, but our 'Medium' compression usually reduces file size by 40-70% while maintaining good visual quality."},
        {"q": "Will my compressed PDF look blurry?", "a": "No. Our smart algorithm removes redundant data but keeps text and images sharp for professional use."}
    ],
    # --- NEW FAQs for Security ---
    "pdf_protect": [
        {"q": "How strong is the PDF encryption?", "a": "We use standard 128-bit AES encryption, which is compatible with all major PDF viewers and provides strong security for your documents."},
        {"q": "Can you recover my password if I forget it?", "a": "No. We do not store your passwords or files. If you forget the password you set, the file cannot be recovered by us."}
    ],
    "pdf_unlock": [
        {"q": "Can I unlock a PDF if I don't know the password?", "a": "No. You must provide the correct password to unlock the file. Our tool removes the password protection so you don't have to enter it every time you open the file."},
        {"q": "Is it safe to type my password here?", "a": "Yes. The process happens securely on our encrypted server, and the file along with the password is immediately deleted after processing."}
    ]
}

def get_pseo_faqs(category: str, source: str = "", target: str = ""):
    """Helper to format FAQs dynamically based on source/target"""
    raw_faqs = FAQ_DATA.get(category, [])
    formatted_faqs = []

    for item in raw_faqs:
        question = item["q"]
        answer = item["a"]

        if source and target:
            question = question.format(s=source, t=target)
            answer = answer.format(s=source, t=target)

        formatted_faqs.append({"q": question, "a": answer})

    return formatted_faqs

# --- HELPER: KILL PROCESS TREE ---
def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

# ==============================================================================
#  SEO & FRONTEND ROUTES (DYNAMIC ROUTING)
# ==============================================================================

@app.get("/")
async def home(request: Request):
    """Default Home Page"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "page_title": "Free Online Image Converter - Convert JPG, PNG, HEIC & PDF (No Signup)",
        "meta_description": "Convert unlimited images and PDFs for free with ConvertSoon. No signup required. Securely batch convert JPG, PNG, HEIC, and documents instantly.",
        "canonical_url": "https://convertsoon.com/",
        "h1_text": "Convert Any File",
        "h2_text": "Batch convert images, vectors, and documents instantly.",
        "pre_select_format": None,

        "howto_title": "How to Convert Files Online",
        "howto_step1": "Drag & drop <strong>unlimited</strong> files at once. We support JPG, PNG, HEIC, WebP, PDF, DOCX, and more.",
        "howto_step2": "Choose your output format. You can also <strong>resize</strong> images, adjust quality, or change background colors easily.",
        "howto_step3": "Click <strong>Convert All</strong>. Once done, download files individually or get everything in a single <strong>ZIP file</strong>."
    })

@app.get("/convert/{source}-to-{target}")
async def dynamic_converter(request: Request, source: str, target: str):
    source = source.lower()
    target = target.lower()

    aliases = {
        'word': 'docx',
        'doc': 'docx',
        'excel': 'xlsx'
    }

    real_source = aliases.get(source, source)
    real_target = aliases.get(target, target)

    if real_source not in ALL_SITEMAP_FORMATS or real_target not in ALL_SITEMAP_FORMATS or real_source == real_target:
        raise HTTPException(status_code=404, detail="Conversion pair not supported")

    readable_src = get_readable_format(source)
    readable_tgt = get_readable_format(target)

    title = f"Convert {readable_src} to {readable_tgt} Online - Free & Secure"
    desc = f"Best free online tool to convert {readable_src} to {readable_tgt}. fast, secure, and no installation required. Batch convert {source.upper()} files today."

    howto_title = f"How to Convert {readable_src} to {readable_tgt}"
    howto_step1 = f"Upload your <strong>{source.upper()}</strong> files. Drag & drop works best."
    howto_step2 = f"Our tool auto-selects <strong>{target.upper()}</strong> for you. Adjust quality if needed."
    howto_step3 = f"Click <strong>Convert</strong>. Download your converted <strong>{readable_tgt}</strong> files instantly."

    doc_formats = ['pdf', 'docx', 'doc', 'xlsx', 'txt', 'odt', 'ppt', 'pptx', 'epub']

    if real_target in doc_formats or real_source in doc_formats:
        faq_category = "document"
    else:
        faq_category = "image"

    dynamic_faqs = get_pseo_faqs(faq_category, source=readable_src, target=readable_tgt)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "page_title": title,
        "meta_description": desc,
        "canonical_url": f"https://convertsoon.com/convert/{source}-to-{target}",
        "h1_text": f"Convert {source.upper()} to {target.upper()}",
        "h2_text": f"Fast and free {readable_src} to {readable_tgt} converter.",
        "pre_select_format": real_target,
        "howto_title": howto_title,
        "howto_step1": howto_step1,
        "howto_step2": howto_step2,
        "howto_step3": howto_step3,
        "dynamic_faqs": dynamic_faqs
    })

@app.get("/pdf-tools")
async def pdf_tools(request: Request):
    """Default PDF Tools Page"""
    return templates.TemplateResponse("pdf-tools.html", {
        "request": request,
        "page_title": "Free PDF Tools - Merge, Split, Compress & Convert PDF Online",
        "meta_description": "Merge, split, and compress PDF files instantly for free with ConvertSoon. Securely manage your documents online.",
        "canonical_url": "https://convertsoon.com/pdf-tools",
        "active_tool": "split",
        "h1_text": "PDF Tools"
    })

@app.get("/pdf/{tool_slug}")
async def dynamic_pdf_tool(request: Request, tool_slug: str):
    """
    pSEO Route: Handles /pdf/merge-pdf, /pdf/compress-pdf etc.
    Updated with Dynamic FAQ Logic.
    """
    tool_map = {
        "merge-pdf": {"tool": "split", "title": "Merge PDF Files - Combine PDFs Online", "h1": "Merge PDF Files", "faq": "pdf_merge"},
        "split-pdf": {"tool": "split", "title": "Split PDF - Extract Pages Online", "h1": "Split PDF Files", "faq": "pdf_split"},
        "compress-pdf": {"tool": "compress", "title": "Compress PDF - Reduce File Size", "h1": "Compress PDF", "faq": "pdf_compress"},
        "rearrange-pdf": {"tool": "split", "title": "Rearrange PDF Pages Online", "h1": "Organize PDF Pages", "faq": "pdf_split"},
        "organize-pdf": {"tool": "split", "title": "Organize PDF Pages - Rearrange & Sort", "h1": "Organize PDF Pages", "faq": "pdf_split"},

        # --- NEW SECURITY ROUTES ---
        "protect-pdf": {"tool": "security", "title": "Protect PDF - Add Password Online", "h1": "Protect PDF", "faq": "pdf_protect"},
        "unlock-pdf": {"tool": "security", "title": "Unlock PDF - Remove Password Online", "h1": "Unlock PDF", "faq": "pdf_unlock"}
    }

    if tool_slug not in tool_map:
        raise HTTPException(status_code=404, detail="Tool not found")

    data = tool_map[tool_slug]
    faq_category = data.get("faq", "pdf_split")
    dynamic_faqs = get_pseo_faqs(faq_category)

    return templates.TemplateResponse("pdf-tools.html", {
        "request": request,
        "page_title": data["title"],
        "meta_description": f"Use our free {data['h1']} tool. Secure, fast, and easy to use. {data['title']}.",
        "canonical_url": f"https://convertsoon.com/pdf/{tool_slug}",
        "active_tool": data["tool"],
        "h1_text": data["h1"],
        "dynamic_faqs": dynamic_faqs
    })

# --- DYNAMIC SITEMAP GENERATOR ---
@app.get("/sitemap.xml")
async def sitemap():
    """Generates sitemap dynamically based on supported formats"""
    base_url = "https://convertsoon.com"
    urls = [
        f"{base_url}/",
        f"{base_url}/pdf-tools",
        f"{base_url}/about",
        f"{base_url}/contact",
        f"{base_url}/privacy",
        f"{base_url}/terms",
    ]

    # Add PDF Tools (Including new ones)
    pdf_slugs = ["merge-pdf", "split-pdf", "compress-pdf", "organize-pdf", "protect-pdf", "unlock-pdf"]
    for slug in pdf_slugs:
        urls.append(f"{base_url}/pdf/{slug}")

    # Add Conversion Combinations
    popular_images = ['jpg', 'png', 'webp', 'heic', 'pdf', 'gif', 'bmp', 'tiff', 'svg']

    for src in popular_images:
        for tgt in popular_images:
            if src != tgt:
                urls.append(f"{base_url}/convert/{src}-to-{tgt}")

    urls.append(f"{base_url}/convert/pdf-to-word")
    urls.append(f"{base_url}/convert/word-to-pdf")

    # --- NEW: Add Blog Posts to Sitemap ---
    posts = blog_service.get_all_posts()
    for post in posts:
        urls.append(f"{base_url}/blog/{post['slug']}")

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url in urls:
        xml_content += f'  <url><loc>{url}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>\n'

    xml_content += '</urlset>'

    return Response(content=xml_content, media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    content = "User-agent: *\nAllow: /\nSitemap: https://convertsoon.com/sitemap.xml"
    return Response(content=content, media_type="text/plain")

# ==============================================================================
#  API ROUTES
# ==============================================================================

# --- [NEW] ACTIVE-ACTIVE DASHBOARD ENDPOINTS ---

@app.post("/api/node-stats")
async def get_node_stats_internal(x_node_secret: Optional[str] = Header(None)):
    """
    Internal endpoint: Returns this server's stats to a remote node.
    Secured by Secret Key.
    """
    # Read from ENV directly to ensure it works even if config.py isn't reloaded yet
    secret = os.getenv("NODE_SECRET_KEY", "default-secret")
    
    if x_node_secret != secret:
        raise HTTPException(status_code=403, detail="Invalid Node Secret")

    # Get Local Data
    stats = dashboard_service.get_dashboard_stats()
    health = dashboard_service.get_system_health()
    
    return {
        "node_name": os.getenv("NODE_NAME", "Unknown Node"),
        "stats": stats,
        "health": health
    }

@app.get("/api/remote-stats")
async def get_remote_stats_proxy():
    """
    Proxy endpoint: Fetches stats from the REMOTE server via Backend.
    Prevents CORS issues on frontend.
    """
    remote_url = os.getenv("REMOTE_NODE_URL")
    secret = os.getenv("NODE_SECRET_KEY", "default-secret")

    if not remote_url:
        return JSONResponse({"error": "Remote Node Not Configured"}, status_code=503)

    async with httpx.AsyncClient() as client:
        try:
            # Call the OTHER server's /api/node-stats
            resp = await client.post(
                f"{remote_url}/api/node-stats",
                headers={"X-Node-Secret": secret},
                timeout=5.0
            )
            if resp.status_code != 200:
                return JSONResponse({"error": "Remote Node Error"}, status_code=resp.status_code)
            
            return resp.json()
        except Exception as e:
            logger.error(f"Remote Sync Error: {e}")
            return JSONResponse({"error": "Connection Failed"}, status_code=502)

# -----------------------------------------------

# --- MAIN UPLOAD ENDPOINT ---
@app.post("/api/upload", dependencies=[Depends(RateLimiter(times=60, seconds=60))])
async def upload_file(
    files: List[UploadFile] = File(..., alias="file"),
    output_format: str = Form(...),
    dpi: Optional[int] = Form(None),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    quality: Optional[int] = Form(None),
    compression: Optional[str] = Form(None),
    compression_level: Optional[str] = Form(None),
    max_dimension: Optional[int] = Form(None),
    background_color: Optional[str] = Form(None),
    vector_mode: Optional[str] = Form(None),
    clustering: Optional[str] = Form(None),
    color_precision: Optional[int] = Form(None),
    gradient_step: Optional[int] = Form(None),
    filter_speckle: Optional[int] = Form(None),
    curve_fitting: Optional[str] = Form(None),
    corner_threshold: Optional[int] = Form(None),
    segment_length: Optional[int] = Form(None),
    splice_threshold: Optional[int] = Form(None)
):
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files allowed per batch.")

    uploaded_jobs = []

    try:
        for file in files:
            temp_file_path = None
            if not file.filename: continue

            file_ext = get_file_extension(file.filename)
            if file_ext not in ALL_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"Security Alert: File type '{file_ext}' is not allowed!")

            job_id = str(uuid.uuid4())
            temp_dir = os.path.join(settings.TEMP_DIR, "temp_uploads")
            os.makedirs(temp_dir, exist_ok=True)
            temp_file_path = os.path.join(temp_dir, f"{job_id}_{file.filename}")

            file_size = 0
            MAX_SIZE = 50 * 1024 * 1024

            async with aiofiles.open(temp_file_path, 'wb') as out_file:
                while content := await file.read(1024 * 1024):
                    file_size += len(content)
                    if file_size > MAX_SIZE:
                        await out_file.close()
                        if os.path.exists(temp_file_path):
                            os.remove(temp_file_path)
                        raise HTTPException(status_code=413, detail=f"File {file.filename} is too large! Maximum limit is 50MB.")
                    await out_file.write(content)

            await file.seek(0)

            blob_name = f"{job_id}/{file.filename}"
            await storage_service.upload_from_path(temp_file_path, blob_name, container="uploads")

            options = {
                "dpi": dpi or settings.DEFAULT_DPI,
                "width": width, "height": height, "quality": quality or settings.DEFAULT_QUALITY,
                "compression": compression or "default", "compression_level": compression_level or "medium",
                "max_dimension": max_dimension, "background_color": background_color or "#FFFFFF",
                "vector_mode": vector_mode or "color", "clustering": clustering or "stacked",
                "color_precision": color_precision or 6, "gradient_step": gradient_step or 16,
                "filter_speckle": filter_speckle or 4, "curve_fitting": curve_fitting or "spline",
                "corner_threshold": corner_threshold or 60, "segment_length": segment_length or 4,
                "splice_threshold": splice_threshold or 45
            }

            job_data = {
                "job_id": job_id, "original_filename": file.filename, "input_blob_name": blob_name,
                "input_extension": file_ext, "input_size": file_size, "output_format": output_format.lower(),
                "options": options, "created_at": datetime.now(timezone.utc).isoformat()
            }

            await queue_service.enqueue_job(job_data)

            uploaded_jobs.append({
                "job_id": job_id,
                "status": "queued",
                "original_filename": file.filename,
                "input_size_formatted": format_size(file_size)
            })

            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

        return JSONResponse({"success": True, "jobs": uploaded_jobs})

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Batch Upload Error: {e}")
        if 'temp_file_path' in locals() and temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = await queue_service.get_job_status(job_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job_id, "status": job.get("status", "unknown"),
        "original_filename": job.get("original_filename"), "output_format": job.get("output_format"),
        "input_size": int(job.get("input_size", 0)), "input_size_formatted": format_size(int(job.get("input_size", 0)))
    }

    if job.get("status") == "completed":
        output_size = int(job.get("output_size", 0))
        input_size = int(job.get("input_size", 0))
        response.update({
            "output_filename": job.get("output_filename"), "completed_at": job.get("completed_at"),
            "output_size": output_size, "output_size_formatted": format_size(output_size)
        })
        if input_size > 0:
            reduction = ((input_size - output_size) / input_size) * 100
            response["size_reduction_percent"] = round(reduction, 1)
    elif job.get("status") == "failed":
        response["error"] = job.get("error")
    elif job.get("status") == "processing":
        response["progress"] = job.get("progress", 0)
    elif job.get("status") == "queued":
        response["queue_position"] = job.get("queue_position", 0)

    return JSONResponse(response)


@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    job = await queue_service.get_job_status(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Job not ready")
    return JSONResponse({"success": True, "download_url": f"/api/download-file/{job_id}", "filename": job.get("output_filename")})


@app.get("/api/download-file/{job_id}")
async def download_file_direct(job_id: str):
    job = await queue_service.get_job_status(job_id)
    if not job: raise HTTPException(status_code=404)

    output_blob = job.get("output_blob_name")
    filename = job.get("output_filename", "download")

    try:
        try:
            file_path = await storage_service.get_file_path(output_blob, "outputs")
        except Exception:
            file_path = None

        if not file_path or not os.path.exists(file_path):
            local_path = os.path.join(PDF_TEMP_DIR, job_id, filename)
            if os.path.exists(local_path):
                file_path = local_path

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found on disk: {filename}")

        ctype = "application/pdf" if filename.endswith(".pdf") else "application/octet-stream"
        return FileResponse(file_path, media_type=ctype, filename=filename)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download-temp/{filename}")
async def download_temp_zip(filename: str):
    file_path = os.path.join(PDF_TEMP_DIR, filename)
    if not os.path.abspath(file_path).startswith(os.path.abspath(PDF_TEMP_DIR)):
         raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File expired or not found")
    return FileResponse(file_path, media_type="application/zip", filename=filename)

@app.post("/api/download-zip")
async def download_zip(request: ZipRequest):
    try:
        job_ids = request.job_ids
        if not job_ids: raise HTTPException(status_code=400, detail="No job IDs")

        batch_id = str(uuid.uuid4())
        zip_filename = f"converted_files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        safe_filename = f"{batch_id}_{zip_filename}"
        zip_path = os.path.join(PDF_TEMP_DIR, safe_filename)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, False) as zip_file:
            for job_id in job_ids:
                job = await queue_service.get_job_status(job_id)
                if not job or job.get("status") != "completed":
                    continue

                output_blob = job.get("output_blob_name")
                filename = job.get("output_filename", f"{job_id}.bin")

                try:
                    file_path = None
                    try:
                        file_path = await storage_service.get_file_path(output_blob, "outputs")
                    except Exception:
                        file_path = None

                    if not file_path or not os.path.exists(file_path):
                        local_path = os.path.join(PDF_TEMP_DIR, job_id, filename)
                        if os.path.exists(local_path):
                            file_path = local_path

                    if file_path and os.path.exists(file_path):
                        if filename in zip_file.namelist():
                            filename = f"{job_id}_{filename}"
                        zip_file.write(file_path, arcname=filename)
                    else:
                        logger.warning(f"File not found for ZIP: {job_id}")

                except Exception as e:
                    logger.error(f"Failed to add file for Job {job_id}: {str(e)}")

        return JSONResponse({
            "success": True,
            "download_url": f"/api/download-temp/{safe_filename}",
            "filename": zip_filename
        })

    except Exception as e:
        logger.error(f"Global ZIP Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cleanup/{job_id}")
async def cleanup_job(job_id: str):
    try:
        await storage_service.cleanup_job_files(job_id)
        await queue_service.delete_job(job_id)
        local_dir = os.path.join(PDF_TEMP_DIR, job_id)
        if os.path.exists(local_dir):
            shutil.rmtree(local_dir)
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/queue/stats")
async def queue_stats():
    try:
        return JSONResponse(await queue_service.get_queue_stats())
    except:
        return JSONResponse({"queue_length": 0})

@app.post("/api/resume-job/{job_id}")
async def resume_job(job_id: str):
    try:
        redis_client = redis.from_url(settings.redis_connection_url, encoding="utf-8", decode_responses=True)
        job_key = f"job:{job_id}"
        raw_data = await redis_client.hget(job_key, "data")
        if not raw_data:
            raise HTTPException(status_code=404, detail="Job data not found")

        job_data = json.loads(raw_data)
        if "options" not in job_data:
            job_data["options"] = {}

        job_data["options"]["approved"] = "true"

        await redis_client.hset(job_key, "data", json.dumps(job_data))
        await queue_service.update_job_status(job_id, "queued")
        await redis_client.rpush(queue_service.queue_key, job_id)

        return JSONResponse({"success": True})

    except Exception as e:
        logger.error(f"Resume Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# NEW: PDF TOOLS API ENDPOINTS (Multi-File Support)
# ==========================================

# --- 1. WORKER: EXECUTE ANALYSIS (Updated for Encryption Detection) ---
def execute_analysis_task(job_dir, output_queue):
    """
    Analyzes PDF.
    UPDATED: Checks for encryption BEFORE converting to images.
    """
    try:
        # Detect Files
        input_files = []
        original_pdf = os.path.join(job_dir, "original.pdf")

        if os.path.exists(original_pdf):
            input_files = [original_pdf]
        else:
            search_pattern = os.path.join(job_dir, "file_*.pdf")
            found_files = glob.glob(search_pattern)
            try:
                found_files.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0]))
            except:
                found_files.sort()
            input_files = found_files

        if not input_files:
            output_queue.put("ERROR:No valid PDF files found for analysis.")
            return

        # --- NEW: ENCRYPTION CHECK ---
        # Only meaningful for the first file or single file operations
        try:
            reader = PdfReader(input_files[0])
            if reader.is_encrypted:
                # If encrypted, we CANNOT generate thumbnails.
                # Return special flag so Frontend knows to ask for password.
                output_queue.put({"is_encrypted": True, "thumbnails": []})
                return
        except Exception as e:
            # If pypdf fails, it might be a corrupted file or complex encryption
            pass
        # -----------------------------

        thumbs_dir = os.path.join(job_dir, "thumbnails")
        os.makedirs(thumbs_dir, exist_ok=True)
        poppler_path = os.environ.get("POPPLER_PATH", "/usr/bin")

        thumb_data = []
        global_page_counter = 1

        for f_idx, file_path in enumerate(input_files):
            image_paths = convert_from_path(
                file_path,
                dpi=72,
                fmt='jpeg',
                output_folder=thumbs_dir,
                paths_only=True,
                poppler_path=poppler_path
            )

            image_paths.sort()

            for i, img_path in enumerate(image_paths):
                clean_name = f"page_{global_page_counter}.jpg"
                clean_path = os.path.join(job_dir, clean_name)
                shutil.move(img_path, clean_path)

                thumb_data.append({
                    "page": global_page_counter,
                    "url": f"/page_{global_page_counter}.jpg",
                    "file_index": f_idx
                })
                global_page_counter += 1

        if os.path.exists(thumbs_dir):
            shutil.rmtree(thumbs_dir)

        # Return standard response (not encrypted)
        output_queue.put({"is_encrypted": False, "thumbnails": thumb_data})

    except Exception as e:
        output_queue.put(f"ERROR:{str(e)}")
    finally:
        if os.path.exists(os.path.join(job_dir, "thumbnails")):
            try: shutil.rmtree(os.path.join(job_dir, "thumbnails"))
            except: pass


@app.post("/api/pdf/analyze")
async def analyze_pdf(files: List[UploadFile] = File(..., alias="file")):
    """
    Optimized PDF Analysis. Returns is_encrypted status.
    """
    async with analysis_semaphore:
        try:
            if not files:
                raise HTTPException(status_code=400, detail="No files provided")

            for f in files:
                if not f.filename.lower().endswith('.pdf'):
                    raise HTTPException(status_code=400, detail="Only PDF files allowed")

            job_id = str(uuid.uuid4())
            job_dir = os.path.join(PDF_TEMP_DIR, job_id)
            os.makedirs(job_dir, exist_ok=True)

            total_input_size = 0
            MAX_PDF_SIZE = 50 * 1024 * 1024

            if len(files) == 1:
                file_path = os.path.join(job_dir, "original.pdf")
                file = files[0]
                async with aiofiles.open(file_path, 'wb') as out_file:
                    while content := await file.read(1024 * 1024):
                        if (total_input_size + len(content)) > MAX_PDF_SIZE:
                             await out_file.close()
                             shutil.rmtree(job_dir)
                             raise HTTPException(status_code=413, detail="File too large! Maximum limit is 50MB.")
                        await out_file.write(content)
                        total_input_size += len(content)
            else:
                for idx, file in enumerate(files):
                    file_path = os.path.join(job_dir, f"file_{idx}.pdf")
                    async with aiofiles.open(file_path, 'wb') as out_file:
                        while content := await file.read(1024 * 1024):
                            if (total_input_size + len(content)) > MAX_PDF_SIZE:
                                 await out_file.close()
                                 shutil.rmtree(job_dir)
                                 raise HTTPException(status_code=413, detail="Total upload size exceeds 50MB limit.")
                            await out_file.write(content)
                            total_input_size += len(content)

            queue = multiprocessing.Queue()
            p = multiprocessing.Process(
                target=execute_analysis_task,
                args=(job_dir, queue)
            )
            p.start()

            TIMEOUT_SECONDS = 100

            try:
                for _ in range(TIMEOUT_SECONDS):
                    if not p.is_alive():
                        break
                    await asyncio.sleep(1)

                if p.is_alive():
                    logger.error(f"Analysis Job {job_id} TIMED OUT! Killing...")
                    kill_process_tree(p.pid)
                    p.join()
                    raise HTTPException(status_code=504, detail="Analysis timed out.")

                if queue.empty():
                    raise HTTPException(status_code=500, detail="Analysis failed unexpectedly.")

                result = queue.get()
                if isinstance(result, str) and result.startswith("ERROR:"):
                    raise HTTPException(status_code=500, detail=result.replace("ERROR:", ""))

                # --- NEW RESPONSE FORMAT ---
                # Check if it returned a dict (new format) or list (old format fallback)
                if isinstance(result, dict):
                    is_encrypted = result.get("is_encrypted", False)
                    thumbnails = result.get("thumbnails", [])
                else:
                    is_encrypted = False
                    thumbnails = result

                for thumb in thumbnails:
                    thumb["url"] = f"/api/pdf/thumbnail/{job_id}{thumb['url']}"

                size_fmt = format_size(total_input_size)

                return JSONResponse({
                    "success": True,
                    "job_id": job_id,
                    "page_count": len(thumbnails),
                    "file_size": size_fmt,
                    "thumbnails": thumbnails,
                    "is_encrypted": is_encrypted # Send this to frontend!
                })

            except HTTPException as he:
                if p.is_alive(): kill_process_tree(p.pid); p.join()
                raise he
            except Exception as e:
                if p.is_alive(): kill_process_tree(p.pid); p.join()
                raise HTTPException(status_code=500, detail=str(e))

        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"PDF Analysis Error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pdf/thumbnail/{job_id}/{filename}")
async def get_pdf_thumbnail(job_id: str, filename: str):
    file_path = os.path.join(PDF_TEMP_DIR, job_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404)
    return FileResponse(file_path)

@app.get("/api/pdf/download-result/{job_id}/{filename}")
async def download_pdf_result(job_id: str, filename: str):
    file_path = os.path.join(PDF_TEMP_DIR, job_id, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404)
    media_type = 'application/zip' if filename.endswith(".zip") else 'application/pdf'
    return FileResponse(file_path, filename=filename, media_type=media_type)

# --- 2. WORKER: EXECUTE PROCESSING (Updated for Lock/Unlock) ---
def execute_pdf_processing_task(job_dir, action, params, output_queue):
    """
    Executes split/compress/lock/unlock logic.
    """
    try:
        # 1. Load Input Readers
        readers = []
        original_pdf = os.path.join(job_dir, "original.pdf")

        if os.path.exists(original_pdf):
            readers.append(PdfReader(original_pdf))
        else:
            search_pattern = os.path.join(job_dir, "file_*.pdf")
            found_files = glob.glob(search_pattern)
            try:
                found_files.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0]))
            except:
                found_files.sort()

            for fp in found_files:
                readers.append(PdfReader(fp))

        if not readers:
            raise ValueError("No input PDF files found.")

        # --- SPLIT / MERGE LOGIC ---
        if action == 'split':
            pages_to_keep = params.get('pages', [])
            split_mode = params.get('split_mode', 'merge')
            rotations = params.get('rotations', {})

            if not pages_to_keep:
                raise ValueError("No pages selected")

            page_map = []
            for r_idx, reader in enumerate(readers):
                for p_idx, page in enumerate(reader.pages):
                    page_map.append((r_idx, p_idx))

            if split_mode == 'merge':
                writer = PdfWriter()
                for global_p_num in pages_to_keep:
                    g_idx = int(global_p_num) - 1
                    if 0 <= g_idx < len(page_map):
                        r_idx, local_p_idx = page_map[g_idx]
                        page = readers[r_idx].pages[local_p_idx]
                        angle = rotations.get(str(global_p_num), 0)
                        if angle != 0:
                            page.rotate(angle)
                        writer.add_page(page)

                out_name = f"merged_document_{int(time.time())}.pdf"
                out_path = os.path.join(job_dir, out_name)
                with open(out_path, "wb") as f:
                    writer.write(f)
                output_queue.put(out_name)

            elif split_mode == 'zip':
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    for global_p_num in pages_to_keep:
                        g_idx = int(global_p_num) - 1
                        if 0 <= g_idx < len(page_map):
                            r_idx, local_p_idx = page_map[g_idx]
                            single_writer = PdfWriter()
                            page = readers[r_idx].pages[local_p_idx]
                            angle = rotations.get(str(global_p_num), 0)
                            if angle != 0:
                                page.rotate(angle)
                            single_writer.add_page(page)
                            page_buffer = io.BytesIO()
                            single_writer.write(page_buffer)
                            page_buffer.seek(0)
                            zip_file.writestr(f"page_{global_p_num}.pdf", page_buffer.getvalue())

                zip_buffer.seek(0)
                out_name = f"split_pages_{int(time.time())}.zip"
                out_path = os.path.join(job_dir, out_name)
                with open(out_path, "wb") as f:
                    f.write(zip_buffer.getvalue())
                output_queue.put(out_name)

        # --- COMPRESS LOGIC ---
        elif action == 'compress':
            reader = readers[0]
            level = params.get('compression_level', 'medium')
            req_quality = int(params.get('quality', 75))
            req_dpi = int(params.get('dpi', 150))
            grayscale = params.get('grayscale', False)

            out_name = f"compressed_{int(time.time())}.pdf"
            out_path = os.path.join(job_dir, out_name)
            images_temp_dir = os.path.join(job_dir, "temp_images")
            os.makedirs(images_temp_dir, exist_ok=True)

            try:
                if level == 'low' and not params.get('custom_mode'):
                    writer = PdfWriter()
                    for page in reader.pages:
                        writer.add_page(page)
                    for page in writer.pages:
                        page.compress_content_streams()
                    with open(out_path, "wb") as f:
                        writer.write(f)
                else:
                    poppler_path = os.environ.get("POPPLER_PATH", "/usr/bin")
                    if not params.get('custom_mode'):
                        if level == 'medium': req_dpi = 150; req_quality = 75
                        elif level == 'high': req_dpi = 96; req_quality = 50

                    target_file_path = original_pdf if os.path.exists(original_pdf) else os.path.join(job_dir, "file_0.pdf")
                    image_paths = convert_from_path(
                        target_file_path, dpi=req_dpi, fmt='jpeg',
                        output_folder=images_temp_dir, paths_only=True, poppler_path=poppler_path
                    )
                    image_paths.sort()
                    final_image_paths = []
                    for img_path in image_paths:
                        with Image.open(img_path) as img:
                            if grayscale: img = img.convert('L')
                            processed_path = img_path + "_processed.jpg"
                            img.save(processed_path, format='JPEG', quality=req_quality, optimize=True)
                            final_image_paths.append(processed_path)
                        if os.path.exists(img_path): os.remove(img_path)
                    with open(out_path, "wb") as f:
                        f.write(img2pdf.convert(final_image_paths))
            finally:
                if os.path.exists(images_temp_dir):
                    shutil.rmtree(images_temp_dir)
            output_queue.put(out_name)

        # --- PROTECT (LOCK) LOGIC ---
        elif action == 'protect':
            password = params.get('password')
            if not password: raise ValueError("Password is required")

            # Use original file path
            target_file_path = original_pdf if os.path.exists(original_pdf) else os.path.join(job_dir, "file_0.pdf")

            reader = PdfReader(target_file_path)
            writer = PdfWriter()

            # Copy all pages
            writer.append_pages_from_reader(reader)

            # Encrypt
            writer.encrypt(password)

            out_name = f"protected_{int(time.time())}.pdf"
            out_path = os.path.join(job_dir, out_name)

            with open(out_path, "wb") as f:
                writer.write(f)

            output_queue.put(out_name)

        # --- UNLOCK LOGIC ---
        elif action == 'unlock':
            password = params.get('password')
            if not password: raise ValueError("Password is required")

            target_file_path = original_pdf if os.path.exists(original_pdf) else os.path.join(job_dir, "file_0.pdf")

            reader = PdfReader(target_file_path)

            # Try to decrypt
            if reader.is_encrypted:
                try:
                    success = reader.decrypt(password)
                    if not success: # Some versions return 0/False on failure
                         raise ValueError("Incorrect Password")
                except Exception:
                    raise ValueError("Incorrect Password or Decryption Failed")

            writer = PdfWriter()

            # Copy pages (this removes encryption if we don't call encrypt())
            writer.append_pages_from_reader(reader)

            out_name = f"unlocked_{int(time.time())}.pdf"
            out_path = os.path.join(job_dir, out_name)

            with open(out_path, "wb") as f:
                writer.write(f)

            output_queue.put(out_name)

    except Exception as e:
        output_queue.put(f"ERROR:{str(e)}")

@app.post("/api/pdf/process")
async def process_pdf(payload: PdfProcessRequest):
    """
    Handles PDF Processing with Semaphore & Timeout.
    Returns JSON errors instead of HTTP Exceptions to prevent frontend parsing issues.
    """
    async with pdf_semaphore:
        job_id = payload.job_id
        action = payload.action
        params = payload.params
        job_dir = os.path.join(PDF_TEMP_DIR, job_id)

        if not os.path.exists(job_dir):
             return JSONResponse({"success": False, "detail": "Session expired or file not found."})

        queue = multiprocessing.Queue()
        p = multiprocessing.Process(
            target=execute_pdf_processing_task,
            args=(job_dir, action, params, queue)
        )
        p.start()

        TIMEOUT_SECONDS = 120

        try:
            for _ in range(TIMEOUT_SECONDS):
                if not p.is_alive():
                    break
                await asyncio.sleep(1)

            if p.is_alive():
                logger.error(f"Job {job_id} TIMED OUT! Force killing...")
                kill_process_tree(p.pid)
                p.join()
                return JSONResponse({"success": False, "detail": "Processing timed out (2 min limit)."})

            if queue.empty():
                return JSONResponse({"success": False, "detail": "Processing failed unexpectedly."})

            result = queue.get()

            if isinstance(result, str) and result.startswith("ERROR:"):
                error_msg = result.replace("ERROR:", "")
                return JSONResponse({"success": False, "detail": error_msg})

            final_file = result
            full_path = os.path.join(PDF_TEMP_DIR, job_id, final_file)

            if not os.path.exists(full_path):
                 return JSONResponse({"success": False, "detail": "Output file generation failed."})

            file_size = os.path.getsize(full_path)

            await queue_service.update_job_status(
                job_id, "completed", output_blob_name="local",
                output_filename=final_file, output_size=str(file_size),
                completed_at=datetime.now(timezone.utc).isoformat()
            )

            # --- [NEW] DASHBOARD LOGGING (PDF TOOLS) ---
            try:
                dashboard_service.log_job_completion(
                    job_id=job_id,
                    job_type=f"pdf-{action}",
                    status="completed",
                    input_size=file_size # Approximate size
                )
            except Exception as log_err:
                logger.error(f"Failed to log PDF stats: {log_err}")
            # ------------------------------------------

            return JSONResponse({
                "success": True,
                "download_url": f"/api/pdf/download-result/{job_id}/{final_file}",
                "file_size": file_size
            })

        except Exception as e:
            logger.error(f"PDF Process Error: {e}")
            if p.is_alive(): kill_process_tree(p.pid); p.join()
            return JSONResponse({"success": False, "detail": str(e)})

# ==============================================================================
#  BLOG ROUTES (NEW)
# ==============================================================================

@app.get("/blog")
async def blog_index(request: Request):
    """බ්ලොග් ලිපි ඔක්කොම පෙන්නන පිටුව"""
    posts = blog_service.get_all_posts()
    return templates.TemplateResponse("blog_list.html", {
        "request": request,
        "page_title": "ConvertSoon Blog - Tech Tips & Tutorials",
        "meta_description": "Read our latest articles about file conversion, PDF tools, and tech tips.",
        "canonical_url": "https://convertsoon.com/blog",
        "posts": posts
    })

@app.get("/blog/{slug}")
async def blog_post(request: Request, slug: str):
    """තනි ලිපියක් පෙන්නන පිටුව"""
    post = blog_service.get_post(slug)
    if not post:
        # ලිපිය නැත්නම් 404 පිටුවට යවනවා
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
        
    return templates.TemplateResponse("blog_post.html", {
        "request": request,
        "page_title": post['title'],
        "meta_description": post['description'],
        "canonical_url": f"https://convertsoon.com/blog/{slug}",
        "post": post
    })

@app.get("/api/refresh-blog")
async def refresh_blog():
    """අලුත් ලිපියක් දැම්මම Cache එක Update කරන රහස් පාර"""
    blog_service.refresh()
    return {"status": "success", "message": "Blog cache updated!"}

# Static Page Handlers
@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"): return JSONResponse({"error": "Not found"}, 404)
    return templates.TemplateResponse("404.html", {"request": request}, 404)

@app.get("/privacy")
async def privacy(request: Request): return templates.TemplateResponse("privacy.html", {"request": request})
@app.get("/terms")
async def terms(request: Request): return templates.TemplateResponse("terms.html", {"request": request})
@app.get("/about")
async def about(request: Request): return templates.TemplateResponse("about.html", {"request": request})
@app.get("/contact")
async def contact(request: Request): return templates.TemplateResponse("contact.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)