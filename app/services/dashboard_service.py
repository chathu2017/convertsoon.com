"""
Dashboard Service - System Monitoring & Analytics
Handles persistent stats (SQLite), live system health (psutil), logs, and visitor mapping.
"""

import os
import sqlite3
import logging
import psutil
import time
import re
import geoip2.database
from datetime import datetime, timedelta, timezone
from collections import deque
from typing import Dict, List, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)

class DashboardService:
    def __init__(self):
        # Database Path from Settings
        self.db_path = settings.stats_db_path
        self._init_db()

    def _get_connection(self):
        """Creates a database connection with row factory"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10) # Increased timeout for concurrency
        conn.row_factory = sqlite3.Row
        # [UPGRADE] Enable WAL Mode for high concurrency (4 Workers safe)
        conn.execute("PRAGMA journal_mode=WAL;") 
        return conn

    def _init_db(self):
        """Initializes the SQLite database schema if not exists"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Job History Table (Conversion Stats)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS job_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT,
                        job_type TEXT, -- e.g., 'image-convert', 'pdf-merge', 'pdf-split'
                        status TEXT,   -- 'completed', 'failed'
                        input_size INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Index for faster date-range queries
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON job_history(created_at)")

                # 2. Server Stats Table (CPU/RAM History)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS server_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cpu REAL,
                        ram REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # 3. Visitors Table (New Feature for Daily/Weekly/Monthly Stats)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS visitors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip TEXT,
                        country_code TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_visit_date ON visitors(created_at)")
                
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to init stats DB: {e}")

    # =========================================================
    # 1. LOGGING (WRITE DATA)
    # =========================================================
    def log_job_completion(self, job_id: str, job_type: str, status: str, input_size: int = 0):
        """
        Logs a finished job to the database.
        Safe method: Won't crash the app if DB fails.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO job_history (job_id, job_type, status, input_size, created_at) VALUES (?, ?, ?, ?, ?)",
                    (job_id, job_type, status, input_size, datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log job stats: {e}")

    def log_server_health(self):
        """Saves current CPU/RAM snapshot to DB"""
        try:
            health = self.get_system_health()
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO server_stats (cpu, ram, created_at) VALUES (?, ?, ?)",
                    (health['cpu_percent'], health['ram_percent'], datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Health Log Error: {e}")

    # =========================================================
    # 2. VISITOR TRACKING & PERIODS [NEW UPGRADE]
    # =========================================================
    def record_visitor(self, ip, country_code):
        """Saves visitor to DB if not visited in last 1 hour (Unique Session)"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Check recent visit to prevent duplicates within 1 hour
                one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                
                cursor.execute("SELECT id FROM visitors WHERE ip = ? AND created_at >= ?", (ip, one_hour_ago))
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO visitors (ip, country_code, created_at) VALUES (?, ?, ?)", 
                        (ip, country_code, datetime.now(timezone.utc).isoformat())
                    )
                    conn.commit()
        except Exception as e:
            # Silent fail to ensure main thread continues
            pass

    def get_visitor_periods(self):
        """Returns counts for Daily, Weekly, Monthly visitors from DB"""
        try:
            now = datetime.now(timezone.utc)
            ranges = {
                "daily": now - timedelta(days=1),
                "weekly": now - timedelta(days=7),
                "monthly": now - timedelta(days=30)
            }
            stats = {}
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for key, start_date in ranges.items():
                    # Count distinct IPs for the period
                    cursor.execute(
                        "SELECT COUNT(DISTINCT ip) FROM visitors WHERE created_at >= ?", 
                        (start_date.isoformat(),)
                    )
                    stats[key] = cursor.fetchone()[0]
            return stats
        except Exception:
            return {"daily": 0, "weekly": 0, "monthly": 0}

    # =========================================================
    # 3. SYSTEM HEALTH (LIVE & HISTORY)
    # =========================================================
    def get_system_health(self) -> Dict[str, Any]:
        """Returns real-time server resource usage"""
        try:
            # CPU
            cpu_usage = psutil.cpu_percent(interval=None)
            
            # RAM
            mem = psutil.virtual_memory()
            ram_usage = mem.percent
            ram_total_gb = round(mem.total / (1024**3), 2)
            ram_used_gb = round(mem.used / (1024**3), 2)

            # Disk
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent

            return {
                "cpu_percent": cpu_usage,
                "ram_percent": ram_usage,
                "ram_detail": f"{ram_used_gb}GB / {ram_total_gb}GB",
                "disk_percent": disk_usage,
                "status": "healthy" if cpu_usage < 90 and ram_usage < 90 else "critical"
            }
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return {"status": "error", "detail": str(e)}

    def get_health_history(self, days=7):
        """Gets CPU/RAM stats for charts (Hourly Average)"""
        try:
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            with self._get_connection() as conn:
                # Get average per hour to reduce data points
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT strftime('%Y-%m-%d %H:00', created_at) as hour, 
                           AVG(cpu), AVG(ram) 
                    FROM server_stats 
                    WHERE created_at >= ? 
                    GROUP BY hour 
                    ORDER BY hour ASC
                """, (start_date,))
                rows = cursor.fetchall()
                return {
                    "labels": [r[0] for r in rows],
                    "cpu": [round(r[1], 1) for r in rows],
                    "ram": [round(r[2], 1) for r in rows]
                }
        except Exception as e:
            return {"error": str(e)}

    # =========================================================
    # 4. SERVER LOGS (PREMIUM SMART FILTERING)
    # =========================================================
    def get_server_logs(self, source: str = "web", limit: int = 100) -> List[str]:
        """
        Reads logs from specific source (web, worker-1, etc).
        Smart Filters applied to remove noise:
        - Dashboard Polling (/api/...)
        - Static Files
        - Localhost Health Pings (127.0.0.1 GET /)
        - Azure/Cloud Monitoring
        """
        # [UPGRADE] Select correct log file based on source
        if source == "web":
            log_file = "/var/www/ConvertSoon/logs/web.log"
        elif source.startswith("worker-"):
            safe_name = os.path.basename(source)
            log_file = f"/var/www/ConvertSoon/logs/{safe_name}.log"
        else:
            log_file = "/var/www/ConvertSoon/logs/web.log"

        if not os.path.exists(log_file):
            return [f"Log file not found: {source} ({log_file})"]

        try:
            filtered_logs = []
            # Read last 2000 lines to find relevant ones
            with open(log_file, 'r') as f:
                lines = deque(f, 2000) 
            
            for line in lines:
                # 1. Dashboard Polling (Noise from the dashboard updating itself)
                if "/api/health" in line or "/api/stats" in line or "/api/logs" in line:
                    continue
                
                # 2. Static Files & Assets
                if "GET /static" in line or "GET /favicon.ico" in line:
                    continue

                # 3. Localhost Health Pings (Internal Traffic)
                # Removes lines like: 127.0.0.1:49750 - "GET / HTTP/1.1" 200
                if "127.0.0.1" in line and "GET / HTTP/1.1" in line:
                    continue

                # 4. External Monitoring (Azure/Cloud)
                if "Azure Traffic Manager" in line:
                    continue

                # 5. Clean up & Keep valid lines
                clean_line = line.strip()
                if clean_line:
                    filtered_logs.append(clean_line)

            # Return only the last 'limit' amount
            return filtered_logs[-limit:]
            
        except Exception as e:
            return [f"Error reading logs: {str(e)}"]

    # =========================================================
    # 5. VISITOR MAP DATA (CAPACITY UPGRADED TO 5000)
    # =========================================================
    def get_visitor_map_data(self) -> Dict[str, int]:
        """
        Parses NGINX logs to map visitor IPs to Countries using GeoLite2.
        Reads last 5000 lines to ensure real users aren't pushed out by API noise.
        """
        # [CHANGE] Nginx Access Log path
        log_file = "/var/log/nginx/access.log"
        db_path = "/var/www/ConvertSoon/geo-location/GeoLite2-Country.mmdb" 
        
        country_counts = {}

        if not os.path.exists(db_path):
            logger.warning("GeoIP DB not found")
            return {} 

        if not os.path.exists(log_file):
            return {} 

        try:
            reader = geoip2.database.Reader(db_path)
            
            # Regex to capture IP at the start of the line
            ip_pattern = re.compile(r'^([0-9a-fA-F:.]+)\s')

            try:
                with open(log_file, 'r') as f:
                    # [UPGRADE] Increased to 5000 lines to catch real users amidst noise
                    lines = deque(f, 5000)
                
                for line in lines:
                    # [OPTIMIZATION] Skip known noise BEFORE regex to save CPU
                    if "Azure Traffic Manager" in line or "/api/" in line or "/static/" in line:
                        continue

                    match = ip_pattern.search(line)
                    if match:
                        ip = match.group(1)
                        ip = ip.strip("[]")

                        # Ignore Localhost & Private IPs
                        if ip == "127.0.0.1" or ip == "::1" or ip.startswith("10.") or ip.startswith("192.168."): 
                            continue

                        try:
                            response = reader.country(ip)
                            code = response.country.iso_code
                            if code:
                                country_counts[code] = country_counts.get(code, 0) + 1
                                self.record_visitor(ip, code)
                        except Exception:
                            continue # Private IP or GeoIP lookup failed
            
            except PermissionError:
                logger.error(f"Permission Denied: Cannot read {log_file}. Check 'adm' group.")
                return {}
                
            reader.close()
            return country_counts

        except Exception as e:
            logger.error(f"Map Data Error: {e}")
            return {}

    # =========================================================
    # 6. DASHBOARD ANALYTICS (CHARTS)
    # =========================================================
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Aggregates data for the dashboard charts"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # --- A. Summary Counts ---
                # Today
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
                cursor.execute("SELECT COUNT(*) FROM job_history WHERE created_at >= ?", (today_start,))
                jobs_today = cursor.fetchone()[0]

                # --- Calculate Last 30 Days Count ---
                thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                cursor.execute("SELECT COUNT(*) FROM job_history WHERE created_at >= ?", (thirty_days_ago,))
                total_jobs = cursor.fetchone()[0]

                # Success vs Failed (Last 24h)
                cursor.execute("""
                    SELECT status, COUNT(*) FROM job_history 
                    WHERE created_at >= ? GROUP BY status
                """, (today_start,))
                status_rows = cursor.fetchall()
                status_counts = {row[0]: row[1] for row in status_rows}

                # --- B. Daily Trend (Last 7 Days) for Chart ---
                seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                cursor.execute("""
                    SELECT date(created_at), COUNT(*) 
                    FROM job_history 
                    WHERE created_at >= ? 
                    GROUP BY date(created_at) 
                    ORDER BY date(created_at) ASC
                """, (seven_days_ago,))
                trend_rows = cursor.fetchall()
                
                trend_labels = [row[0] for row in trend_rows]
                trend_data = [row[1] for row in trend_rows]

                # --- C. Job Type Distribution (Top 5) ---
                cursor.execute("""
                    SELECT job_type, COUNT(*) as cnt 
                    FROM job_history 
                    GROUP BY job_type 
                    ORDER BY cnt DESC 
                    LIMIT 5
                """)
                type_rows = cursor.fetchall()
                type_dist = [{"name": r[0], "count": r[1]} for r in type_rows]

                # --- D. Get Map & Visitor Data [NEW] ---
                map_data = self.get_visitor_map_data() # This triggers DB recording
                visitor_periods = self.get_visitor_periods() # Fetches DB stats

                return {
                    "summary": {
                        "today": jobs_today,
                        "total": total_jobs,
                        "success": status_counts.get("completed", 0),
                        "failed": status_counts.get("failed", 0)
                    },
                    "charts": {
                        "trend_labels": trend_labels,
                        "trend_data": trend_data,
                        "type_distribution": type_dist,
                        "map_data": map_data,
                        "visitor_periods": visitor_periods # Sent to frontend
                    }
                }

        except Exception as e:
            logger.error(f"Stats Aggregation Error: {e}")
            return {"error": str(e)}

# Create singleton instance
dashboard_service = DashboardService()