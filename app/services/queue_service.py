"""
Queue Service - Redis Job Queue Management
Fast FIFO queue for conversion jobs
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)


class QueueService:
    """Redis-based job queue with fast processing"""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.queue_key = f"{settings.QUEUE_NAME}:pending"
        self.processing_key = f"{settings.QUEUE_NAME}:processing"
    
    async def connect(self) -> None:
        """Connect to Redis"""
        try:
            self.redis = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True
            )
            await self.redis.ping()
            logger.info(f"Redis connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from Redis"""
        if self.redis:
            try:
                await self.redis.close()
                logger.info("Redis disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting from Redis: {e}")
            finally:
                self.redis = None
    
    async def health_check(self) -> bool:
        """Check Redis health"""
        try:
            if self.redis:
                await self.redis.ping()
                return True
            return False
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    async def enqueue_job(self, job_data: Dict[str, Any]) -> str:
        """Add job to queue"""
        job_id = job_data["job_id"]
        
        # Store job data
        job_key = f"job:{job_id}"
        await self.redis.hset(job_key, mapping={
            "data": json.dumps(job_data),
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        await self.redis.expire(job_key, settings.JOB_EXPIRY)
        
        # Add to queue
        await self.redis.rpush(self.queue_key, job_id)
        
        logger.info(f"Job queued: {job_id}")
        return job_id
    
    async def dequeue_job(self) -> Optional[Dict[str, Any]]:
        """Get next job from queue (FIFO)"""
        try:
            # Pop from queue
            job_id = await self.redis.lpop(self.queue_key)
            if not job_id:
                return None
            
            job_key = f"job:{job_id}"
            
            # Get job data
            job_data_str = await self.redis.hget(job_key, "data")
            if not job_data_str:
                logger.warning(f"Job data not found: {job_id}")
                return None
            
            # Mark as processing
            await self.redis.hset(job_key, "status", "processing")
            await self.redis.sadd(self.processing_key, job_id)
            
            return json.loads(job_data_str)
            
        except Exception as e:
            logger.error(f"Dequeue error: {e}")
            return None
    
    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status and data"""
        job_key = f"job:{job_id}"
        
        try:
            data = await self.redis.hgetall(job_key)
            if not data:
                return None
            
            result = {"job_id": job_id, "status": data.get("status", "unknown")}
            
            if "data" in data:
                job_data = json.loads(data["data"])
                result.update({
                    "original_filename": job_data.get("original_filename"),
                    "output_format": job_data.get("output_format"),
                    "created_at": job_data.get("created_at"),
                    "input_blob_name": job_data.get("input_blob_name"),
                    "input_size": job_data.get("input_size", 0),
                    "options": job_data.get("options", {})
                })
            
            # Add completion data if available
            for key in ["output_blob_name", "output_blob_url", "output_filename", 
                       "completed_at", "error", "progress", "output_size", "input_size"]:
                if key in data:
                    result[key] = data[key]
            
            # Get queue position if queued
            if result["status"] == "queued":
                position = await self._get_queue_position(job_id)
                result["queue_position"] = position
            
            return result
            
        except Exception as e:
            logger.error(f"Get status error: {e}")
            return None
    
    async def update_job_status(self, job_id: str, status: str, **kwargs) -> None:
        """Update job status and metadata"""
        job_key = f"job:{job_id}"
        
        updates = {"status": status}
        for key, value in kwargs.items():
            if value is not None:
                updates[key] = str(value) if not isinstance(value, str) else value
        
        await self.redis.hset(job_key, mapping=updates)
        
        # Remove from processing set if completed/failed
        if status in ["completed", "failed"]:
            await self.redis.srem(self.processing_key, job_id)
        
        logger.info(f"Job {job_id} status: {status}")
    
    async def delete_job(self, job_id: str) -> None:
        """Delete job from Redis"""
        job_key = f"job:{job_id}"
        await self.redis.delete(job_key)
        await self.redis.srem(self.processing_key, job_id)
        logger.info(f"Job deleted: {job_id}")
    
    async def _get_queue_position(self, job_id: str) -> int:
        """Get position in queue"""
        try:
            queue = await self.redis.lrange(self.queue_key, 0, -1)
            if job_id in queue:
                return queue.index(job_id) + 1
            return 0
        except:
            return 0
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        try:
            if not self.redis:
                return {"queue_length": 0, "processing_count": 0, "status": "disconnected"}
            
            queue_length = await self.redis.llen(self.queue_key)
            processing_count = await self.redis.scard(self.processing_key)
            
            return {
                "queue_length": queue_length,
                "processing_count": processing_count,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Stats error: {e}")
            return {"queue_length": 0, "processing_count": 0, "error": str(e)}
    
    async def clear_all(self) -> None:
        """Clear all jobs (for testing)"""
        await self.redis.delete(self.queue_key)
        await self.redis.delete(self.processing_key)
        
        # Delete all job keys
        keys = await self.redis.keys("job:*")
        if keys:
            await self.redis.delete(*keys)
        
        logger.info("Queue cleared")
