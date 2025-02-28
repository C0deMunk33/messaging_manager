import os
import shutil
import asyncio
from pydantic import BaseModel
from typing import Optional
from messaging_manager.service_mappers.telegram import TelegramServiceMapper
from messaging_manager.libs.common import call_ollama_chat, Message, call_ollama_vision, ToolSchema
import json
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

def get_contextual_caption(image_path, chat_context):
    # TODO call vision model to get a description of the image in context
    return "TODO"

async def main():
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
        init_keys={"api_id": api_id, "api_hash": api_hash},
        session_name=session_key,
        media_dir=media_dir
    )

    await service_mapper.login()
    is_logged_in = await service_mapper.is_logged_in()

    message_limit = 6

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
        If you determine that User A does not need to respond, set the response_needed to False."""
        
        for message in messages:
            file_paths = []
            # TODO add time as "minutes ago" "hours ago" "days ago" etc
            # TODO add media to the prompt
            if message.sender_name == "user":
                user_prompt += f"User A: {message.message_content}\n"
            else:
                user_prompt += f"User B: {message.message_content}\n"
            
            for file_path in message.file_paths:
                caption = get_contextual_caption(file_path, user_prompt)
                user_prompt += f"Image [{file_path}]: {caption}\n"


        user_prompt += f"\nPlease respond with the following JSON format: \n{DraftResponse.model_json_schema()}"

        ollama_messages = [Message(role="system", content=system_prompt)]
        
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
    asyncio.run(main())