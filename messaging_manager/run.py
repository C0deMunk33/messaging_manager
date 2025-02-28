import os
import asyncio
from pydantic import BaseModel
from typing import Optional
from messaging_manager.service_mappers.telegram import TelegramServiceMapper
from messaging_manager.libs.common import call_ollama_chat, Message

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

async def main():
    import dotenv
    dotenv.load_dotenv()
    server_url = os.getenv("OLLAMA_SERVER_URL")
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_key = "session one"
    service_mapper = TelegramServiceMapper(
        init_keys={"api_id": api_id, "api_hash": api_hash},
        session_name=session_key
    )

    await service_mapper.login()
    is_logged_in = await service_mapper.is_logged_in()

    message_limit = 25

    new_messages = await service_mapper.get_new_messages(limit_per_source=message_limit)

    print(await service_mapper.get_service_metadata())


    # group messages by source ID
    messages_by_source_id = {}
    for message in new_messages:
        if message.source_id not in messages_by_source_id:
            messages_by_source_id[message.source_id] = []
        messages_by_source_id[message.source_id].append(message)

    system_prompt = get_system_prompt()


    for source_id, messages in messages_by_source_id.items():        
        # reverse the messages, create a string
        messages.reverse()
        user_prompt = """Please determine if User A needs to respond next in the conversion and if so draft an appropriate response.
        If you determine that User A does not need to respond, set the response_needed to False."""
        for message in messages:
            # TODO add time as "minutes ago" "hours ago" "days ago" etc
            # TODO add media to the prompt
            if message.sender_name == "user":
                user_prompt += f"User A: {message.message_content}\n"
            else:
                user_prompt += f"User B: {message.message_content}\n"

        user_prompt += f"\nPlease respond with the following JSON format: \n{DraftResponse.model_json_schema()}"

        ollama_messages = [Message(role="system", content=system_prompt)]
        ollama_messages.append(Message(role="user", content=user_prompt))
        print("~" * 100)
        print(ollama_messages)
        # call ollama chat
        response = call_ollama_chat(server_url, "Qwen2.5-14B-Instruct-1M-GGUF", ollama_messages, json_schema=DraftResponse.model_json_schema())
        draft_response = DraftResponse.model_validate_json(response)
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