
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
    def __init__(self, init_keys: dict[str, str], media_dir: str = None):
        super().__init__()
        # hash the init keys
        
        self.client = None
        self.init_keys = init_keys
        self.media_dir = media_dir
        self.latest_message_id = self.init_keys['latest_message_id']

        self.session_name = self.init_keys['session_name']
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

    async def logout(self) -> bool:
        await self.client.disconnect()
        return True

    async def is_logged_in(self) -> bool:
        return self.client.is_connected()
    
    async def get_new_messages(self, latest_message: UnifiedMessageFormat = None, limit_per_source: int = 5) -> List[UnifiedMessageFormat]:
        results = []
        min_id = 0
        me = await self.client.get_me()

        parent_posts = {} # grouped_id -> parent_post_id
        if latest_message is not None:
            min_id = int(latest_message.source_keys["message_id"])
        async for dialog in self.client.iter_dialogs(limit=2):
            if dialog.name is None or dialog.name == "":
                continue

            all_messages = []
            async for message in self.client.iter_messages(entity=dialog.message.peer_id, limit=limit_per_source, min_id=min_id):
                all_messages.append(message)

            for message in reversed(all_messages):
                print("~" * 100)
                print(message)
                print("~" * 100)
                generated_message_id = hashlib.sha256((str(message.id) + "telegram").encode()).hexdigest()                
                source_keys={"peer_id": str(dialog.message.peer_id.user_id), "message_id": str(message.id)}                               

                media_dir = os.path.join(self.media_dir, str(generated_message_id))

                if message.grouped_id:
                    generated_grouped_message_id = hashlib.sha256((str(message.grouped_id) + "telegram").encode()).hexdigest()
                    media_dir = os.path.join(self.media_dir, str(generated_grouped_message_id))
                    source_keys["grouped_id"] = str(message.grouped_id)
 
                from_id = message.peer_id.user_id
                if message.from_id is not None:
                    from_id = message.from_id.user_id

                sender_name = dialog.name if dialog.name is not None else "Unknown"
               
                if from_id == me.id:
                    sender_name = "user"
                # notes:
                # reddit links preview
                # X links don't preview, or at least not always
                # only one media per message, when you send multiple files in telegram, each file is a new message. the caption is attached to the first message as .message .
                final_message = message.message

                if message.media:
                    # make media dir if it doesn't exist
                    if not os.path.exists(media_dir):
                        os.makedirs(media_dir)
                    
                    source_keys["media_dir"] = media_dir

                    media_type = type(message.media)
                    if media_type == telethon.tl.types.MessageMediaWebPage:
                        if type(message.media.webpage) == telethon.tl.types.WebPageEmpty:
                            final_message = f"shared a webpage: {message.media.webpage.url}\n"
                        else:
                            final_message = f"shared a webpage: {message.media.webpage.title} ({message.media.webpage.url})\n"
                        
                        if message.message and message.message != "":
                            final_message += f"comment: {message.message}"
                            
                        # TODO: scrape page
                    elif media_type == telethon.tl.types.MessageMediaPhoto:
                        # download media
                        await message.download_media(media_dir)
                    elif media_type == telethon.tl.types.MessageMediaDocument:
                        await message.download_media(media_dir)


                    source_keys["media_type"] = str(media_type)
                        
                source_id = get_source_id(dialog.message.peer_id.user_id)
                result_message = UnifiedMessageFormat(
                    message_id=generated_message_id,
                    service_name="telegram",
                    source_id=source_id,
                    source_keys=source_keys,
                    message_content=final_message,
                    sender_id=str(from_id),
                    sender_name=sender_name,
                    message_timestamp=message.date,
                    file_paths=[]
                )
                
                results.append(result_message)

        final_messages = []
        processed_grouped_ids = []
        # get file paths for each file in media_dir
        for message in results:
            if "media_dir" in message.source_keys:
                media_dir = message.source_keys["media_dir"]
                if os.path.exists(media_dir):
                    for file in os.listdir(media_dir):
                        message.file_paths.append(os.path.join(media_dir, file))

            if "grouped_id" not in message.source_keys:
                final_messages.append(message)
            else:
                if message.source_keys["grouped_id"] not in processed_grouped_ids:
                    # get all messages with the same grouped_id
                    grouped_messages = [m for m in results if "grouped_id" in m.source_keys and m.source_keys["grouped_id"] == message.source_keys["grouped_id"]]
                    # sort by message_timestamp
                    grouped_messages.sort(key=lambda x: x.message_timestamp)
                    # concat all message_content
                    message.message_content = "\n".join([m.message_content for m in grouped_messages])
                    final_messages.append(message)
                    processed_grouped_ids.append(message.source_keys["grouped_id"])


        # find the latest message
        if len(final_messages) > 0:
            latest_message = max(final_messages, key=lambda x: x.message_timestamp)
            self.latest_message_id = latest_message.message_id
        return final_messages
    
    async def reply_to_message(self, message: UnifiedMessageFormat, reply_content: str) -> str:
        peer_id = int(message.source_keys["peer_id"])
        message_id = int(message.source_keys["message_id"])
        await self.client.send_message(entity=peer_id, message=reply_content, reply_to=message_id)
        return "Message sent"
    
    async def get_service_metadata(self) -> ServiceMetadata:
        return ServiceMetadata(
            service_name="telegram",
            init_keys=["api_id", "api_hash", "latest_message_id", "session_name"],
            reinitialize_keys={
                "latest_message_id": self.latest_message_id,
                "session_name": self.session_name,
                "api_id": self.init_keys["api_id"],
                "api_hash": self.init_keys["api_hash"]
            }
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