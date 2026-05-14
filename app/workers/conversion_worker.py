import os
# ==============================================================================
# PRODUCTION SAFETY: THREAD & RESOURCE LIMITS (CRITICAL FOR STABILITY)
# ==============================================================================
# AI Libraries like Torch/NumPy try to use all cores. We limit this to prevent
# the worker from starving the OS or Nginx.
os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
# ==============================================================================

import psutil
import sys
import asyncio
import logging
import signal
import subprocess
import time
import multiprocessing
import zipfile
import io
import shutil
import pytesseract
import json
import base64
import re
from datetime import datetime, timezone

# --- IMPORTS FOR AI & IMAGE PROCESSING ---
# Only imported here, but Model Loading happens inside functions to save RAM
try:
    import cv2
    import numpy as np
    import layoutparser as lp
    from openai import AzureOpenAI
    from dotenv import load_dotenv
    from PIL import Image
    # Prevent Decompression Bomb Attacks
    Image.MAX_IMAGE_PIXELS = 178000000
except ImportError as e:
    print(f"AI Import Error: {e}")

# --- EXCEL TOOLS ---
import pandas as pd
import pdfplumber
import openpyxl

# Load Environment Variables
load_dotenv()

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.queue_service import QueueService
from app.services.storage_service import StorageService
from app.services.conversion_service import ConversionService
from app.config import settings

# [NEW] Import Dashboard Service for Stats Logging
from app.services.dashboard_service import dashboard_service

# Libraries
from pdf2image import convert_from_path, convert_from_bytes, pdfinfo_from_path
from docx import Document
# Professional Styling Imports
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import vtracer
from pypdf import PdfReader

# HEIF Support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==============================================================================
# GLOBAL AI MODEL STORAGE
# ==============================================================================
# AI මොඩල් එක මෙමරි එකේ තියාගන්න Global Variable එක
GLOBAL_LAYOUT_MODEL = None

def load_ai_model_once():
    """
    වර්කර් එක පටන් ගන්නකොටම AI මොඩල් එක මෙමරි එකට ලෝඩ් කරගන්නා ෆන්ක්ෂන් එක.
    මෙය ක්‍රියාත්මක වන්නේ එක් වරක් පමණි.
    """
    global GLOBAL_LAYOUT_MODEL

    # දැනටමත් ලෝඩ් වෙලා නම්, තිබෙන එකම ආපසු දෙනවා (Re-use)
    if GLOBAL_LAYOUT_MODEL is not None:
        return GLOBAL_LAYOUT_MODEL

    try:
        logger.info("🚀 Loading AI Model into Memory (One-time process)...")

        # මොඩල් ෆයිල් වල පාත් සොයා ගැනීම
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        local_config = os.path.join(base_dir, "app/models/config.yml")
        local_model = os.path.join(base_dir, "app/models/model_final.pth")

        # Detectron2 මොඩල් එක ලෝඩ් කිරීම
        GLOBAL_LAYOUT_MODEL = lp.Detectron2LayoutModel(
            config_path=local_config,
            model_path=local_model,
            extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.2],
            label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"}
        )
        logger.info("✅ AI Model Loaded Successfully!")
        return GLOBAL_LAYOUT_MODEL

    except Exception as e:
        logger.error(f"❌ Failed to load AI Model: {e}")
        return None

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def wait_for_resources(threshold_percent=90):
    """
    Waits if System RAM or CPU is too high.
    Prevents server from freezing when multiple workers run heavy jobs.
    """
    while True:
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.5)

        if mem.percent < threshold_percent:
            return # Safe to proceed

        # System is stressed, wait 3 seconds
        logger.warning(f"High Load (RAM: {mem.percent}%, CPU: {cpu}%). Worker pausing...")
        time.sleep(3)

def kill_process_tree(pid):
    """
    Ensures all child processes (like Tesseract or LibreOffice) are killed
    if the main worker process is terminated.
    """
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

def has_extractable_text(input_path):
    """
    Returns True if the PDF is 'Digital' (English/Simple).
    Returns False if it's Scanned OR contains Korean/Japanese (Forces Hybrid AI).
    """
    try:
        reader = PdfReader(input_path)
        for i, page in enumerate(reader.pages):
            if i > 2: break
            text = page.extract_text()

            # --- FORCE HYBRID AI FOR KOREAN/JAPANESE ---
            # කොරියන් අකුරු තිබුනොත් pdf2docx එකට නොදී, Hybrid AI එකට යවනවා.
            # එතකොට Layout එකයි අකුරුයි දෙකම ආරක්ෂිතයි.
            if text:
                for char in text:
                    if ('\uac00' <= char <= '\ud7a3') or ('\u3040' <= char <= '\u30ff') or \
                        ('\u0D80' <= char <= '\u0DFF') or ('\u0B80' <= char <= '\u0BFF'):  # <--- මේ කොටස එකතු කරන්න
                            return False
            # ------------------------------------------------

            if text and len(text.strip()) > 50:
                return True
        return False
    except:
        return False

# ==============================================================================
# SMART JOINT DETECTION (NEW LOGIC V2 - OPTIMIZED)
# ==============================================================================

def contains_table_grid(image_path):
    """
    SMART COST SAVING (V2):
    Checks for 'Intersections' (Joints) instead of just rectangles.
    """
    try:
        # 1. Image Read & Validation
        img = cv2.imread(image_path)
        if img is None: return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, \
                                       cv2.THRESH_BINARY, 15, -2)
        scale = 15

        # Horizontal Kernel
        horizontal = thresh.copy()
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(img.shape[1] / scale), 1))
        horizontal = cv2.erode(horizontal, horizontal_kernel)
        horizontal = cv2.dilate(horizontal, horizontal_kernel)

        # Vertical Kernel
        vertical = thresh.copy()
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(img.shape[0] / scale)))
        vertical = cv2.erode(vertical, vertical_kernel)
        vertical = cv2.dilate(vertical, vertical_kernel)
        # 4. Find Joints
        joints = cv2.bitwise_and(horizontal, vertical)

        # 5. Count Joints
        contours, _ = cv2.findContours(joints, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

        # DECISION RULE:
        if len(contours) > 3:
            return True
        return False

    except Exception as e:
        return False

# ==============================================================================
# CONVERSION METHODS
# ==============================================================================

# --- 1. DIGITAL PDF TO WORD (STABLE METHOD: PDF2DOCX) ---
def run_digital_pdf_conversion(input_path, output_path):
    """
    Uses pdf2docx. Fast and stable for English digital PDFs.
    Falls back gracefully if it fails.
    """
    from pdf2docx import Converter
    import sys

    try: os.nice(15)
    except: pass

    try:
        # pdf2docx Converter එක පාවිච්චි කරනවා (No Crash Guaranteed)
        cv = Converter(input_path)
        cv.convert(output_path, start=0, end=None)
        cv.close()

        # Validation
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 2000:
             raise Exception("Output file is empty.")

    except Exception as e:
        print(f"Digital Conversion Error: {e}")
        sys.exit(1)

# --- 2. AZURE TABLE EXTRACTION (SMART AI) ---
def extract_table_data_with_azure(image_crop):
    """
    Sends cropped table image to Azure OpenAI GPT-4o.
    Uses an Engineered Prompt for Data Extraction Specialists.
    """
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment_name = os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o-mini")

    if not azure_api_key or not azure_endpoint:
        print("Azure Credentials Missing.")
        return None


    try:
        client = AzureOpenAI(
            api_key=azure_api_key,
            api_version="2024-02-15-preview",
            azure_endpoint=azure_endpoint
        )

        buffered = io.BytesIO()
        image_crop.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{img_str}"

        # --- IMPROVED PROMPT ---
        prompt = """
        You are a Data Extraction Specialist. Your task is to extract tabular data from the provided image.

        Rules:
        1. Analyze the image to identify table structures, headers, and rows.
        2. If the image contains a valid table or structured list, extract the content into a JSON Array of Arrays (e.g., [["Header1", "Header2"], ["Row1Col1", "Row1Col2"]]).
        3. Handle merged cells by repeating the value or leaving blank as appropriate for a spreadsheet.
        4. If the image is a logo, signature, picture, or handwritten note without tabular structure, return exactly the string: "NULL".
        5. Output ONLY the raw JSON. Do not use Markdown (```json).
        """

        response = client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only JSON."},
                {"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}
            ],
            max_tokens=4096,
            temperature=0 # Zero temperature for deterministic results
        )

        content = response.choices[0].message.content.strip()

        # Cleanup response
        if "null" in content.lower() and len(content) < 10: return None
        if content.startswith("```json"): content = content.replace("```json", "").replace("```", "")
        if content.startswith("```"): content = content.replace("```", "")

        return json.loads(content)
    except Exception as e:
        print(f"Azure API Error: {e}")
        return None

# --- 3. HYBRID AI CONVERSION (HEAVY DUTY - FONT FIXED) ---
def run_hybrid_ai_pdf_conversion(input_path, output_path, options):
    """
    The Advanced Pipeline with KOREAN/JAPANESE FONT SUPPORT.
    """
    try: os.nice(15)
    except: pass

    mem = psutil.virtual_memory()
    if mem.percent > 85:
        print(f"RAM too high for AI ({mem.percent}%). Exiting to Safe Mode.")
        sys.exit(1)

    process_temp_dir = os.path.join(os.path.dirname(input_path), f"temp_hybrid_{os.getpid()}")
    os.makedirs(process_temp_dir, exist_ok=True)

    try:
        try:
            global GLOBAL_LAYOUT_MODEL
            model = GLOBAL_LAYOUT_MODEL
            if model is None:
                logger.warning("⚠️ Model not found in memory, loading now (Fallback)...")
                model = load_ai_model_once()
            logger.info("🚀 Using Pre-loaded AI Model from Memory.")
        except Exception as e:
            logger.error(f"Error accessing Global AI Model: {e}")
            sys.exit(1)

        try: info = pdfinfo_from_path(input_path); total_pages = info["Pages"]
        except: total_pages = 1

        doc = Document()
        section = doc.sections[0]
        section.left_margin = Inches(0.5); section.right_margin = Inches(0.5)
        section.top_margin = Inches(0.5); section.bottom_margin = Inches(0.5)
        style = doc.styles['Normal']; font = style.font; font.name = 'Arial'; font.size = Pt(10)

        logger.info(f"Processing {total_pages} pages with Hybrid AI...")

        for page_num in range(1, total_pages + 1):
            mem = psutil.virtual_memory()
            if mem.percent > 90: time.sleep(5)

            page_images = convert_from_path(input_path, dpi=200, first_page=page_num, last_page=page_num, fmt='jpeg')
            if not page_images: continue
            pil_image = page_images[0]

            layout = model.detect(pil_image)
            all_blocks = [b for b in layout if b.type in ['Text', 'Title', 'List', 'Table', 'Figure']]
            all_blocks.sort(key=lambda b: b.block.y_1)

            for block in all_blocks:
                segment = pil_image.crop((block.block.x_1, block.block.y_1, block.block.x_2, block.block.y_2))

                # Tiny image filter
                is_tiny = False
                if segment.width < 200 or segment.height < 100: is_tiny = True

                temp_seg_path = os.path.join(process_temp_dir, f"check_{page_num}_{block.block.y_1}.jpg")
                segment.save(temp_seg_path)

                is_real_table = False
                table_data = None

                if block.type in ['Table', 'Figure'] and not is_tiny:
                    if contains_table_grid(temp_seg_path):
                        logger.info(f"OpenCV detected >3 Joints. Sending to Azure...")
                        table_data = extract_table_data_with_azure(segment)
                        if table_data and isinstance(table_data, list) and len(table_data) > 0 and len(table_data[0]) > 1:
                            is_real_table = True
                            logger.info("Azure confirmed it's a Table!")
                        else:
                            logger.info("Azure returned NULL or Invalid Data.")
                    else:
                        logger.info(f"Skipping Azure: {block.type} has <10 Joints (Likely Border/Logo).")
                        is_real_table = False

                # --- DRAWING LOGIC ---

                # A. DRAW TABLE
                if is_real_table and table_data:
                    rows = len(table_data); cols = len(table_data[0]) if rows > 0 else 0
                    if rows > 0 and cols > 0:
                        table = doc.add_table(rows=rows, cols=cols); table.style = 'Table Grid'
                        for r, row_data in enumerate(table_data):
                            for c, cell_data in enumerate(row_data):
                                if c < cols:
                                    cell = table.cell(r, c)
                                    # Table Cell Font Fix
                                    run = cell.paragraphs[0].add_run(str(cell_data))
                                    run.font.name = 'Iskoola Pota'
                                    run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Iskoola Pota')

                        doc.add_paragraph()

                # # B. DRAW IMAGE
                # elif block.type in ['Table', 'Figure'] and not is_real_table:
                #     try:
                #         with Image.open(temp_seg_path) as tmp_img:
                #             w, h = tmp_img.size; aspect = w / h
                #         if aspect > 2.5: doc.add_picture(temp_seg_path, width=Inches(6.5))
                #         elif w < 200: doc.add_picture(temp_seg_path, width=Inches(1.5))
                #         else: doc.add_picture(temp_seg_path, width=Inches(4.0))
                #     except:
                #         doc.add_picture(temp_seg_path, width=Inches(4))
                #     doc.add_paragraph()

                # C. DRAW TEXT (KOREAN FIX HERE)
                elif block.type in ['Text', 'Title', 'List']:
                    # Use multi-language Tesseract
                    text = pytesseract.image_to_string(segment, lang='eng+sin')
                    clean_text = text.replace('\x00', '').strip()
                        # --- FONT FIX ---
                        # Set font to Noto Sans CJK (supports Korean/Japanese/Sinhala/Tamil)
                        # ... (clean_text එක හැදුවට පස්සේ) ...
                    if clean_text:
                        p = doc.add_paragraph()
                        run = p.add_run(clean_text)

                        # --- FONT FIX (UPDATED FOR SINHALA & TAMIL) ---
                        # Text එකේ තියෙන අකුරු අනුව Font එක මාරු කිරීම
                        if any('\u0D80' <= c <= '\u0DFF' for c in clean_text): # සිංහල අකුරු තිබේ නම්
                            run.font.name = 'Iskoola Pota'
                            run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Iskoola Pota')
                        
                        else:
                            # ඉංග්‍රීසි සඳහා සාමාන්‍ය ෆොන්ට් එකක්
                            run.font.name = 'Arial'
                            run._element.rPr.rFonts.set(qn('w:eastAsia'), 'Arial')

                        if block.type == 'Title': p.style = 'Heading 1'

                if os.path.exists(temp_seg_path): os.remove(temp_seg_path)

            if page_num < total_pages: doc.add_page_break()

        doc.save(output_path)

    except Exception as e:
        print(f"Hybrid AI Error: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(process_temp_dir):
            try: shutil.rmtree(process_temp_dir)
            except: pass

# --- 4. SAFE OCR CONVERSION (RESTORED FROM PRODUCTION) ---
def run_simple_safe_ocr(input_path, output_path, options):
    """
    FALLBACK METHOD.
    Uses only Tesseract. Low RAM usage. No AI.
    Guarantees output even if AI fails.
    """
    logger.info("Using SAFE OCR Mode (Tesseract Only)...")
    try: os.nice(15)
    except: pass

    process_temp_dir = os.path.join(os.path.dirname(input_path), f"temp_safeocr_{os.getpid()}")
    os.makedirs(process_temp_dir, exist_ok=True)

    try:
        try:
            info = pdfinfo_from_path(input_path)
            total_pages = info["Pages"]
        except:
            total_pages = None

        doc = Document()

        if total_pages:
            for page_num in range(1, total_pages + 1):
                mem = psutil.virtual_memory()
                if mem.percent > 90: time.sleep(5)

                # Convert page to image
                page_images = convert_from_path(
                    input_path, dpi=200, first_page=page_num, last_page=page_num,
                    fmt='jpeg', output_folder=process_temp_dir, paths_only=True
                )

                if page_images:
                    img_path = page_images[0]
                    try:
                        text = pytesseract.image_to_string(Image.open(img_path))
                        safe_text = text.replace('\x00', '')
                        doc.add_paragraph(safe_text)
                        if page_num < total_pages: doc.add_page_break()
                    finally:
                        if os.path.exists(img_path): os.remove(img_path)
                time.sleep(0.5)
        else:
            # Fallback for unknown page count
            image_paths = convert_from_path(input_path, dpi=200, output_folder=process_temp_dir, fmt='jpeg', paths_only=True)
            for i, img_path in enumerate(image_paths):
                text = pytesseract.image_to_string(Image.open(img_path))
                doc.add_paragraph(text.replace('\x00', ''))
                if i < len(image_paths) - 1: doc.add_page_break()
                time.sleep(0.5)

        doc.save(output_path)

    except Exception as e:
        print(f"Safe OCR Error: {e}")
        sys.exit(1)
    finally:
        if os.path.exists(process_temp_dir):
            try: shutil.rmtree(process_temp_dir)
            except: pass


# --- 5. PDF TO EXCEL (SMART & MEMORY OPTIMIZED - V2) ---
def run_pdf_to_excel_conversion(input_path, output_path, options):
    """
    Smart PDF to Excel with Strict Cost Control.
    1. Tries Digital Extraction (Fast/Free).
    2. If fails, uses Hybrid AI (LayoutParser + OpenCV Check + Azure).
    """
    try: os.nice(15)
    except: pass

    dfs = []

    process_temp_dir = os.path.join(os.path.dirname(input_path), f"temp_excel_{os.getpid()}")
    os.makedirs(process_temp_dir, exist_ok=True)

    try:
        # Step A: Digital Extraction (Fast & Free)
        try:
            with pdfplumber.open(input_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if table and len(table) > 1:
                            # Assume Row 1 is Header
                            header = table[0]
                            data = table[1:]
                            dfs.append(pd.DataFrame(data, columns=header))
        except Exception as e:
            logger.warning(f"Digital Extraction Failed: {e}")

        # Step B: AI Check (Only if RAM allows & No tables found)
        mem = psutil.virtual_memory()
        if not dfs and mem.percent < 85:
            logger.info("No digital tables. Attempting AI extraction with GLOBAL MODEL...")

            try:
                # --- MEMORY FIX: USE GLOBAL MODEL ---
                global GLOBAL_LAYOUT_MODEL
                model = GLOBAL_LAYOUT_MODEL

                if model is None:
                    logger.warning("Global Model missing in Excel worker. Loading fallback...")
                    model = load_ai_model_once()
                # ------------------------------------

                # Process pages
                images = convert_from_path(input_path, dpi=200, fmt='jpeg')

                for i, img in enumerate(images):
                    layout = model.detect(img)
                    blocks = [b for b in layout if b.type in ['Table', 'Figure']]

                    for block in blocks:
                        # Crop the potential table
                        segment = img.crop((block.block.x_1, block.block.y_1, block.block.x_2, block.block.y_2))

                        # Temp check image save
                        temp_seg_path = os.path.join(process_temp_dir, f"check_{i}_{block.block.y_1}.jpg")
                        segment.save(temp_seg_path)

                        is_valid = False

                        # --- SMART FILTERING (NEW LOGIC) ---
                        # Table or Figure anytype OpenCV check if Joints > 10 .
                        if block.type in ['Table', 'Figure']:
                            if contains_table_grid(temp_seg_path):
                                is_valid = True
                                logger.info(f"OpenCV Verified Grid in {block.type} (Page {i+1}). Ready for Azure.")
                            else:
                                logger.info(f"Skipping {block.type}: Not enough joints detected.")

                        # Check if good for send open ai
                        if is_valid:
                            json_data = extract_table_data_with_azure(segment)

                            if json_data and isinstance(json_data, list) and len(json_data) > 1:
                                try:
                                    header = json_data[0]
                                    rows = json_data[1:]
                                    dfs.append(pd.DataFrame(rows, columns=header))
                                    logger.info("Azure Data Added to Excel.")
                                except: pass

            except Exception as e:
                logger.error(f"AI Excel Logic Error: {e}")

        # Step C: Save
        if dfs:
            logger.info(f"Saving {len(dfs)} tables to Excel...")
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                for i, df in enumerate(dfs):
                    sheet_name = f"Table_{i+1}"
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            logger.info("No tables found. Saving empty Excel.")
            pd.DataFrame(["No tabular data detected."]).to_excel(output_path, index=False)

    except Exception as e:
        logger.error(f"Excel Process Critical Error: {e}")
        # Error try to make fresh file (trying to safe with Crash)
        if not os.path.exists(output_path):
             pd.DataFrame(["Conversion Failed."]).to_excel(output_path, index=False)

    finally:
        # (Cleanup)
        if os.path.exists(process_temp_dir):
            try: shutil.rmtree(process_temp_dir)
            except: pass

# --- 6. VECTOR CONVERSION (PRODUCTION) ---
def run_vector_conversion(input_path, output_path, options):
    import os, sys, vtracer, subprocess
    from PIL import Image
    try: os.nice(15)
    except: pass

    vtracer_input = input_path
    temp_png = None
    safe_formats = ['jpg', 'jpeg', 'png', 'bmp']
    try:
        input_ext = os.path.splitext(input_path)[1].lower().strip('.')
        if input_ext not in safe_formats:
            temp_png = input_path + ".png"
            with Image.open(input_path) as img: img.save(temp_png, "PNG")
            vtracer_input = temp_png

        if options.get('vector_mode') == 'color':
            clustering_mode = options.get('clustering', 'stacked')
            vtracer.convert_image_to_svg_py(
                vtracer_input, output_path, colormode='color', hierarchical=clustering_mode,
                mode=options.get('curve_fitting', 'spline'),
                filter_speckle=int(options.get('filter_speckle', 4)),
                color_precision=int(options.get('color_precision', 6)),
                layer_difference=16, corner_threshold=int(options.get('corner_threshold', 60)),
                length_threshold=int(options.get('segment_length', 4)),
                max_iterations=10, splice_threshold=int(options.get('splice_threshold', 45)), path_precision=3
            )
        else:
            with Image.open(vtracer_input) as img:
                bmp_path = vtracer_input + ".bmp"
                img.convert('1').save(bmp_path)
            subprocess.run(['potrace', bmp_path, '-s', '-o', output_path], check=True)
            if os.path.exists(bmp_path): os.remove(bmp_path)
    except Exception as e:
        print(f"Vector Error: {e}")
        sys.exit(1)
    finally:
        if temp_png and os.path.exists(temp_png): os.remove(temp_png)


# ==============================================================================
# WORKER CLASS
# ==============================================================================

class ConversionWorker:
    def __init__(self, worker_id: int = 0):
        self.worker_id = worker_id
        self.queue = QueueService()
        self.storage = StorageService()
        self.converter = ConversionService()
        self.running = False
        self.sem = asyncio.Semaphore(1)

    async def start(self) -> None:
        logger.info(f"Worker {self.worker_id} started. HEALTH CHECK: ACTIVE.")
        await self.queue.connect()
        await self.storage.initialize()
        self.running = True

        while self.running:
            wait_for_resources(threshold_percent=90)
            await self.sem.acquire()

            try:
                job = await self.queue.dequeue_job()

                if not job:
                    self.sem.release()
                    await asyncio.sleep(settings.WORKER_CHECK_INTERVAL)
                    continue

                asyncio.create_task(self._process_wrapper(job))

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                self.sem.release()
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self.running = False
        await self.queue.disconnect()
        logger.info("Worker stopped")

    async def _process_wrapper(self, job):
        try:
            await self._process_job_logic(job)
        except Exception as e:
            logger.error(f"Job Wrapper Error {job.get('job_id')}: {e}")
        finally:
            self.sem.release()

    def _apply_resize(self, img, options):
        width = int(options.get('width')) if options.get('width') else None
        height = int(options.get('height')) if options.get('height') else None
        max_dim = int(options.get('max_dimension')) if options.get('max_dimension') else None
        orig_w, orig_h = img.size

        if max_dim:
            if orig_w > max_dim or orig_h > max_dim:
                if orig_w > orig_h: width = max_dim; height = None
                else: height = max_dim; width = None

        if not width and not height: return img

        if width and height: new_size = (width, height)
        elif width:
            ratio = width / orig_w
            new_size = (width, int(orig_h * ratio))
        else:
            ratio = height / orig_h
            new_size = (int(orig_w * ratio), height)

        return img.resize(new_size, Image.Resampling.LANCZOS)

    def _get_save_kwargs(self, fmt, options):
        kwargs = {}
        quality = int(options.get('quality', 85))
        dpi = int(options.get('dpi', 150))
        comp_level = options.get('compression_level', 'medium')
        if comp_level == 'low': quality = max(quality, 90)
        elif comp_level == 'high': quality = min(quality, 70)
        elif comp_level == 'maximum': quality = min(quality, 50)

        if fmt in ['jpg', 'jpeg']:
            kwargs = {'quality': quality, 'optimize': True, 'progressive': True}
        elif fmt == 'png':
            kwargs = {'optimize': True, 'compress_level': 6}
        elif fmt == 'webp':
            kwargs = {'quality': quality, 'method': 6}
        elif fmt == 'tiff':
            kwargs = {'compression': 'tiff_lzw'}

        if dpi and fmt not in ['gif', 'bmp']:
            kwargs['dpi'] = (dpi, dpi)

        return kwargs

    async def _process_job_logic(self, job) -> None:
        job_id = job["job_id"]
        logger.info(f"Processing job: {job_id}")

        try:
            await self.queue.update_job_status(job_id, "processing", progress="10")

            input_content = await self.storage.download_file(job["input_blob_name"], "uploads")

            temp_input = os.path.join(settings.TEMP_DIR, "uploads", job_id, job["original_filename"])
            os.makedirs(os.path.dirname(temp_input), exist_ok=True)
            with open(temp_input, 'wb') as f:
                f.write(input_content)

            input_ext = job["input_extension"].lower().strip('.')
            output_format = job["output_format"].lower().strip('.')
            options = job.get("options", {})

            filename_no_ext = os.path.splitext(job["original_filename"])[0]
            output_filename = f"{filename_no_ext}.{output_format}"
            temp_output = os.path.join(settings.TEMP_DIR, "outputs", job_id, output_filename)
            os.makedirs(os.path.dirname(temp_output), exist_ok=True)

            await self.queue.update_job_status(job_id, "processing", progress="30")

            # ------------------------------------------------------------------
            # CASE 1: PDF -> WORD (The Fallback Chain)
            # ------------------------------------------------------------------
            if input_ext == 'pdf' and output_format == 'docx':
                is_digital = await asyncio.to_thread(has_extractable_text, temp_input)
                success_digital = False

                # ATTEMPT 1: Digital Conversion (Best Quality)
                if is_digital:
                    logger.info("Detected Digital PDF. Attempting High-Quality Conversion...")
                    p = multiprocessing.Process(
                        target=run_digital_pdf_conversion,
                        args=(temp_input, temp_output)
                    )
                    p.start()
                    p.join(timeout=120)

                    if p.is_alive():
                        logger.warning("Digital Conversion Timeout.")
                        kill_process_tree(p.pid)
                    elif p.exitcode == 0:
                        success_digital = True
                        logger.info("Digital Conversion Success!")

                # ATTEMPT 2: Hybrid AI (If Digital Failed)
                if not success_digital:
                    logger.info("Attempting Hybrid AI Mode (LayoutParser + Azure)...")
                    p = multiprocessing.Process(
                        target=run_hybrid_ai_pdf_conversion,
                        args=(temp_input, temp_output, options)
                    )
                    p.start()

                    ai_failed = False
                    try:
                        start_time = time.time()
                        TIMEOUT = 240 # 4 Minutes
                        while p.is_alive():
                            if time.time() - start_time > TIMEOUT:
                                logger.error("AI Job Timed Out.")
                                kill_process_tree(p.pid)
                                ai_failed = True
                                break
                            await asyncio.sleep(1)

                        if p.exitcode != 0: ai_failed = True
                    except:
                        ai_failed = True
                    finally:
                        if p.is_alive(): kill_process_tree(p.pid)

                    # ATTEMPT 3: Safe OCR Fallback (If AI Failed)
                    if ai_failed:
                        logger.warning("AI Mode Failed/Crashed. Switching to SAFE OCR (Fallback)...")
                        p_safe = multiprocessing.Process(
                            target=run_simple_safe_ocr,
                            args=(temp_input, temp_output, options)
                        )
                        p_safe.start()
                        try:
                            start_time = time.time()
                            TIMEOUT = 200 # 3.3 Minutes
                            while p_safe.is_alive():
                                if time.time() - start_time > TIMEOUT:
                                    kill_process_tree(p_safe.pid)
                                    raise Exception("Safe OCR Timeout")
                                await asyncio.sleep(1)

                            if p_safe.exitcode != 0: raise Exception("Safe OCR Failed")
                        finally:
                            if p_safe.is_alive(): kill_process_tree(p_safe.pid)

            # ------------------------------------------------------------------
            # CASE 2: VECTOR TRACING
            # ------------------------------------------------------------------
            elif output_format == 'svg':
                logger.info("Starting Vector Tracing...")
                p = multiprocessing.Process(
                    target=run_vector_conversion,
                    args=(temp_input, temp_output, options)
                )
                p.start()
                try:
                    start_time = time.time()
                    TIMEOUT = 300
                    while p.is_alive():
                        if time.time() - start_time > TIMEOUT:
                            logger.error(f"Vector Job {job_id} TIMEOUT")
                            kill_process_tree(p.pid)
                            raise Exception("Vector Timeout")
                        await asyncio.sleep(1)
                    if p.exitcode != 0: raise Exception("Vector Failed")
                finally:
                    if p.is_alive(): kill_process_tree(p.pid)

            # ------------------------------------------------------------------
            # CASE 3: PDF -> EXCEL
            # ------------------------------------------------------------------
            elif input_ext == 'pdf' and output_format in ['xlsx', 'xls']:
                logger.info("Starting PDF to Excel...")
                p = multiprocessing.Process(
                    target=run_pdf_to_excel_conversion,
                    args=(temp_input, temp_output, options)
                )
                p.start()
                try:
                    start_time = time.time()
                    TIMEOUT = 240
                    while p.is_alive():
                        if time.time() - start_time > TIMEOUT:
                            kill_process_tree(p.pid)
                            raise Exception("Excel Conversion Timeout")
                        await asyncio.sleep(1)
                    if p.exitcode != 0: raise Exception("Excel Conversion Failed")
                finally:
                    if p.is_alive(): kill_process_tree(p.pid)

            # ------------------------------------------------------------------
            # CASE 4: DOC/DOCX Conversion (LibreOffice)
            # ------------------------------------------------------------------
            elif input_ext in ['doc', 'docx'] and output_format in ['pdf', 'jpg', 'jpeg', 'png', 'webp', 'tiff']:
                logger.info(f"Handling DOC conversion...")
                temp_pdf_dir = os.path.dirname(temp_input)
                libreoffice_cmd = getattr(settings, 'LIBREOFFICE_PATH', 'libreoffice')

                cmd = [
                    'nice', '-n', '10',
                    libreoffice_cmd,
                    f'-env:UserInstallation=file://{temp_pdf_dir}/user_profile',
                    '--headless', '--convert-to', 'pdf',
                    '--outdir', temp_pdf_dir,
                    temp_input
                ]

                await asyncio.to_thread(
                    subprocess.run, cmd, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )

                generated_pdf_name = os.path.splitext(os.path.basename(temp_input))[0] + ".pdf"
                generated_pdf_path = os.path.join(temp_pdf_dir, generated_pdf_name)

                if output_format == 'pdf':
                    if os.path.exists(temp_output): os.remove(temp_output)
                    shutil.move(generated_pdf_path, temp_output)
                else:
                    # Convert generated PDF to images
                    req_dpi = int(options.get('dpi', 150))
                    images = await asyncio.to_thread(convert_from_path, generated_pdf_path, fmt=output_format, dpi=req_dpi)

                    if not images: raise Exception("No images from DOC")
                    save_fmt = "JPEG" if output_format in ['jpg', 'jpeg'] else output_format.upper()
                    save_kwargs = self._get_save_kwargs(output_format, options)

                    if len(images) > 1:
                        # Zip Logic
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_STORED, False) as zf:
                            for i, img in enumerate(images):
                                img = self._apply_resize(img, options)
                                b = io.BytesIO()
                                img.save(b, format=save_fmt, **save_kwargs)
                                zf.writestr(f"page_{i+1}.{output_format}", b.getvalue())
                        with open(temp_output, "wb") as f: f.write(zip_buffer.getvalue())
                        # Rename output for zip
                        output_filename = f"{filename_no_ext}.zip"
                        output_blob = f"{job_id}/{output_filename}"
                    else:
                        img = self._apply_resize(images[0], options)
                        img.save(temp_output, format=save_fmt, **save_kwargs)

            # ------------------------------------------------------------------
            # CASE 5: PDF -> IMAGES
            # ------------------------------------------------------------------
            elif input_ext == 'pdf' and output_format in ['jpg', 'jpeg', 'png', 'webp', 'tiff']:
                req_dpi = int(options.get('dpi', 150))
                images = await asyncio.to_thread(convert_from_path, temp_input, fmt=output_format, dpi=req_dpi)

                if not images: raise Exception("PDF Empty")
                save_fmt = "JPEG" if output_format in ['jpg', 'jpeg'] else output_format.upper()
                save_kwargs = self._get_save_kwargs(output_format, options)

                if len(images) > 1:
                    output_filename = f"{filename_no_ext}.zip"
                    # Re-define temp output for ZIP
                    temp_output = os.path.join(settings.TEMP_DIR, "outputs", job_id, output_filename)

                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_STORED, False) as zf:
                        for i, img in enumerate(images):
                            img = self._apply_resize(img, options)
                            b = io.BytesIO()
                            img.save(b, format=save_fmt, **save_kwargs)
                            zf.writestr(f"page_{i+1}.{output_format}", b.getvalue())
                    with open(temp_output, "wb") as f: f.write(zip_buffer.getvalue())
                else:
                    img = self._apply_resize(images[0], options)
                    img.save(temp_output, format=save_fmt, **save_kwargs)

            # ------------------------------------------------------------------
            # CASE 6: DEFAULT FALLBACK (Other formats)
            # ------------------------------------------------------------------
            else:
                output_content, out_ext = await self.converter.convert(
                    input_content, input_ext, output_format, options
                )
                with open(temp_output, 'wb') as f:
                    f.write(output_content)

            # ==========================================
            # FINALIZE JOB
            # ==========================================
            await self.queue.update_job_status(job_id, "processing", progress="90")

            # Re-verify output blob name in case it changed (like .zip)
            if 'output_filename' not in locals():
                output_filename = f"{filename_no_ext}.{output_format}"

            output_blob = f"{job_id}/{output_filename}"

            # Upload
            with open(temp_output, 'rb') as f: output_data = f.read()
            await self.storage.upload_file(output_data, output_blob, container="outputs")

            await self.queue.update_job_status(
                job_id, "completed", progress="100",
                output_blob_name=output_blob, output_filename=output_filename,
                output_size=str(len(output_data)), input_size=str(len(input_content)),
                completed_at=datetime.now(timezone.utc).isoformat()
            )
            logger.info(f"Job {job_id} Completed Successfully.")

            # --- [NEW] DASHBOARD LOGGING (SUCCESS) ---
            try:
                dashboard_service.log_job_completion(
                    job_id=job_id,
                    job_type=f"{input_ext}-to-{output_format}",
                    status="completed",
                    input_size=len(input_content)
                )
            except Exception as log_err:
                logger.error(f"Failed to log stats: {log_err}")
            # -----------------------------------------

        except Exception as e:
            logger.error(f"Job {job_id} Failed: {e}")
            await self.queue.update_job_status(job_id, "failed", error=str(e))

            # --- [NEW] DASHBOARD LOGGING (FAILURE) ---
            try:
                # Safe variable access for logging failure
                size = len(input_content) if 'input_content' in locals() else 0
                j_type = "unknown"
                if 'input_ext' in locals() and 'output_format' in locals():
                    j_type = f"{input_ext}-to-{output_format}"
                
                dashboard_service.log_job_completion(
                    job_id=job_id,
                    job_type=j_type,
                    status="failed",
                    input_size=size
                )
            except Exception as log_err:
                logger.error(f"Failed to log failure stats: {log_err}")
            # -----------------------------------------

async def run_worker():
    load_ai_model_once()
    worker = ConversionWorker()
    try: await worker.start()
    except KeyboardInterrupt: await worker.stop()

if __name__ == '__main__':
    asyncio.run(run_worker())
