import os
import shutil
import asyncio
from pydantic import BaseModel
from typing import Optional
from messaging_manager.service_mappers.telegram import TelegramServiceMapper
from messaging_manager.libs.common import call_ollama_chat, Message, call_ollama_vision, ToolSchema
import json
from messaging_manager.libs.service_mapper_interface import ServiceMapperInterface, UnifiedMessageFormat
from sqlmodel import create_engine, Session, SQLModel, select

def get_system_prompt():
    # TODO: add in extra context, like user name and profile
    return """You will be provided recent messages between User A and User B, your task is to determine if User A needs to respond next in the conversation and if so draft an appropriate response.
    If you determine that User A does not need to respond, set the response_needed to False."""

class DraftResponse(BaseModel):
    thoughts: str
    summary_of_chat: str
    reasoning_for_decision: str
    response_needed: bool
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


async def pull_latest_messages(db_engine, service_mappers: list[ServiceMapperInterface]):
    latest_messages = []
    service_metadata = {}
    with Session(db_engine) as session:
        for service_mapper in service_mappers:
            if not await service_mapper.is_logged_in():
                await service_mapper.login()
            
            metadata = await service_mapper.get_service_metadata()
            service_metadata[metadata.service_name] = metadata

            # get the latest message from the database
            latest_message = session.exec(select(UnifiedMessageFormat)
                                          .where(UnifiedMessageFormat.service_name == metadata.service_name)
                                          .order_by(UnifiedMessageFormat.message_timestamp.desc())).first()

            latest_messages.extend(await service_mapper.get_new_messages(latest_message, limit_per_source=25))
            await service_mapper.logout()
        
        session.add_all(latest_messages)
        session.commit()
    return latest_messages
    

async def pull_loop(db_engine):
    import dotenv
    dotenv.load_dotenv()
    server_url = os.getenv("OLLAMA_SERVER_URL")
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_key = "session one"

    media_dir = "media"

    mappers = [
        TelegramServiceMapper(
            init_keys={"api_id": api_id, 
                       "api_hash": api_hash, 
                       "latest_message_id": 0, 
                       "session_name": session_key},
            media_dir=media_dir
        )
    ]
    
    await pull_latest_messages(db_engine, mappers)
    
    

async def main_old():
    import dotenv
    dotenv.load_dotenv()
    server_url = os.getenv("OLLAMA_SERVER_URL")
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_key = "session one"

    media_dir = "media"
    if os.path.exists(media_dir):
        shutil.rmtree(media_dir)
    os.makedirs(media_dir)

    service_mapper = TelegramServiceMapper(
        init_keys={"api_id": api_id, 
                   "api_hash": api_hash,
                   "latest_message_id": 0,
                   "session_name": session_key},
        media_dir=media_dir
    )

    await service_mapper.login()
    is_logged_in = await service_mapper.is_logged_in()

    message_limit = 25

    new_messages = await service_mapper.get_new_messages(limit_per_source=message_limit)

    print(await service_mapper.get_service_metadata())
    for message in new_messages:
        print("~" * 100)
        print(message.model_dump_json(indent=4))

    # group messages by source ID
    messages_by_source_id = {}
    for message in new_messages:
        if message.source_id not in messages_by_source_id:
            messages_by_source_id[message.source_id] = []
        messages_by_source_id[message.source_id].append(message)

    system_prompt = get_system_prompt()


    for source_id, messages in messages_by_source_id.items():        
        user_prompt = """Please determine if User A needs to respond next in the conversion and if so draft an appropriate response.
        If you determine that User A does not need to respond, set the response_needed to False.
        
"""
        
        file_paths = []

        print("~" * 100)
        print(f"Number of messages: {len(messages)}")
        print("~" * 100)

        for message in messages:
            file_paths = []
            # TODO add time as "minutes ago" "hours ago" "days ago" etc
            # TODO add media to the prompt
            user_name = "User A"
            if message.sender_name != "user":
                user_name = "User B"
            
            user_prompt += f"{user_name}: {message.message_content}\n"
            
            for file_path in message.file_paths:
                file_paths.append(file_path)
                caption = get_contextual_caption(server_url, file_path, user_prompt)
                user_prompt += f"{user_name}: shared an image. Description: [{caption}]\n"
                

        user_prompt += f"\nPlease respond with the following JSON format: \n{DraftResponse.model_json_schema()}"

        ollama_messages = [Message(role="system", content=system_prompt)]
        print("~" * 100)
        print("user prompt:")
        print(user_prompt)
        print("~" * 100)
        # call ollama chat        
        ollama_messages.append(Message(role="user", content=user_prompt))

        response = call_ollama_chat(server_url, "Qwen2.5-14B-Instruct-1M-GGUF", ollama_messages, json_schema=DraftResponse.model_json_schema())
        draft_response = DraftResponse.model_validate_json(response)
        print("~")
        for m in ollama_messages:
            print(json.dumps(m.chat_ml(), indent=4))
        print("~" * 100)
        print(draft_response)
        print("~" * 100)
        if draft_response.response_needed:
            print("suggested response:")
            print(draft_response.response)
        else:
            print("No response needed")

        print("~" * 100)

# todo: embed the messages and the response
# todo: save the embedding to a vector database
# todo: call vector database for more context
    
    

if __name__ == "__main__":
    media_dir = "media"
    if os.path.exists(media_dir):
        shutil.rmtree(media_dir)
    os.makedirs(media_dir)

    # delete the messages.db file
    if os.path.exists("messages.db"):
        os.remove("messages.db")

    engine = create_engine("sqlite:///messages.db")
    SQLModel.metadata.create_all(engine)
    
    asyncio.run(pull_loop(engine))

    # get message count from sqlite db
    with Session(engine) as session:
        messages = select(UnifiedMessageFormat)
        message_count = session.exec(messages).all()
        print(f"Message count: {len(message_count)}")

    asyncio.run(pull_loop(engine))

    with Session(engine) as session:
        messages = select(UnifiedMessageFormat)
        message_count = session.exec(messages).all()
        print(f"Message count: {len(message_count)}")