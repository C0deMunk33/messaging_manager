import uuid
from typing import Optional, Dict, List
from sqlmodel import Field, SQLModel, Column, JSON
from datetime import datetime
import json



class UnifiedMessageFormat(SQLModel, table=True):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    service_name: str # the name of the service that the message is from
    source_id: str # the id of the source, this is a hash of the source_keys
    source_keys: Dict[str, str] | None = Field(default={}, sa_column=Column(JSON)) # all the keys that are needed to identify the message, channel, guild, etc.
    message_content: Optional[str] = Field(default=None) # the content of the message
    sender_id: str # the id of the sender
    sender_name: str # the name of the sender at time of retrieval
    message_timestamp: datetime # the timestamp of the message
    file_paths: List[str] | None = Field(default=[], sa_column=Column(JSON)) # the paths to the files in the message


class DraftResponse(SQLModel, table=True):
    draft_response_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    messages: List[UnifiedMessageFormat] = Field(sa_column=Column(JSON))
    thoughts: str
    summary_of_chat: str
    reasoning_for_decision: str
    response_suggested: bool
    response: Optional[str] = None
    status: str


class ServiceMetadata(SQLModel, table=True):
    service_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    service_name: str # the name of the service
    init_keys: List[str] | None = Field(default=[], sa_column=Column(JSON)) # the keys that are needed to initialize the service
