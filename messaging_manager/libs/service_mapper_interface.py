import hashlib
import json
import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, List
from sqlmodel import Field, SQLModel, create_engine, select, Column, JSON

from messaging_manager.libs.database_models import UnifiedMessageFormat, ServiceMetadata

def get_source_id(source_keys: dict[str, str]) -> str:
    # sha256 hash the source_keys
    return hashlib.sha256(json.dumps(source_keys).encode()).hexdigest()

class ServiceMapperInterface(ABC):
    @abstractmethod
    async def get_service_metadata(self) -> ServiceMetadata:
        pass
    
    @abstractmethod
    async def get_new_messages(self, latest_message: UnifiedMessageFormat) -> List[UnifiedMessageFormat]:
        """gets messages from service since last message retrieval"""
        pass

    @abstractmethod
    async def reply_to_message(self, message: UnifiedMessageFormat, reply_content: str) -> str:
        """replies to a message"""
        pass

    @abstractmethod
    async def login(self) -> bool:
        """logs in to the service"""
        pass

    @abstractmethod
    async def logout(self) -> bool:
        """logs out of the service"""
        pass

    @abstractmethod
    async def is_logged_in(self) -> bool:
        """checks if the service is logged in"""
        pass