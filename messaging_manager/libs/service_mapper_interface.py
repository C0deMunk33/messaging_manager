import hashlib
import json
import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, List
from sqlmodel import Field, SQLModel, create_engine, select, Column, JSON

class UnifiedMessageFormat(SQLModel, table=True):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    service_name: str # the name of the service that the message is from
    source_id: str # the id of the source, this is a hash of the source_keys
    source_keys: Dict[str, str] | None = Field(default={}, sa_column=Column(JSON)) # all the keys that are needed to identify the message, channel, guild, etc.
    message_content: str # the content of the message
    sender_id: str # the id of the sender
    sender_name: str # the name of the sender at time of retrieval
    message_timestamp: datetime # the timestamp of the message
    file_paths: List[str] | None = Field(default=[], sa_column=Column(JSON)) # the paths to the files in the message

class ServiceMetadata(SQLModel, table=True):
    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    service_name: str # the name of the service
    init_keys: List[str] | None = Field(default=[], sa_column=Column(JSON)) # the keys that are needed to initialize the service

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