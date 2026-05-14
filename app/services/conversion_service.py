"""
Conversion Service - File Conversion with Smart Compression
Supports: JPG, PNG, WEBP, GIF, BMP, TIFF, HEIC, HEIF, SVG, PDF, Documents
"""

import os
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, Tuple
from io import BytesIO

# --- NEW: High Performance Image Engine ---
import pyvips

from PIL import Image
import img2pdf

# Try to import HEIC support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False

# Try to import SVG support
try:
    import cairosvg
    SVG_SUPPORTED = True
except ImportError:
    SVG_SUPPORTED = False

from app.config import settings

logger = logging.getLogger(__name__)


class ConversionService:
    """File conversion service with smart compression"""

    # Supported formats
    STANDARD_IMAGE_FORMATS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'tif'}
    HEIC_FORMATS = {'heic', 'heif'}
    SVG_FORMATS = {'svg'}
    DOC_FORMATS = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'html', 'htm', 'odt', 'epub'}

    # All image input formats (for routing)
    ALL_IMAGE_INPUTS = STANDARD_IMAGE_FORMATS | HEIC_FORMATS | SVG_FORMATS

    def __init__(self):
        self.temp_dir = settings.TEMP_DIR
        os.makedirs(self.temp_dir, exist_ok=True)

    async def convert(
        self,
        input_content: bytes,
        input_extension: str,
        output_format: str,
        options: Dict[str, Any]
    ) -> Tuple[bytes, str]:
        """
        Convert file with smart compression.
        Returns (output_bytes, output_extension)
        """
        input_ext = input_extension.lower().strip('.')
        output_fmt = output_format.lower().strip('.')

        input_size = len(input_content)
        logger.info(f"Converting {input_ext} -> {output_fmt} (input: {input_size} bytes)")

        # Determine input type
        is_heic = input_ext in self.HEIC_FORMATS
        is_svg = input_ext in self.SVG_FORMATS
        is_standard_image = input_ext in self.STANDARD_IMAGE_FORMATS
        is_pdf = input_ext == 'pdf'
        is_doc = input_ext in self.DOC_FORMATS

        # Determine output type
        is_image_output = output_fmt in self.STANDARD_IMAGE_FORMATS
        is_pdf_output = output_fmt == 'pdf'

        try:
            # Route based on input type
            if is_heic:
                if not HEIC_SUPPORTED:
                    raise ValueError("HEIC support missing. pip install pillow-heif")
                if is_image_output:
                    result = await self._heic_to_image(input_content, output_fmt, options)
                elif is_pdf_output:
                    result = await self._heic_to_pdf(input_content, options)
                else:
                    raise ValueError(f"Cannot convert HEIC to {output_fmt}")

            elif is_svg:
                if is_image_output:
                    result = await self._svg_to_image(input_content, output_fmt, options)
                elif is_pdf_output:
                    result = await self._svg_to_pdf(input_content, options)
                else:
                    raise ValueError(f"Cannot convert SVG to {output_fmt}")

            elif is_standard_image:
                if is_image_output:
                    # UPDATED: Now uses hybrid VIPS/Pillow approach
                    result = await self._image_to_image(input_content, input_ext, output_fmt, options)
                elif is_pdf_output:
                    result = await self._image_to_pdf(input_content, options)
                else:
                    raise ValueError(f"Cannot convert {input_ext} to {output_fmt}")

            elif is_pdf:
                if is_image_output:
                    result = await self._pdf_to_image(input_content, output_fmt, options)
                else:
                    raise ValueError(f"Cannot convert PDF to {output_fmt}")

            elif is_doc:
                if is_pdf_output:
                    result = await self._doc_to_pdf(input_content, input_ext, options)
                elif is_image_output:
                    result = await self._doc_to_image(input_content, input_ext, output_fmt, options)
                else:
                    raise ValueError(f"Cannot convert {input_ext} to {output_fmt}")

            else:
                raise ValueError(f"Unsupported input format: {input_ext}")

            output_content, output_ext = result
            output_size = len(output_content)

            # Log result
            if input_size > 0:
                ratio = (1 - output_size / input_size) * 100
                logger.info(f"Done: {input_size} -> {output_size} bytes ({ratio:.1f}% {'reduced' if ratio > 0 else 'increased'})")

            return output_content, output_ext

        except Exception as e:
            logger.error(f"Conversion error: {e}")
            raise

    # ... [Internal helper methods below] ...

    async def _image_to_image(self, content: bytes, input_ext: str, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        """
        Smart Image Conversion:
        Tries VIPS (Fast) first. If it fails, falls back to Pillow (Safe).
        """
        try:
            # 1. Attempt High-Performance VIPS Conversion
            return await self._vips_process_image(content, output_fmt, options)
        except Exception as e:
            logger.warning(f"VIPS Conversion failed ({e}), falling back to Pillow.")
            # 2. Fallback to Pillow
            img = Image.open(BytesIO(content))
            return await self._process_and_save_image(img, output_fmt, options)

    async def _vips_process_image(self, content: bytes, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        """
        Process image using libvips (Memory Efficient & Fast)
        """
        # Parse Options
        quality = int(options.get('quality', 85))
        width = int(options.get('width')) if options.get('width') else None
        height = int(options.get('height')) if options.get('height') else None
        max_dim = int(options.get('max_dimension')) if options.get('max_dimension') else None

        # 1. Load & Resize (Using VIPS thumbnail logic which is super fast)
        image = None

        # If resizing is needed, use thumbnail_buffer (Load-on-demand resizing)
        if max_dim:
             image = pyvips.Image.thumbnail_buffer(content, max_dim)
        elif width and not height:
             image = pyvips.Image.thumbnail_buffer(content, width)
        elif height and not width:
             # VIPS thumbnail needs a width, so we set a large width and limit by height
             image = pyvips.Image.thumbnail_buffer(content, 10000, height=height)
        elif width and height:
             # Force dimensions
             image = pyvips.Image.thumbnail_buffer(content, width, height=height, size=pyvips.enums.Size.FORCE)
        else:
             # No resize, just load
             image = pyvips.Image.new_from_buffer(content, "")

        # 2. Handle Rotation (EXIF)
        image = image.autorot()

        # 3. Handle Color Profile (CMYK -> sRGB for web compatibility)
        if image.hasalpha():
            # If has alpha, ensure we are in a safe space
            if image.interpretation == 'cmyk':
                image = image.icc_transform('srgb')
        else:
             if image.interpretation == 'cmyk':
                image = image.icc_transform('srgb')

        # 4. Save Options
        save_options = {}

        if output_fmt in ['jpg', 'jpeg']:
             # VIPS uses 'Q' for quality, strip to remove metadata
             save_options = {'Q': quality, 'optimize_coding': True, 'strip': True}
             # Handle background color if jpg (flatten alpha)
             # VIPS handles alpha in JPG by flattening to black usually,
             # but we can flatten manually to white if needed.
             if image.hasalpha():
                 # Flatten against white background
                 bg = image.new_from_image([255, 255, 255])
                 image = image.composite2(bg, pyvips.enums.BlendMode.DEST_OVER)

        elif output_fmt == 'png':
             # Compression 0-9
             save_options = {'compression': 6, 'bitdepth': 8}

        elif output_fmt == 'webp':
             save_options = {'Q': quality}

        elif output_fmt in ['tiff', 'tif']:
             save_options = {'compression': 'lzw'}

        # 5. Write to Buffer
        output_buffer = image.write_to_buffer(f".{output_fmt}", **save_options)

        return output_buffer, output_fmt

    async def _heic_to_image(self, content: bytes, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        img = Image.open(BytesIO(content))
        return await self._process_and_save_image(img, output_fmt, options)

    async def _heic_to_pdf(self, content: bytes, options: Dict[str, Any]) -> Tuple[bytes, str]:
        img = Image.open(BytesIO(content))
        return await self._pil_image_to_pdf(img, options)

    async def _svg_to_image(self, content: bytes, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        if not SVG_SUPPORTED: raise ValueError("SVG support missing. pip install cairosvg")
        dpi = options.get('dpi', 150)
        scale = dpi / 96
        png_data = cairosvg.svg2png(bytestring=content, scale=scale)
        if output_fmt == 'png': return png_data, 'png'
        img = Image.open(BytesIO(png_data))
        return await self._process_and_save_image(img, output_fmt, options)

    async def _svg_to_pdf(self, content: bytes, options: Dict[str, Any]) -> Tuple[bytes, str]:
        if not SVG_SUPPORTED: raise ValueError("SVG support missing. pip install cairosvg")
        pdf_data = cairosvg.svg2pdf(bytestring=content)
        return pdf_data, 'pdf'

    # --- OLD PILLOW HELPERS (Kept for fallback & PDF/HEIC support) ---

    async def _process_and_save_image(self, img: Image.Image, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        # Get options
        quality = options.get('quality', 85)
        # Safe Integer Conversion for dimensions
        target_width = int(options.get('width')) if options.get('width') else None
        target_height = int(options.get('height')) if options.get('height') else None
        max_dimension = int(options.get('max_dimension')) if options.get('max_dimension') else None
        compression_level = options.get('compression_level', 'medium')

        # Compression Presets
        if compression_level == 'low': quality = max(quality, 90)
        elif compression_level == 'high': quality = min(quality, 70)
        elif compression_level == 'maximum':
            quality = min(quality, 50)
            if not max_dimension: max_dimension = 1920

        # Resize
        if target_width or target_height or max_dimension:
            img = self._resize_image(img, target_width, target_height, max_dimension)

        # Prepare mode
        img = self._prepare_for_output(img, output_fmt, options)

        # Get Save Options
        save_opts = self._get_save_options(output_fmt, quality, options)

        # Save
        buffer = BytesIO()
        format_map = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP', 'gif': 'GIF', 'bmp': 'BMP', 'tiff': 'TIFF', 'tif': 'TIFF'}
        pil_format = format_map.get(output_fmt, output_fmt.upper())

        img.save(buffer, format=pil_format, **save_opts)
        return buffer.getvalue(), output_fmt

    def _prepare_for_output(self, img: Image.Image, output_fmt: str, options: Dict) -> Image.Image:
        bg_color = options.get('background_color', '#FFFFFF')

        if output_fmt in ('jpg', 'jpeg'):
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, bg_color)
                if img.mode == 'P': img = img.convert('RGBA')
                background.paste(img, mask=img.split()[3] if len(img.split()) > 3 else None)
                return background
            elif img.mode != 'RGB': return img.convert('RGB')
        elif output_fmt == 'png' and img.mode == 'CMYK': return img.convert('RGBA')
        elif output_fmt == 'webp' and img.mode == 'CMYK': return img.convert('RGB')
        elif output_fmt == 'bmp' and img.mode not in ('RGB', 'L', 'P'): return img.convert('RGB')

        return img

    def _resize_image(self, img: Image.Image, width=None, height=None, max_dim=None) -> Image.Image:
        orig_w, orig_h = img.size

        # FIX 1: Ensure checks are safe against None
        if max_dim is not None and max_dim > 0:
            if orig_w > max_dim or orig_h > max_dim:
                if orig_w > orig_h:
                    width = max_dim
                    height = None
                else:
                    height = max_dim
                    width = None

        if not width and not height: return img

        if width and height: new_size = (int(width), int(height))
        elif width:
            ratio = int(width) / orig_w
            new_size = (int(width), int(orig_h * ratio))
        else:
            ratio = int(height) / orig_h
            new_size = (int(orig_w * ratio), int(height))

        return img.resize(new_size, Image.Resampling.LANCZOS)

    def _get_save_options(self, output_fmt: str, quality: int, options: Dict) -> Dict:
        save_opts = {}
        dpi = options.get('dpi', settings.DEFAULT_DPI)

        if output_fmt in ('jpg', 'jpeg'):
            save_opts = {'quality': quality, 'optimize': True, 'progressive': True}
            if quality < 70: save_opts['subsampling'] = 2
            elif quality < 85: save_opts['subsampling'] = 1
        elif output_fmt == 'png':
            save_opts = {'optimize': True, 'compress_level': 6 if quality >= 80 else 9}
        elif output_fmt == 'webp':
            save_opts = {'quality': quality, 'method': 6}
        elif output_fmt in ('tiff', 'tif'):
            comp = options.get('compression', 'default')
            if comp in ('lzw', 'default'): save_opts['compression'] = 'tiff_lzw'
            elif comp == 'jpeg':
                save_opts['compression'] = 'jpeg'
                save_opts['quality'] = quality

        if dpi and output_fmt not in ('gif', 'bmp'): save_opts['dpi'] = (dpi, dpi)
        return save_opts

    async def _image_to_pdf(self, content: bytes, options: Dict[str, Any]) -> Tuple[bytes, str]:
        img = Image.open(BytesIO(content))
        return await self._pil_image_to_pdf(img, options)

    async def _pil_image_to_pdf(self, img: Image.Image, options: Dict[str, Any]) -> Tuple[bytes, str]:
        # FIX 2: Handle NoneType for max_dimension explicitly
        max_dim = options.get('max_dimension')
        if not max_dim:
            max_dim = 2480
        else:
            max_dim = int(max_dim) # Ensure it's an int

        if img.size[0] > max_dim or img.size[1] > max_dim:
            img = self._resize_image(img, max_dim=max_dim)

        if img.mode != 'RGB': img = img.convert('RGB')

        img_buffer = BytesIO()
        img.save(img_buffer, format='JPEG', quality=85)

        dpi = options.get('dpi', settings.DEFAULT_DPI)
        pdf_content = img2pdf.convert(img_buffer.getvalue(), dpi=dpi)
        return pdf_content, 'pdf'

    async def _pdf_to_image(self, content: bytes, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        with tempfile.TemporaryDirectory(dir=self.temp_dir) as temp_dir:
            pdf_path = os.path.join(temp_dir, "input.pdf")
            with open(pdf_path, 'wb') as f: f.write(content)

            dpi = options.get('dpi', 150)
            quality = options.get('quality', 85)
            cmd = ['pdftoppm', '-r', str(dpi)]

            if output_fmt in ('jpg', 'jpeg'):
                cmd.extend(['-jpeg', '-jpegopt', f'quality={quality}'])
                ext = 'jpg'
            else:
                cmd.append('-png')
                ext = 'png'

            cmd.extend([pdf_path, os.path.join(temp_dir, "output")])
            subprocess.run(cmd, check=True)

            files = sorted([f for f in os.listdir(temp_dir) if f.startswith('output')])
            if not files: raise RuntimeError("PDF conversion failed")

            with open(os.path.join(temp_dir, files[0]), 'rb') as f:
                data = f.read()

            if len(files) == 1:
                # Convert if needed (e.g. to webp)
                if output_fmt not in ('jpg', 'jpeg', 'png'):
                    img = Image.open(BytesIO(data))
                    return await self._process_and_save_image(img, output_fmt, options)
                return data, ext

            # Zip logic would go here for multi-page
            return data, ext # Returning first page for now as per logic

    async def _doc_to_pdf(self, content: bytes, input_ext: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        with tempfile.TemporaryDirectory(dir=self.temp_dir) as temp_dir:
            input_path = os.path.join(temp_dir, f"input.{input_ext}")
            with open(input_path, 'wb') as f: f.write(content)

            # --- FIXED: Added Unique UserInstallation to prevent Profile Locking ---
            cmd = [
                settings.LIBREOFFICE_PATH,
                f'-env:UserInstallation=file://{temp_dir}/user_profile', # Unique Profile
                '--headless', '--convert-to', 'pdf',
                '--outdir', temp_dir,
                input_path
            ]
            subprocess.run(cmd, check=True, env={**os.environ, 'HOME': temp_dir})

            pdf_files = [f for f in os.listdir(temp_dir) if f.endswith('.pdf')]
            if not pdf_files: raise RuntimeError("Doc conversion failed")

            with open(os.path.join(temp_dir, pdf_files[0]), 'rb') as f:
                return f.read(), 'pdf'

    async def _doc_to_image(self, content: bytes, input_ext: str, output_fmt: str, options: Dict[str, Any]) -> Tuple[bytes, str]:
        pdf, _ = await self._doc_to_pdf(content, input_ext, options)
        return await self._pdf_to_image(pdf, output_fmt, options)

