"""
Configuration Settings for FileConverter Application
(Updated for Dashboard Security & Monitoring)
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings

# --- FIX: Define BASE_DIR outside the class ---
# This calculates the project root: /var/www/ConvertSoon
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application Settings
    APP_NAME: str = "FileConverter"
    APP_VERSION: str = "1.0.0"
    SITE_TITLE: str = "FileConverter - Free Online File Conversion"
    SITE_DESCRIPTION: str = "Convert images and documents to various formats online."
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    
    # Server Settings
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    
    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: Optional[str] = None
    
    # Azure Blob Storage
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_UPLOAD_CONTAINER: str = "uploads"
    AZURE_OUTPUT_CONTAINER: str = "outputs"
    AZURE_SAS_EXPIRY_HOURS: int = 24
    
    # Legacy names (for compatibility)
    AZURE_STORAGE_CONTAINER_UPLOADS: str = "uploads"
    AZURE_STORAGE_CONTAINER_OUTPUTS: str = "outputs"
    
    # Conversion Settings
    DEFAULT_DPI: int = 150
    DEFAULT_QUALITY: int = 85
    MAX_FILE_SIZE_MB: int = 100
    CONVERSION_TIMEOUT: int = 300
    
    # Worker Configuration
    WORKER_COUNT: int = 2
    MAX_CONCURRENT_WORKERS: int = 4
    WORKER_CHECK_INTERVAL: float = 0.5
    CPU_THRESHOLD: float = 95.0
    MEMORY_THRESHOLD: float = 95.0
    MAX_CPU_PERCENT: float = 95.0
    MAX_RAM_PERCENT: float = 95.0
    JOB_TIMEOUT: int = 1800
    CLEANUP_INTERVAL: int = 3600
    
    # Queue Configuration
    QUEUE_NAME: str = "conversion_jobs"
    JOB_EXPIRY: int = 86400
    MAX_RETRIES: int = 3
    
    # --- FILE PATHS (FIXED) ---
    # Now using the global BASE_DIR variable
    TEMP_DIR: str = os.path.join(BASE_DIR, "temp")
    
    # [NEW] DATA DIR for Persistent Stats (Won't be deleted by cleanup)
    DATA_DIR: str = os.path.join(BASE_DIR, "data")
    
    LIBREOFFICE_PATH: str = "soffice" if os.name == 'nt' else "/usr/bin/libreoffice"
    
    # Logging
    LOG_LEVEL: str = "INFO"

    # =========================================================
    # [NEW] DASHBOARD & SECURITY SETTINGS
    # =========================================================
    # URL eka: convertsoon.com/secure-admin-panel (Change this in .env)
    ADMIN_SECRET_URL: str = "secure-admin-panel"  
    
    # Login Credentials (Change these in .env!)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "Chathu@941217"
    
    # Stats Database File Name
    STATS_DB_NAME: str = "stats.db"

    @property
    def redis_connection_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    @property
    def stats_db_path(self) -> str:
        """Returns full path to stats database"""
        return os.path.join(self.DATA_DIR, self.STATS_DB_NAME)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

# Update legacy container names
settings.AZURE_STORAGE_CONTAINER_UPLOADS = settings.AZURE_UPLOAD_CONTAINER
settings.AZURE_STORAGE_CONTAINER_OUTPUTS = settings.AZURE_OUTPUT_CONTAINER

# Ensure Data Directory Exists
os.makedirs(settings.DATA_DIR, exist_ok=True)
