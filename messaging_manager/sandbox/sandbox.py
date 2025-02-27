import telethon
from telethon import TelegramClient
from qrcode import QRCode
import os
import dotenv
import uuid
from messaging_manager.libs.service_mapper_interface import UnifiedMessageFormat

qr = QRCode()

def gen_qr(token: str):
    qr.clear()
    qr.add_data(token)
    qr.print_ascii()

def display_url_as_qr(url):
    print(url)  # do whatever to show url as a qr to the user
    gen_qr(url)

async def show_chats(client: telethon.TelegramClient):
    print("\nFetching your chats...")
    # Get all dialogs (conversations) and their unread counts
    async for dialog in client.iter_dialogs(limit=3):
        if dialog.name is None or dialog.name == "":
            continue
        print("~" * 100)
        print(dialog)
        print("~" * 100)
        print(dir(dialog))
        print("~" * 100)
        # Get the name of the chat
        chat_name = dialog.name or "Deleted Account"
        # Get unread count
        unread_count = dialog.unread_count
        # Get chat type (private, group, channel)
        chat_type = "Private" if dialog.is_user else "Group" if dialog.is_group else "Channel"
        # Get the last message from iter_messages
        print("~" * 100)
        print(dialog.input_entity)
        print("~" * 100)
        async for message in client.iter_messages(entity=dialog.input_entity, limit=2):
            print("~" * 100)
            print(message)
            print("~" * 100)
        print(f"{chat_type}: {chat_name} - {unread_count} unread messages")

async def test_reply(client: telethon.TelegramClient):
    reply_to_id = 190317
    user = 1331568242
    message = "test"
    await client.send_message(entity=user, message=message, reply_to=reply_to_id)

async def login(client: telethon.TelegramClient):
    if not client.is_connected():
        await client.connect()
    
    # Check if we're already authorized
    if await client.is_user_authorized():
        print("Session found! Using existing session.")
        # Do whatever you need with the authorized session
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username})")
        return me
    
    # If we're not authorized, proceed with QR login
    print("No valid session found. Starting QR login...")
    qr_login = await client.qr_login()
    print(f"Connected: {client.is_connected()}")
    # TODO: redirect qr code to whatever UI is being used
    r = False
    while not r:
        display_url_as_qr(qr_login.url)
        # Important! You need to wait for the login to complete!
        try:
            r = await qr_login.wait(10)
            if r:
                me = await client.get_me()
                print(f"Successfully logged in as: {me.first_name} (@{me.username})")
                # After successful login, show chats
                return me
        except Exception as e:
            print(f"Waiting for login... ({e})")
            await qr_login.recreate()

    return None

async def get_chats(client: telethon.TelegramClient, limit: int=3):
    chats = []
    async for dialog in client.iter_dialogs(limit=limit):
        if dialog.name is None or dialog.name == "":
            continue
        chats.append(dialog)
    return chats

async def get_messages(client: telethon.TelegramClient, me, chats: list, latest_message_id: int=0):
    messages = []
    print("~" * 100)
    print(me)
    print("~" * 100)
    my_id = me.id
    for chat in chats:
        async for message in client.iter_messages(entity=chat.message.peer_id, limit=5, min_id=latest_message_id):
            from_id = message.peer_id.user_id
            if message.from_id is not None:
                from_id = message.from_id.user_id

            sender_name = chat.name
            print("~" * 100)
            print(from_id)
            print(my_id)
            print("~" * 100)

            if from_id == my_id:
                sender_name = f"Me"

            messages.append(UnifiedMessageFormat(
                message_id=str(uuid.uuid4()),
                service_name="telegram",
                source_keys={"peer_id": str(chat.message.peer_id.user_id), "message_id": str(message.id)},
                message_content=message.message,
                sender_id=str(from_id),
                sender_name=sender_name,
                message_timestamp=message.date,
                file_paths=[] # TODO: add file paths
            ))

    return messages

async def main(client: telethon.TelegramClient):
    me = await login(client)
    # await show_chats(client)
    chats = await get_chats(client, limit=2)
    messages = await get_messages(client, me, chats)
    for message in messages:
        print("~" * 100)
        print(message.model_dump_json(indent=4))
        print("~" * 100)
    #await test_reply(client)

# Load environment variables from .env
dotenv.load_dotenv()
TELEGRAM_API_ID = int(os.getenv("API_ID", "1234567"))
TELEGRAM_API_HASH = os.getenv("API_HASH", "0123456789abcdef0123456789abcdef")

# The session name is important - this is the file where session data is stored
SESSION_NAME = "SessionName"

client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
client.loop.run_until_complete(main(client))