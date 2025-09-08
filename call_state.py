"""
Call state management for tracking call metadata and state.
Simple in-memory implementation - replace with DynamoDB for production.
"""
from typing import Dict, Optional, List
from datetime import datetime
import asyncio
import json

from loguru import logger


class CallStateManager:
    """Manages call state and metadata"""
    
    def __init__(self):
        # In-memory storage - replace with DynamoDB for production
        self.calls: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()
    
    def create_call(self, call_id: str, metadata: Dict) -> Dict:
        """Create a new call record"""
        call_data = {
            "call_id": call_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "status": "initiated",
            **metadata
        }
        
        self.calls[call_id] = call_data
        logger.info(f"Created call record: {call_id}")
        
        return call_data
    
    def get_call(self, call_id: str) -> Optional[Dict]:
        """Get call record by ID"""
        return self.calls.get(call_id)
    
    def update_call(self, call_id: str, updates: Dict) -> bool:
        """Update call record"""
        if call_id not in self.calls:
            logger.warning(f"Call {call_id} not found for update")
            return False
        
        self.calls[call_id].update({
            **updates,
            "updated_at": datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Updated call {call_id}: {updates}")
        return True
    
    def list_active_calls(self) -> List[Dict]:
        """List all active (non-completed) calls"""
        active_calls = [
            call for call in self.calls.values()
            if call.get("status") not in ["completed", "failed", "cancelled"]
        ]
        return active_calls
    
    def delete_call(self, call_id: str) -> bool:
        """Delete call record (for cleanup)"""
        if call_id in self.calls:
            del self.calls[call_id]
            logger.info(f"Deleted call record: {call_id}")
            return True
        return False
    
    def get_metrics(self) -> Dict:
        """Get call metrics"""
        total_calls = len(self.calls)
        active_calls = len(self.list_active_calls())
        completed_calls = len([
            c for c in self.calls.values() 
            if c.get("status") == "completed"
        ])
        
        return {
            "total_calls": total_calls,
            "active_calls": active_calls,
            "completed_calls": completed_calls,
        }
