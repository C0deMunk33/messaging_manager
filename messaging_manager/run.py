import os
import shutil
import asyncio
from pydantic import BaseModel
from typing import Optional
from messaging_manager.service_mappers.telegram import TelegramServiceMapper
from messaging_manager.service_mappers.gmail import GmailServiceMapper
from messaging_manager.libs.common import call_ollama_chat, Message, call_ollama_vision, ToolSchema
import json
from messaging_manager.libs.service_mapper_interface import ServiceMapperInterface
from datetime import datetime, timedelta
from sqlmodel import create_engine, Session, SQLModel, select
import uuid
from typing import List
from sqlmodel import Field,  Column, JSON
import hashlib
from messaging_manager.libs.database_models import DraftResponse, UnifiedMessageFormat, ServiceMetadata

def get_system_prompt():
    # TODO: add in extra context, like user name and profile
    return """You will be provided recent messages between User A and User B, your task is to determine if User A needs to respond next in the conversation and if so draft an appropriate response.
    If you determine that User A does not need to respond, set the response_suggested to False."""

class DraftResponseSchema(BaseModel):
    thoughts: str
    summary_of_chat: str
    reasoning_for_decision: str
    response_suggested: bool
    response: Optional[str] = None

class ContextualCaption(BaseModel):
    thoughts: str
    reasoning: str
    detailed_description: str
    context: str
    final_description: str


def get_contextual_caption(server_url, image_path, chat_context):
    # TODO call vision model to get a description of the image in context
    context_system_prompt = """Your task is to accurately and comprehensively describe the image. Use the chat context to help you describe the image and how it relates to the chat."""
    context_user_prompt = f"""Chat context: 
    {chat_context}
    
    Please respond with the following JSON format:
    {ContextualCaption.model_json_schema()}"""

    ollama_messages = [Message(role="system", content=context_system_prompt)]
    ollama_messages.append(Message(
        role="user",
        images=[image_path],
        content=context_user_prompt
    ))
    response = call_ollama_vision(server_url, "llava:34b", ollama_messages, json_schema=ContextualCaption.model_json_schema())
    parsed_response = ContextualCaption.model_validate_json(response)

    print("~" * 100)
    print("image description:")
    print(parsed_response.model_dump_json(indent=4))
    print("~" * 100)
    return parsed_response.final_description



    
class LoopManager:
    def __init__(self, db_engine, media_dir):
        import dotenv
        dotenv.load_dotenv()
        self.server_url = os.getenv("OLLAMA_SERVER_URL")
        api_id = os.getenv("TELEGRAM_API_ID")
        api_hash = os.getenv("TELEGRAM_API_HASH")

        email_address = os.getenv("GMAIL_EMAIL")
        password = os.getenv("GMAIL_PASSWORD")
        gmail_credentials_file_path = os.getenv("GMAIL_CREDENTIALS_FILE_PATH")
        session_key = "session one"

        self.media_dir = media_dir
    
        self.db_engine = db_engine
        self.service_mappers = [
            GmailServiceMapper(
                init_keys={"email": email_address, 
                        "password": password,
                        "credentials_file_path": gmail_credentials_file_path,
                        "latest_message_timestamp": datetime.now() - timedelta(days=30)},
                media_dir=media_dir
            )            
        ]

        """
        TelegramServiceMapper(
            init_keys={"api_id": api_id, 
                    "api_hash": api_hash, 
                    "latest_message_id": 0, 
                    "session_name": session_key},
            media_dir=media_dir
        ),"""
  
    def add_service_mapper(self, service_mapper: ServiceMapperInterface):
        self.service_mappers.append(service_mapper)
               
    async def pull_latest_messages(self):
        latest_messages = []
        service_metadata = {}
        with Session(self.db_engine) as session:
            for service_mapper in self.service_mappers:
                if not await service_mapper.is_logged_in():
                    await service_mapper.login()
                
                metadata = await service_mapper.get_service_metadata()
                service_metadata[metadata.service_name] = metadata

                # get the latest message from the database
                latest_message = session.exec(select(UnifiedMessageFormat)
                                            .where(UnifiedMessageFormat.service_name == metadata.service_name)
                                            .order_by(UnifiedMessageFormat.message_timestamp.desc())).first()

                latest_messages.extend(await service_mapper.get_new_messages(latest_message, limit_per_source=40))
                await service_mapper.logout()
            
            # get the messages from all the message ids
            message_ids = [message.message_id for message in latest_messages]
            existing_messages = session.exec(select(UnifiedMessageFormat)
                                            .where(UnifiedMessageFormat.message_id.in_(message_ids))).all()
            existing_message_ids = [message.message_id for message in existing_messages]
            # NOTE: this will only add new messages to the database, it will not update the latest message id for the service mapper
            latest_messages = [message for message in latest_messages if message.message_id not in existing_message_ids]
            
            session.add_all(latest_messages)
            session.commit()
        return latest_messages
    
    async def process_messages(self):
        # get all messages, group by source ID, limited to 40 messages per source
        with Session(self.db_engine) as session:
            all_messages = select(UnifiedMessageFormat)
            all_messages = session.exec(all_messages).all()
            messages_by_source_id = {}
            for message in all_messages:
                if message.source_id not in messages_by_source_id:
                    messages_by_source_id[message.source_id] = []
                messages_by_source_id[message.source_id].append(message)
                if len(messages_by_source_id[message.source_id]) > 40:
                    messages_by_source_id[message.source_id].pop(0)
            
            

            for source_id, messages in messages_by_source_id.items():
                # sha256 hash the message ids
                message_ids = [message.message_id for message in messages]
                message_ids_hash = hashlib.sha256(json.dumps(message_ids).encode()).hexdigest()

                # check if the draft response already exists, if the messages havent changed, we can skip the draft response
                draft_response = session.exec(select(DraftResponse)
                                            .where(DraftResponse.draft_response_id == message_ids_hash)).first()
                if draft_response:
                    print("Draft response already exists")
                    continue

                system_prompt = get_system_prompt()
                user_prompt = """Please determine if User A needs to respond next in the conversion and if so draft an appropriate response.
                If you determine that User A does not need to respond, set the response_needed to False.
                """

                # TODO: pull in writing samples from stored messages

                file_paths = []
                for message in messages:
                    # TODO add time as "minutes ago" "hours ago" "days ago" etc
                    # TODO add media to the prompt
                    user_name = "User A"
                    if message.sender_name != "user":
                        user_name = "User B"
                    
                    user_prompt += f"{user_name}: {message.message_content}\n"
                    
                    image_extensions = [".jpg", ".png", ".JPG", ".PNG", ".jpeg", ".JPEG"]

                    for file_path in message.file_paths:
                        file_paths.append(file_path)
                        if any(file_path.endswith(ext) for ext in image_extensions):    
                            caption = get_contextual_caption(self.server_url, file_path, user_prompt)
                            user_prompt += f"{user_name}: shared an image. Description: [{caption}]\n"
                        elif file_path.endswith(".txt"):
                            with open(file_path, "r") as f:
                                user_prompt += f"{user_name}: shared a file. File content: [{f.read()}]\n"
                        elif file_path.endswith(".mp4"):
                            pass
                        else:
                            user_prompt += f"{user_name}: shared file: [{file_path}]\n"
                    
                user_prompt += f"\nPlease respond with the following JSON format: \n{DraftResponseSchema.model_json_schema()}"

                ollama_messages = [Message(role="system", content=system_prompt)]
                ollama_messages.append(Message(role="user", content=user_prompt))

                response = call_ollama_chat(self.server_url, "Qwen2.5-14B-Instruct-1M-GGUF", ollama_messages, json_schema=DraftResponseSchema.model_json_schema())
                parsed_draft_response = DraftResponseSchema.model_validate_json(response)    


                

                draft_response = DraftResponse(
                    draft_response_id=message_ids_hash,
                    messages=[message.model_dump(mode="json") for message in messages],
                    thoughts=parsed_draft_response.thoughts,
                    summary_of_chat=parsed_draft_response.summary_of_chat,
                    reasoning_for_decision=parsed_draft_response.reasoning_for_decision,
                    response_suggested=parsed_draft_response.response_suggested,
                    response=parsed_draft_response.response,
                    # pending if reponse is needed, ignored if not
                    status="pending" if parsed_draft_response.response_suggested else "ignored"
                )
                print("~" * 100)
                print("draft response:")
                print(draft_response.model_dump_json(indent=4))
                print("~" * 100)
                session.add(draft_response)
                session.commit()
    
    async def send_approved_response(self, draft_response_id: str, response_text: str):
        """Send an approved response through the appropriate service mapper"""

        with Session(self.db_engine) as session:
            draft_response = session.exec(select(DraftResponse).where(
                DraftResponse.draft_response_id == draft_response_id)).first()
            
            if not draft_response:
                return {"success": False, "message": "Draft response not found"}
            
            # Get the first message to determine which service to use
            if not draft_response.messages:
                return {"success": False, "message": "No messages found in draft response"}
            
            # Parse the first message to get service details
            first_message = UnifiedMessageFormat.model_validate(draft_response.messages[0])
            service_name = first_message.service_name
            source_id = first_message.source_id
            
            # Find the appropriate service mapper
            service_mapper = None
            for mapper in self.service_mappers:
                metadata = await mapper.get_service_metadata()
                if metadata.service_name == service_name:
                    service_mapper = mapper
                    break
            
            if not service_mapper:
                return {"success": False, "message": f"Service mapper for {service_name} not found"}
            
            # Login to the service
            if not await service_mapper.is_logged_in():
                await service_mapper.login()
            
            # Send the message
            try:
                # reply_to_message(self, message: UnifiedMessageFormat, reply_content: str) -> str:
                # should be the last message in the draft response
                last_message = UnifiedMessageFormat.model_validate(draft_response.messages[-1])
                result = await service_mapper.reply_to_message(last_message, response_text)
                
                # Update the draft response status
                draft_response.status = "sent"
                draft_response.response = response_text
                session.add(draft_response)
                session.commit()
                
                await service_mapper.logout()
                return {"success": True, "message": "Response sent successfully"}
            except Exception as e:
                await service_mapper.logout()
                return {"success": False, "message": f"Failed to send message: {str(e)}"}

# todo: embed the messages and the response
# todo: save the embedding to a vector database
# todo: call vector database for more context

async def pull_loop(engine, loop_manager: LoopManager):
    await loop_manager.pull_latest_messages()

# Create a global instance of LoopManager
def get_loop_manager():
    media_dir = "media"
    if not os.path.exists(media_dir):
        os.makedirs(media_dir)
    
    engine = create_engine("sqlite:///messages.db")
    SQLModel.metadata.create_all(engine)
    
    return LoopManager(engine, media_dir)

# Global instance for server use
loop_manager = None

async def run_continuous_loop(interval_seconds=300):
    """Run the message processing loop continuously with a specified interval"""
    engine = create_engine("sqlite:///messages.db")
    SQLModel.metadata.create_all(engine)
    
    loop_manager = LoopManager(engine, "media")
    
    while True:
        try:
            print(f"Running message pull and processing cycle at {datetime.now()}")
            await loop_manager.pull_latest_messages()
            
            # Get message count from sqlite db
            with Session(engine) as session:
                messages = select(UnifiedMessageFormat)
                message_count = session.exec(messages).all()
                print(f"Message count: {len(message_count)}")
            
            await loop_manager.process_messages()
            print(f"Completed processing cycle, waiting {interval_seconds} seconds until next cycle")
        except Exception as e:
            print(f"Error in processing cycle: {str(e)}")
        
        # Wait for the next cycle
        await asyncio.sleep(interval_seconds)

if __name__ == "__main__":
    # Run the continuous loop
    asyncio.run(run_continuous_loop())

   