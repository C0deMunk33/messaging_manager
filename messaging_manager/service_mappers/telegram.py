
from messaging_manager.libs.service_mapper_interface import ServiceMapperInterface, ServiceMetadata, get_source_id
from messaging_manager.libs.service_mapper_interface import UnifiedMessageFormat
from datetime import datetime
from typing import List
import uuid
from qrcode import QRCode
import asyncio
import telethon
import os
import hashlib
import json
qr = QRCode()

def gen_qr(token: str):
    qr.clear()
    qr.add_data(token)
    qr.print_ascii()

def display_url_as_qr(url):
    print(url)  # do whatever to show url as a qr to the user
    gen_qr(url)

class TelegramServiceMapper(ServiceMapperInterface):
    def __init__(self, init_keys: dict[str, str], session_name: str = None):
        super().__init__()
        # hash the init keys
        self.session_name = session_name
        self.latest_message_id = 0
        self.client = None
        self.init_keys = init_keys
        self.client = telethon.TelegramClient(session=self.session_name, api_id=self.init_keys['api_id'], api_hash=self.init_keys['api_hash'])

    async def login(self) -> bool:
        # get session from file
        if os.path.exists(self.session_name):
            self.client = telethon.TelegramClient(session=self.session_name, api_id=self.init_keys['api_id'], api_hash=self.init_keys['api_hash'])
        else:
            self.client = telethon.TelegramClient(session=self.session_name, api_id=self.init_keys['api_id'], api_hash=self.init_keys['api_hash'])

        if not self.client.is_connected():
            await self.client.connect()

        if await self.client.is_user_authorized():
            me = await self.client.get_me()
            print(f"Successfully logged in as: {me.first_name} (@{me.username})")
            return me
        
        qr_login = await self.client.qr_login()
        r = False
        while not r:
            display_url_as_qr(qr_login.url)
            # Important! You need to wait for the login to complete!
            try:
                r = await qr_login.wait(10)
                if r:
                    me = await self.client.get_me()
                    print(f"Successfully logged in as: {me.first_name} (@{me.username})")
                    return me
            except Exception as e:
                print(f"Waiting for login... ({e})")
                await qr_login.recreate()
        return None

    async def is_logged_in(self) -> bool:
        return self.client.is_connected()
    
    async def get_new_messages(self, latest_message: UnifiedMessageFormat = None, limit_per_source: int = 5) -> List[UnifiedMessageFormat]:
        results = []
        min_id = 0
        me = await self.client.get_me()
        if latest_message is not None:
            min_id = latest_message.message_id
        async for dialog in self.client.iter_dialogs(limit=2):
            if dialog.name is None or dialog.name == "":
                continue
            async for message in self.client.iter_messages(entity=dialog.message.peer_id, limit=limit_per_source, min_id=min_id):
                from_id = message.peer_id.user_id
                if message.from_id is not None:
                    from_id = message.from_id.user_id

                sender_name = dialog.name if dialog.name is not None else "Unknown"
               
                if from_id == me.id:
                    sender_name = "user"
                print("~" * 100)
                print(message)
                print("~" * 100)
                #TODO  if message media get url, type, site_name, title, description, send image to ollama?
                source_id = get_source_id(dialog.message.peer_id.user_id)
                result_message = UnifiedMessageFormat(
                    message_id=str(uuid.uuid4()),
                    service_name="telegram",
                    source_id=source_id,
                    source_keys={"peer_id": str(dialog.message.peer_id.user_id), "message_id": str(message.id)},
                    message_content=message.message, # todo: add media.
                    sender_id=str(from_id),
                    sender_name=sender_name,
                    message_timestamp=message.date,
                    file_paths=[] # TODO: add file paths
                )
                results.append(result_message)

        # find the latest message
        latest_message = max(results, key=lambda x: x.message_timestamp)
        self.latest_message_id = latest_message.message_id
        return results
    
    async def reply_to_message(self, message: UnifiedMessageFormat, reply_content: str) -> str:
        peer_id = int(message.source_keys["peer_id"])
        message_id = int(message.source_keys["message_id"])
        await self.client.send_message(entity=peer_id, message=reply_content, reply_to=message_id)
        return "Message sent"
    
    async def get_service_metadata(self) -> ServiceMetadata:
        return ServiceMetadata(
            service_name="telegram",
            init_keys=["api_id", "api_hash"]
        )


async def main():
    import dotenv
    dotenv.load_dotenv()
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_key = "session one"
    service_mapper = TelegramServiceMapper(
        init_keys={"api_id": api_id, "api_hash": api_hash},
        session_name=session_key
    )
    await service_mapper.login()
    is_logged_in = await service_mapper.is_logged_in()
    print(is_logged_in)
    new_messages = await service_mapper.get_new_messages()
    print(new_messages)
    print(await service_mapper.get_service_metadata())

if __name__ == "__main__":
    asyncio.run(main())