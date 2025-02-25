import hashlib
import json
from abc import ABC, abstractmethod
from typing import List
from pydantic import BaseModel
from datetime import datetime

class UnifiedMessageFormat(BaseModel):
    message_id: str # the id of the message
    service_name: str # the name of the service that the message is from
    source_keys: dict[str, str] # all the keys that are needed to identify the message, channel, guild, etc.
    message_content: str # the content of the message
    sender_id: str # the id of the sender
    sender_name: str # the name of the sender at time of retrieval
    message_timestamp: datetime # the timestamp of the message

class ServiceMetadata(BaseModel):
    service_name: str # the name of the service
    init_keys: list[str] # the keys that are needed to initialize the service

def get_source_id(source_keys: dict[str, str]) -> str:
    # sha256 hash the source_keys
    return hashlib.sha256(json.dumps(source_keys).encode()).hexdigest()

class ServiceMapperInterface(ABC):
    @abstractmethod
    def get_service_metadata(self) -> ServiceMetadata:
        pass
    
    @abstractmethod
    def get_new_messages(self, last_message_timestamp: datetime) -> List[UnifiedMessageFormat]:
        """gets messages from service since last message retrieval"""
        pass

    @abstractmethod
    def reply_to_message(self, message: UnifiedMessageFormat, reply_content: str) -> str:
        """replies to a message"""
        pass