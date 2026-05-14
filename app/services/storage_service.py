"""
Storage Service - Local File System Implementation (Optimized)
Handles file uploads, downloads, and directory cleanup locally with Stream Support.
"""

import os
import logging
import shutil
import aiofiles
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

class StorageService:
    """Local storage service with directory cleanup capabilities"""
    
    def __init__(self):
        self.initialized = True

    async def initialize(self) -> None:
        """Initialize local directories"""
        try:
            # Create uploads and outputs folders if they don't exist
            for container in ["uploads", "outputs"]:
                path = os.path.join(settings.TEMP_DIR, container)
                os.makedirs(path, exist_ok=True)
            logger.info(f"Local Storage initialized at: {settings.TEMP_DIR}")
        except Exception as e:
            logger.error(f"Storage initialization failed: {e}")

    async def health_check(self) -> bool:
        """Check if storage directory is writable"""
        try:
            return os.path.exists(settings.TEMP_DIR) and os.access(settings.TEMP_DIR, os.W_OK)
        except Exception:
            return False

    async def close(self) -> None:
        """No connection to close for local storage"""
        pass

    async def upload_file(self, file_content: bytes, blob_name: str, content_type: str = "", container: str = "uploads") -> str:
        """Save bytes to local storage (Classic method)"""
        try:
            local_path = os.path.join(settings.TEMP_DIR, container, blob_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            async with aiofiles.open(local_path, 'wb') as f:
                await f.write(file_content)
            
            logger.info(f"Saved local file (bytes): {local_path}")
            return f"local://{container}/{blob_name}"
        except Exception as e:
            logger.error(f"Local upload failed: {e}")
            raise

    # --- NEW: Low RAM Upload Method ---
    async def upload_from_path(self, source_path: str, blob_name: str, container: str = "uploads") -> str:
        """
        Moves a file from a temporary path to the storage container.
        This avoids loading the file into RAM.
        """
        try:
            target_path = os.path.join(settings.TEMP_DIR, container, blob_name)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # Use move if on same filesystem for instant transfer, else copy
            shutil.move(source_path, target_path)
            
            logger.info(f"Moved file to storage: {target_path}")
            return f"local://{container}/{blob_name}"
        except Exception as e:
            logger.error(f"Upload from path failed: {e}")
            raise

    async def download_file(self, blob_name: str, container: str = "uploads") -> bytes:
        """Read file from local storage into RAM"""
        try:
            local_path = os.path.join(settings.TEMP_DIR, container, blob_name)
            if not os.path.exists(local_path):
                raise FileNotFoundError(f"File not found: {local_path}")
            
            async with aiofiles.open(local_path, 'rb') as f:
                return await f.read()
        except Exception as e:
            logger.error(f"Local download failed: {e}")
            raise

    # --- NEW: Get Path Method ---
    async def get_file_path(self, blob_name: str, container: str = "uploads") -> str:
        """Returns the absolute file path (Useful for FileResponse streaming)"""
        local_path = os.path.join(settings.TEMP_DIR, container, blob_name)
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")
        return local_path

    async def delete_file(self, blob_name: str, container: str = "uploads") -> bool:
        """Delete a single file"""
        try:
            local_path = os.path.join(settings.TEMP_DIR, container, blob_name)
            if os.path.exists(local_path):
                os.remove(local_path)
                return True
            return False
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False

    async def get_download_url(self, blob_name: str, container: str = "outputs", expiry_hours: int = None) -> str:
        """Return local download URL path"""
        return f"/api/local-download/{container}/{blob_name}"

    async def cleanup_job_files(self, job_id: str, input_blob: str = None, output_blob: str = None) -> None:
        """Completely remove the folder associated with the Job ID."""
        try:
            for container in ["uploads", "outputs"]:
                job_dir = os.path.join(settings.TEMP_DIR, container, job_id)
                if os.path.exists(job_dir):
                    shutil.rmtree(job_dir) 
                    logger.info(f"Deleted directory: {job_dir}")
        except Exception as e:
            logger.error(f"Cleanup failed for job {job_id}: {e}")

    async def _upload_local(self, *args, **kwargs): return await self.upload_file(*args, **kwargs)
    async def _download_local(self, *args, **kwargs): return await self.download_file(*args, **kwargs)
    async def _delete_local(self, *args, **kwargs): return await self.delete_file(*args, **kwargs)
