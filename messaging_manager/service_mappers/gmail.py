try:
    from libs.service_mapper_interface import ServiceMapperInterface, ServiceMetadata, get_source_id
    from libs.service_mapper_interface import UnifiedMessageFormat
    from libs.gmail_oauth_utils import get_gmail_oauth_token
except ImportError:
    from messaging_manager.libs.service_mapper_interface import ServiceMapperInterface, ServiceMetadata, get_source_id
    from messaging_manager.libs.service_mapper_interface import UnifiedMessageFormat
    from messaging_manager.libs.gmail_oauth_utils import get_gmail_oauth_token

from datetime import datetime
from typing import List, Optional, Dict
import uuid
import hashlib
import os
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
import asyncio
import base64
import re
import json
from datetime import datetime, timedelta, timezone
import traceback


class GmailServiceMapper(ServiceMapperInterface):
    def __init__(self, init_keys: dict[str, str], media_dir: str = None):
        super().__init__()
        self.init_keys = init_keys
        self.media_dir = media_dir
        self.latest_message_timestamp = self.init_keys.get('latest_message_timestamp', datetime.now() - timedelta(days=30))
        self.latest_message_ids = {}
        # TODO: run get_gmail_oauth_token rather than using the env variable
        self.oauth_token = get_gmail_oauth_token(self.init_keys["credentials_file_path"])
        # IMAP settings for different providers
        self.provider_settings = {
            'gmail': {
                'imap_server': 'imap.gmail.com',
                'smtp_server': 'smtp.gmail.com',
                'smtp_port': 587,
                'requires_oauth': True
            },
            'outlook': {
                'imap_server': 'outlook.office365.com',
                'smtp_server': 'smtp.office365.com',
                'smtp_port': 587,
                'requires_oauth': False
            },
            'yahoo': {
                'imap_server': 'imap.mail.yahoo.com',
                'smtp_server': 'smtp.mail.yahoo.com',
                'smtp_port': 587,
                'requires_oauth': False
            },
            'generic': {
                'imap_server': self.init_keys.get('imap_server', ''),
                'smtp_server': self.init_keys.get('smtp_server', ''),
                'smtp_port': int(self.init_keys.get('smtp_port', 587)),
                'requires_oauth': False
            }
        }
        
        # Determine provider from email address or use custom settings
        self.email = self.init_keys.get('email', '')
        self.provider = self._determine_provider()
        self.settings = self.provider_settings[self.provider]
        
        # Initialize connections
        self.imap_conn = None
        self.smtp_conn = None

    def _determine_provider(self) -> str:
        """Determine email provider based on email domain or explicit setting"""
        if 'provider' in self.init_keys:
            return self.init_keys['provider']
        
        if '@gmail.com' in self.email:
            return 'gmail'
        elif '@outlook.com' in self.email or '@hotmail.com' in self.email:
            return 'outlook'
        elif '@yahoo.com' in self.email:
            return 'yahoo'
        else:
            return 'generic'

    async def login(self) -> bool:
        """Log in to the email service using IMAP"""
        try:
            # Create IMAP connection
            self.imap_conn = imaplib.IMAP4_SSL(self.settings['imap_server'])
            
            if self.settings['requires_oauth'] and self.provider == 'gmail':
                # Handle Gmail's OAuth2 authentication
                token = self.oauth_token
                
                # Print first few characters of token for debugging
                token_prefix = token[:10] + "..." if len(token) > 10 else "too_short"
                print(f"Using OAuth token starting with: {token_prefix}")
                print(f"Email being used for authentication: {self.email}")
                
                # Try alternative authentication first (this worked in last attempt)
                try:
                    print("Using alternative authentication approach (direct command)")
                    
                    # Format the auth string exactly as Gmail expects it
                    auth_string = f'user={self.email}\1auth=Bearer {token}\1\1'
                    auth_bytes = auth_string.encode('utf-8')
                    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
                    
                    # Use lower-level command with proper formatting
                    typ, data = self.imap_conn._simple_command('AUTHENTICATE', 'XOAUTH2', auth_b64)
                    
                    # Properly handle the server's response
                    if typ == 'CONTINUE':
                        print("Received continuation request from server")
                        self.imap_conn.send('\r\n'.encode('utf-8'))
                        typ, data = self.imap_conn._get_response()
                    
                    if typ != 'OK':
                        print(f"OAuth authentication failed: {typ} {data}")
                        raise Exception(f"IMAP authentication failed: {data}")
                        
                    # Critical: Process the server response to update connection state
                    self.imap_conn.state = 'AUTH'
                    
                    # Verify the state updated correctly
                    print(f"IMAP state after authentication: {self.imap_conn.state}")
                    
                    # Test the connection with a simple command
                    status, folders = self.imap_conn.list()
                    if status != 'OK':
                        print(f"Warning: List command failed after authentication: {status}")
                        raise Exception("Authentication succeeded but commands fail")
                    else:
                        print("Connection verified with successful LIST command")
                    
                except Exception as auth_error:
                    print(f"Alternative authentication failed: {auth_error}")
                    
                    # Try the authenticate method instead
                    try:
                        print("Attempting OAuth authentication using authenticate() method")
                        self.imap_conn = imaplib.IMAP4_SSL(self.settings['imap_server'])
                        
                        # Create the auth string in the correct format for Gmail
                        auth_string = f'user={self.email}\1auth=Bearer {token}\1\1'
                        auth_bytes = auth_string.encode('utf-8')
                        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
                        
                        # Use the standard authenticate method
                        self.imap_conn.authenticate('XOAUTH2', lambda x: auth_b64)
                        print("IMAP authentication successful with authenticate() method")
                        
                    except imaplib.IMAP4.error as e:
                        print(f"Standard authenticate method failed: {e}")
                        
                        # Try app password as last resort
                        try:
                            if "app_password" in self.init_keys:
                                print("Attempting to use app password as fallback")
                                self.imap_conn = imaplib.IMAP4_SSL(self.settings['imap_server'])
                                result = self.imap_conn.login(self.email, self.init_keys['app_password'])
                                if result[0] != 'OK':
                                    raise Exception(f"App password authentication failed: {result}")
                                print("Successfully authenticated with app password")
                            else:
                                raise Exception("No app password available as fallback")
                        except Exception as app_pass_error:
                            print(f"App password authentication failed: {app_pass_error}")
                            raise Exception("All IMAP authentication methods failed")
                
                # Connect to SMTP for sending emails
                try:
                    print("Setting up SMTP connection")
                    self.smtp_conn = smtplib.SMTP(self.settings['smtp_server'], self.settings['smtp_port'])
                    self.smtp_conn.ehlo()
                    self.smtp_conn.starttls()
                    self.smtp_conn.ehlo()  # Second EHLO after STARTTLS is required
                    
                    # For SMTP OAuth authentication
                    print("Attempting SMTP OAuth authentication")
                    auth_string = f'user={self.email}\1auth=Bearer {token}\1\1'
                    auth_bytes = auth_string.encode('utf-8')
                    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
                    
                    # Try the standard SMTP AUTH command
                    smtp_code, smtp_resp = self.smtp_conn.docmd('AUTH', f'XOAUTH2 {auth_b64}')
                    
                    # Check if we got a challenge response
                    if smtp_code == 334:
                        print("Received SMTP continuation challenge")
                        self.smtp_conn.send('\r\n'.encode('utf-8'))
                        smtp_code, smtp_resp = self.smtp_conn.getreply()
                        
                    if smtp_code not in (235, 250, 200):  # Various success codes
                        print(f"SMTP OAuth failed, trying app password if available")
                        # Try app password as fallback for SMTP
                        if "app_password" in self.init_keys:
                            self.smtp_conn.login(self.email, self.init_keys['app_password'])
                        else:
                            raise Exception(f"SMTP authentication failed: {smtp_code} {smtp_resp}")
                    
                    print("SMTP authentication successful")
                    
                except Exception as smtp_e:
                    print(f"SMTP setup failed: {smtp_e}")
                    # We can continue without SMTP if only reading emails
                    print("Continuing without SMTP capability")
                    self.smtp_conn = None
                    
            else:
                # Standard password authentication
                print("Using standard password authentication")
                result = self.imap_conn.login(self.email, self.init_keys['password'])
                if result[0] != 'OK':
                    raise Exception(f"IMAP password authentication failed: {result}")
                print("IMAP password authentication successful")
                
                # Connect to SMTP for sending emails
                self.smtp_conn = smtplib.SMTP(self.settings['smtp_server'], self.settings['smtp_port'])
                self.smtp_conn.ehlo()
                self.smtp_conn.starttls()
                self.smtp_conn.ehlo()  # Second EHLO after STARTTLS is required
                self.smtp_conn.login(self.email, self.init_keys['password'])
                print("SMTP password authentication successful")
            
            # Verify IMAP authentication state manually
            try:
                if self.imap_conn.state != 'AUTH':
                    print(f"Warning: IMAP state is {self.imap_conn.state}, attempting to verify connection with a command")
                    # Test connection with a simple command
                    status, response = self.imap_conn.noop()
                    if status == 'OK':
                        print("Connection verified with NOOP command despite state reporting issues")
                        # Force the state to AUTH since commands are working
                        self.imap_conn.state = 'AUTH'
                    else:
                        raise Exception(f"IMAP not properly authenticated. NOOP test failed with: {status}")
            except Exception as state_error:
                print(f"State verification failed: {state_error}")
                raise
                
            print(f"Successfully logged in as: {self.email}")
            print(f"Final IMAP state: {self.imap_conn.state}")
            return True
            
        except Exception as e:
            print(f"Login failed: {e}")
            
            # Clean up connections on failure
            try:
                if self.imap_conn:
                    self.imap_conn.logout()
            except Exception as logout_e:
                print(f"Error during IMAP logout: {logout_e}")
                
            try:
                if self.smtp_conn:
                    self.smtp_conn.quit()
            except Exception as quit_e:
                print(f"Error during SMTP quit: {quit_e}")
                
            self.imap_conn = None
            self.smtp_conn = None
            
            return False

    async def logout(self) -> bool:
        """Log out from the email service"""
        try:
            if self.imap_conn:
                self.imap_conn.logout()
            
            if self.smtp_conn:
                self.smtp_conn.quit()
                
            return True
        except Exception as e:
            print(f"Logout failed: {e}")
            return False

    async def is_logged_in(self) -> bool:
        """Check if connected to the email service"""
        try:
            if not self.imap_conn:
                return False
                
            # Try a simple command to check connection
            status, _ = self.imap_conn.noop()
            return status == 'OK'
        except:
            return False

    def process_emails(self, email_ids: List[str], box: str) -> List[UnifiedMessageFormat]:
        results = []
        for email_id in sorted(email_ids, key=lambda x: int(x)):
                # Convert bytes to string if needed
                if isinstance(email_id, bytes):
                    email_id_str = email_id.decode('utf-8')
                else:
                    email_id_str = str(email_id)

                if box not in self.latest_message_ids:
                    self.latest_message_ids[box] = int(email_id)
                elif int(email_id) <= self.latest_message_ids[box]:
                    continue
                else:
                    self.latest_message_ids[box] = int(email_id)

                generated_email_id = hashlib.sha256(f"{box} {email_id_str}".encode()).hexdigest()
                media_dir = os.path.join(self.media_dir, generated_email_id)
                
                # Correctly fetch the email using RFC822
                status, msg_data = self.imap_conn.fetch(email_id, '(RFC822)')
                if status != 'OK' or not msg_data or msg_data[0] is None:
                    print(f"Failed to fetch email {email_id}: {msg_data}")
                    print(traceback.format_exc())
                    continue
                
                # Check if we have valid data structure before accessing
                if not isinstance(msg_data[0], tuple) or len(msg_data[0]) < 2:
                    print(f"Unexpected response format for email {email_id}: {msg_data}")
                    continue
                
                # The email body is in the second part of the first item in msg_data
                email_body = msg_data[0][1]
                if not email_body:
                    print(f"Empty email body for email {email_id}")
                    continue
                    
                message = email.message_from_bytes(email_body)

                # Get other party's id
                sender_email = self.extract_email(message['From'])
                other_party_id = sender_email
                sender_name = message['From']
                
                if sender_email == self.email:
                    sender_name = "user"
                    other_party_id = self.extract_email(message['To'])

                # Get subject
                subject = message['Subject'] or ""
                # Get thread id by stripping out RE: from the subject and hashing that with the other party's id
                stripped_subject = re.sub(r'(?i)^Re:\s*', '', subject)

                source_id = hashlib.sha256(f"{stripped_subject} {other_party_id}".encode()).hexdigest()
                file_paths = []
                
                # Process attachments and message content
                if message.is_multipart():
                    message_text = ""
                    for part in message.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        
                        # Handle attachments
                        if "attachment" in content_disposition:
                            filename = part.get_filename()
                            if filename:
                                if not os.path.exists(media_dir):
                                    os.makedirs(media_dir)
                                filepath = os.path.join(media_dir, filename)
                                print(f"Saving attachment to {filepath}")
                                message_text += f"\n[Attachment: {filename}]"
                                with open(filepath, 'wb') as f:
                                    f.write(part.get_payload(decode=True))
                                file_paths.append(filepath)
                        
                        # Handle inline images with Content-ID, only if not in a reply block
                        elif "Content-ID" in part:
                            content_id = part["Content-ID"].strip("<>")
                            if content_id and part.get_payload(decode=True):
                                # Try to get original filename
                                filename = None
                                
                                # Try Content-Disposition first
                                content_disposition = str(part.get("Content-Disposition", ""))
                                if "filename=" in content_disposition:
                                    filename_match = re.search(r'filename=["\'](.*?)["\']', content_disposition)
                                    if filename_match:
                                        filename = filename_match.group(1)
                                
                                # If no filename found, try Content-Type header
                                if not filename:
                                    content_type = str(part.get("Content-Type", ""))
                                    if "name=" in content_type:
                                        name_match = re.search(r'name=["\'](.*?)["\']', content_type)
                                        if name_match:
                                            filename = name_match.group(1)
                                
                                # If still no filename, fallback to Content-ID, but try to extract a meaningful name
                                if not filename:
                                    # Sometimes Content-IDs follow patterns like image001.jpg@01D... or filename.ext@...
                                    cid_filename_match = re.search(r'^([^@]+)@', content_id)
                                    if cid_filename_match:
                                        cid_filename = cid_filename_match.group(1)
                                        if '.' in cid_filename:  # Looks like it might have an extension
                                            filename = cid_filename
                                        else:
                                            # Determine extension based on MIME type
                                            mime_to_ext = {
                                                'image/jpeg': '.jpg',
                                                'image/png': '.png',
                                                'image/gif': '.gif',
                                                'image/bmp': '.bmp',
                                            }
                                            ext = mime_to_ext.get(part.get_content_type(), '.bin')
                                            filename = f"{content_id}{ext}"
                                    else:
                                        # Just use the content_id with appropriate extension
                                        mime_to_ext = {
                                            'image/jpeg': '.jpg',
                                            'image/png': '.png',
                                            'image/gif': '.gif',
                                            'image/bmp': '.bmp',
                                        }
                                        ext = mime_to_ext.get(part.get_content_type(), '.bin')
                                        filename = f"{content_id}{ext}"
                                
                                if not os.path.exists(media_dir):
                                    os.makedirs(media_dir)
                                    
                                filepath = os.path.join(media_dir, filename)
                                print(f"Saving inline image to {filepath}")
                                with open(filepath, 'wb') as f:
                                    payload = part.get_payload(decode=True)
                                    print(f"Payload: {len(payload)}")
                                    f.write(payload)
                                file_paths.append(filepath)
                        
                        # Get text content
                        elif content_type == "text/plain" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            if payload:
                                message_text += payload.decode('utf-8', errors='replace')
                else:
                    # For non-multipart messages
                    payload = message.get_payload(decode=True)
                    message_text = payload.decode('utf-8', errors='replace') if payload else ""
                
                # Clean the message text
                # strip out reply blocks start with "On" and ALWAYS ends with TWO or more \r\n> or \r\n>>
                # needs to the last of this pattern
                # Clean the message text
                message_text = re.sub(r'On.*?wrote:.*?((?:\r\n>|\r\n>>)(?:.(?!(?:\r\n>|\r\n>>)))*$)', '', message_text, flags=re.DOTALL)
                message_text = message_text.strip()

                # for each file path, see if the filename is in the message_text, if not, remove the file path
                file_paths = [fp for fp in file_paths if os.path.basename(fp) in message_text]
                # remove any files from media_dir that are not in the file_paths
                if os.path.exists(media_dir):
                    for file in os.listdir(media_dir):
                        if os.path.join(media_dir, file) not in file_paths:
                            os.remove(os.path.join(media_dir, file))
                    
                    # if the media_dir exists, is empty, remove it
                    if not os.listdir(media_dir):
                        os.rmdir(media_dir)

                    
                # Create unified message format
                unified_message = UnifiedMessageFormat(
                    message_id=generated_email_id,
                    service_name="email",
                    source_id=source_id,
                    source_keys={
                        "email_id": email_id_str,
                        "box": box
                    },
                    message_content=message_text,
                    sender_id=sender_email,
                    sender_name=sender_name,
                    message_timestamp=email.utils.parsedate_to_datetime(message['Date']) if message['Date'] else datetime.now(),
                    file_paths=file_paths
                )

                # if the message_timestamp is greater than the latest_message_timestamp, update the latest_message_timestamp
                if unified_message.message_timestamp.replace(tzinfo=timezone.utc) > self.latest_message_timestamp.replace(tzinfo=timezone.utc):
                    self.latest_message_timestamp = unified_message.message_timestamp
                
                # Add to results
                results.append(unified_message)

        return results
    
    async def get_new_messages(self, latest_message: UnifiedMessageFormat = None, limit_per_source: int = 5) -> List[UnifiedMessageFormat]:
        """Get email messages from both INBOX and Sent folders with thread organization
        
        Args:
            latest_message: The most recent message we've processed (optional)
            limit_per_source: Maximum number of messages to retrieve per folder
            
        Returns:
            List of UnifiedMessageFormat objects representing emails with consistent thread IDs
        """
        if not await self.is_logged_in():
            await self.login()
            
        results = []
        min_date = self.latest_message_timestamp
        # Default to checking the last 30 days if no latest message
        from datetime import timedelta
        if latest_message:
            min_date = latest_message.message_timestamp

        try:
            latest_date_str = min_date.strftime("%d-%b-%Y")
            # Process Sent folder
            status, message_count = self.imap_conn.select('"[Gmail]/Sent Mail"')
            if status != 'OK':
                print(f"Failed to select Sent: {message_count}")
                return results
            
            print(f"Searching for emails since {latest_date_str}")
            status, data = self.imap_conn.search(None, f'(SINCE "{latest_date_str}")')
            if status != 'OK':
                print(f"Failed to search for emails: {data}")
                return results
            
            sent_email_ids = data[0].split()[-limit_per_source:] if data[0] else []
            print(f"Found {len(sent_email_ids)} sent emails")
            results.extend(self.process_emails(sent_email_ids, '"[Gmail]/Sent Mail"'))

            # Process INBOX
            status, message_count = self.imap_conn.select('INBOX')
            if status != 'OK':
                print(f"Failed to select INBOX: {message_count}")
                return results
                
            # Search with SINCE criterion
            status, data = self.imap_conn.search(None, f'(SINCE "{latest_date_str}")')
            if status != 'OK':
                print(f"Failed to search for emails: {data}")
                return results
                
            inbox_email_ids = data[0].split()[-limit_per_source:] if data[0] else []
            print(f"Found {len(inbox_email_ids)} inbox emails")
            results.extend(self.process_emails(inbox_email_ids, "INBOX"))

        except Exception as e:
            print(f"Error getting new messages: {e}")
            print(traceback.format_exc())
            
        return results
        
    def extract_email(self, header_value):
        """Extract email address from a header value like 'Name <email@example.com>'"""
        if not header_value:
            return ""
        match = re.search(r'<([^>]+)>', header_value)
        if match:
            return match.group(1)
        return header_value.strip()
    
    async def reply_to_message(self, message: UnifiedMessageFormat, reply_content: str) -> str:
        """Reply to an email message"""
        if not await self.is_logged_in():
            await self.login()
            
        try:
            # Get original subject from source_keys
            subject = message.source_keys.get("subject", "")
            
            # Check if it already has Re: prefix
            if not subject.startswith("Re:"):
                subject = f"Re: {subject}"
            
            # Create email message
            msg = MIMEMultipart()
            msg["From"] = self.email
            msg["To"] = message.sender_id
            msg["Subject"] = subject
            
            # Add In-Reply-To header if we have the original Message-ID
            if "message_id" in message.source_keys:
                msg["In-Reply-To"] = message.source_keys["message_id"]
                msg["References"] = message.source_keys["message_id"]
            
            # Add text content
            msg.attach(MIMEText(reply_content, "plain"))
            
            # Send the email
            self.smtp_conn.send_message(msg)
            
            return "Message sent"
            
        except Exception as e:
            print(f"Error replying to message: {e}")
            return f"Failed to send message: {str(e)}"

    async def get_service_metadata(self) -> ServiceMetadata:
        """Get service metadata for email"""
        required_keys = ["email", "password",  "latest_message_timestamp"]
        
        # Add OAuth token for Gmail
        if self.provider == 'gmail':
            required_keys.append("credentials_file_path")
        
        # Add custom server settings for generic provider
        if self.provider == 'generic':
            required_keys.extend(["imap_server", "smtp_server", "smtp_port"])
        
        # Create reinitialize keys
        reinitialize_keys = {
            "latest_message_timestamp": self.latest_message_timestamp,
            "email": self.email,
            "provider": self.provider
        }
        
        # Add password if available (might be removed for security)
        if "password" in self.init_keys:
            reinitialize_keys["password"] = self.init_keys["password"]
            
        # Add OAuth token if available
        if "credentials_file_path" in self.init_keys:
            reinitialize_keys["credentials_file_path"] = self.init_keys["credentials_file_path"]
            
        # Add custom server settings if generic
        if self.provider == 'generic':
            reinitialize_keys["imap_server"] = self.init_keys.get("imap_server", "")
            reinitialize_keys["smtp_server"] = self.init_keys.get("smtp_server", "")
            reinitialize_keys["smtp_port"] = self.init_keys.get("smtp_port", "587")
        
        return ServiceMetadata(
            service_name="email",
            init_keys=required_keys,
            reinitialize_keys=reinitialize_keys
        )


async def main():
    """Test function for GmailServiceMapper"""
    import dotenv
    
    # Load environment variables
    dotenv.load_dotenv()
    
    # Set up email parameters
    email = os.getenv("GMAIL_EMAIL")
    password = os.getenv("GMAIL_PASSWORD")
    media_dir = "media"
    
    if not os.path.exists(media_dir):
        os.makedirs(media_dir)
    
    # Initialize keys dictionary
    init_keys = {
        "email": email,
        "latest_message_timestamp": datetime.now() - timedelta(days=30)
    }
    
    # For standard password authentication
    if password:
        init_keys["password"] = password
    
    # Handle OAuth for Gmail
    if "@gmail.com" in email:
        # First try to get OAuth token from environment        
        credentials_file_path = os.getenv("GMAIL_CREDENTIALS_FILE_PATH")
        if credentials_file_path:
            init_keys["credentials_file_path"] = credentials_file_path
            # Remove password if we're using OAuth
            if "password" in init_keys:
                del init_keys["password"]
        else:
            print("Warning: Gmail account detected but no OAuth token provided.")
            print("Using password authentication, which might not work with Gmail's security settings.")
    
    # For custom email server
    if os.getenv("EMAIL_IMAP_SERVER"):
        init_keys["provider"] = "generic"
        init_keys["imap_server"] = os.getenv("EMAIL_IMAP_SERVER")
        init_keys["smtp_server"] = os.getenv("EMAIL_SMTP_SERVER")
        init_keys["smtp_port"] = os.getenv("EMAIL_SMTP_PORT", "587")
    
    print(f"Initializing GmailServiceMapper with: {email}")
    print(f"Authentication method: {'OAuth' if 'oauth_token' in init_keys else 'Password'}")
    
    # Create service mapper
    service_mapper = GmailServiceMapper(
        init_keys=init_keys,
        media_dir=media_dir
    )
    await service_mapper.logout()
    # Try to log in
    logged_in = await service_mapper.login()
    
    if logged_in:
        print(f"Logged in: {logged_in}")
        print("latest_message_timestamp", service_mapper.latest_message_timestamp)
        # Get new messages
        new_messages = await service_mapper.get_new_messages(limit_per_source=5)
        print(f"Found {len(new_messages)} new messages")
        print("latest_message_timestamp", service_mapper.latest_message_timestamp)
        
        # save new_messages to file
        with open("test_messages.json", "w") as f:
            f.write("\n".join([m.model_dump_json(indent=4) for m in new_messages]))
        
        metadata = await service_mapper.get_service_metadata()
        print(f"Service metadata: {metadata}")

        await service_mapper.logout()

    await service_mapper.login()
    if await service_mapper.is_logged_in(): 
        # Get new messages
        new_messages = await service_mapper.get_new_messages(limit_per_source=5)
        print(f"Found {len(new_messages)} new messages")
        print("latest_message_timestamp", service_mapper.latest_message_timestamp)

if __name__ == "__main__":
    asyncio.run(main())