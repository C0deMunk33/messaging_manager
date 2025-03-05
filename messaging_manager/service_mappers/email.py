try:
    from libs.service_mapper_interface import ServiceMapperInterface, ServiceMetadata, get_source_id
    from libs.service_mapper_interface import UnifiedMessageFormat
except ImportError:
    from messaging_manager.libs.service_mapper_interface import ServiceMapperInterface, ServiceMetadata, get_source_id
    from messaging_manager.libs.service_mapper_interface import UnifiedMessageFormat

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

class EmailServiceMapper(ServiceMapperInterface):
    def __init__(self, init_keys: dict[str, str], media_dir: str = None):
        super().__init__()
        self.init_keys = init_keys
        self.media_dir = media_dir
        self.latest_message_id = self.init_keys.get('latest_message_id', None)
        
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
                token = self.init_keys["oauth_token"]
                
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

    def _decode_email_part(self, part) -> tuple:
        """Decode email part content and return content type and data"""
        content_type = part.get_content_type()
        content_disposition = str(part.get("Content-Disposition", ""))
        
        if "attachment" in content_disposition:
            # Handle attachment
            filename = part.get_filename()
            if filename:
                # Clean filename to decode if necessary
                if decode_header(filename)[0][1] is not None:
                    filename = decode_header(filename)[0][0].decode(decode_header(filename)[0][1])
                
                # Return attachment info
                return "attachment", {
                    "filename": filename,
                    "data": part.get_payload(decode=True),
                    "content_type": content_type
                }
        
        if content_type == "text/plain":
            # Get plain text content
            try:
                payload = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                return "text/plain", payload
            except:
                return "text/plain", "Error decoding text content"
                
        elif content_type == "text/html":
            # Get HTML content
            try:
                payload = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                return "text/html", payload
            except:
                return "text/html", "Error decoding HTML content"
        
        return None, None

    def _extract_email_content(self, msg) -> tuple:
        """Extract text content and attachments from email message"""
        text_content = ""
        html_content = ""
        attachments = []
        
        # Handle single part emails
        if msg.is_multipart():
            for part in msg.walk():
                content_type, content = self._decode_email_part(part)
                
                if content_type == "text/plain":
                    text_content = content
                elif content_type == "text/html":
                    html_content = content
                elif content_type == "attachment":
                    attachments.append(content)
        else:
            content_type, content = self._decode_email_part(msg)
            if content_type == "text/plain":
                text_content = content
            elif content_type == "text/html":
                html_content = content
                
        # Prefer plain text, but use HTML if that's all we have
        final_content = text_content if text_content else html_content
        
        return final_content, attachments

    def _get_sender_info(self, msg) -> tuple:
        """Extract sender name and email from message"""
        from_header = msg["From"]
        sender_email = ""
        sender_name = ""
        
        # Extract name and email from the from header
        match = re.search(r'"?([^"<]+)"?\s*<?([^>]*)>?', from_header)
        if match:
            sender_name, sender_email = match.groups()
            sender_name = sender_name.strip()
            sender_email = sender_email.strip()
        else:
            sender_email = from_header
            sender_name = from_header
            
        return sender_name, sender_email

    async def get_new_messages(self, latest_message: UnifiedMessageFormat = None, limit_per_source: int = 5) -> List[UnifiedMessageFormat]:
        """Get new email messages"""
        if not await self.is_logged_in():
            await self.login()
            
        results = []
        
        try:
            # Select inbox folder
            self.imap_conn.select("INBOX")
            
            # Get all or unseen messages
            if latest_message and self.latest_message_id:
                # Try to get messages newer than the latest message
                status, data = self.imap_conn.search(None, f'SINCE {latest_message.message_timestamp.strftime("%d-%b-%Y")}')
            else:
                # Get unseen messages if no latest message
                status, data = self.imap_conn.search(None, "UNSEEN")
                
            if status != 'OK':
                print("Failed to search for emails")
                return results
                
            email_ids = data[0].split()
            
            # Process emails (newest first, limited by limit_per_source)
            for i, email_id in enumerate(reversed(email_ids)):
                if i >= limit_per_source:
                    break
                    
                status, msg_data = self.imap_conn.fetch(email_id, "(RFC822)")
                if status != 'OK':
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Get message ID for tracking
                message_id = msg.get("Message-ID", f"email_{email_id.decode()}")
                if not message_id:
                    message_id = f"email_{email_id.decode()}_{hash(raw_email)}"
                
                # Generate a deterministic ID for the message
                generated_message_id = hashlib.sha256((message_id + "email").encode()).hexdigest()
                
                # Extract basic email info
                subject = msg.get("Subject", "")
                if decode_header(subject)[0][1] is not None:
                    subject = decode_header(subject)[0][0].decode(decode_header(subject)[0][1])
                
                date_str = msg.get("Date", "")
                try:
                    # Parse email date format
                    date_tuple = email.utils.parsedate_tz(date_str)
                    timestamp = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                except:
                    timestamp = datetime.now()
                
                # Get sender info
                sender_name, sender_email = self._get_sender_info(msg)
                
                # Extract content and attachments with improved function
                content, attachments = self._extract_email_content(msg)
                
                # Construct message content
                message_content = f"Subject: {subject}\n\n{content}"
                
                # Save attachments if any, including inline images
                file_paths = []
                inline_image_map = {}  # Map content IDs to file paths
                
                if attachments and self.media_dir:
                    # Create directory for this email's attachments
                    media_dir = os.path.join(self.media_dir, str(generated_message_id))
                    if not os.path.exists(media_dir):
                        os.makedirs(media_dir)
                    
                    for attachment in attachments:
                        file_path = os.path.join(media_dir, attachment["filename"])
                        with open(file_path, "wb") as f:
                            f.write(attachment["data"])
                        
                        # Track file paths
                        file_paths.append(file_path)
                        
                        # If this is an inline image with a content ID, map it
                        if attachment.get("is_inline") and attachment.get("content_id"):
                            inline_image_map[attachment["content_id"]] = file_path
                        
                        print(f"Saved attachment to: {file_path}")
                
                # If we have HTML content and inline images, update the HTML to reference local files
                if content.startswith("<!DOCTYPE html") or "<html" in content:
                    for cid, file_path in inline_image_map.items():
                        # Replace "cid:content_id" references with file paths
                        content = content.replace(f'cid:{cid}', f'file://{file_path}')
                    
                    # Update the message content with the modified HTML
                    message_content = f"Subject: {subject}\n\n{content}"
                
                # Create source keys for reference
                source_keys = {
                    "email_id": email_id.decode(),
                    "message_id": message_id,
                    "subject": subject
                }
                
                if file_paths:
                    source_keys["media_dir"] = os.path.join(self.media_dir, str(generated_message_id))
                    source_keys["has_inline_images"] = bool(inline_image_map)
                
                # Generate source ID
                source_id = get_source_id(sender_email)
                
                # Create unified message
                unified_message = UnifiedMessageFormat(
                    message_id=generated_message_id,
                    service_name="email",
                    source_id=source_id,
                    source_keys=source_keys,
                    message_content=message_content,
                    sender_id=sender_email,
                    sender_name=sender_name,
                    message_timestamp=timestamp,
                    file_paths=file_paths
                )
                
                results.append(unified_message)
            
            # Update latest message ID if we got any messages
            if results:
                latest_msg = max(results, key=lambda x: x.message_timestamp)
                self.latest_message_id = latest_msg.message_id
                
            return results
            
        except Exception as e:
            print(f"Error getting new messages: {e}")
            return []


    def _extract_email_content(self, msg):
        """Extract email content and attachments, including inline images
        
        Args:
            msg: Email message object
            
        Returns:
            tuple: (content, attachments)
                - content: String with email body
                - attachments: List of dictionaries with attachment info
        """
        content = ""
        html_content = ""
        attachments = []
        
        # Process each part of the email
        if msg.is_multipart():
            # Handle multipart messages
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                
                # Get the content ID for potential inline images
                content_id = part.get("Content-ID")
                if content_id:
                    # Remove angle brackets if present
                    content_id = content_id.strip("<>")
                
                # Handle text content
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        part_content = part.get_payload(decode=True)
                        if part_content:
                            part_content = part_content.decode(errors='replace')
                            content += part_content
                    except Exception as e:
                        print(f"Error decoding plain text: {e}")
                
                # Handle HTML content
                elif content_type == "text/html" and "attachment" not in content_disposition:
                    try:
                        part_content = part.get_payload(decode=True)
                        if part_content:
                            part_content = part_content.decode(errors='replace')
                            html_content = part_content
                    except Exception as e:
                        print(f"Error decoding HTML: {e}")
                
                # Handle inline images (they typically have Content-ID and no Content-Disposition or are inline)
                elif content_type.startswith("image/") and (content_id or "inline" in content_disposition):
                    try:
                        filename = part.get_filename()
                        if not filename:
                            # Generate filename for inline images without names
                            ext = content_type.split('/')[1]
                            filename = f"inline_image_{len(attachments)}.{ext}"
                        
                        # Store inline image data
                        image_data = part.get_payload(decode=True)
                        
                        # Add to attachments
                        attachments.append({
                            "filename": filename,
                            "data": image_data,
                            "content_type": content_type,
                            "is_inline": True,
                            "content_id": content_id
                        })
                    except Exception as e:
                        print(f"Error processing inline image: {e}")
                
                # Handle regular attachments
                elif "attachment" in content_disposition or content_type.startswith(("application/", "image/", "audio/", "video/")):
                    try:
                        filename = part.get_filename()
                        if filename:
                            # Try to decode the filename if needed
                            if decode_header(filename)[0][1] is not None:
                                filename = decode_header(filename)[0][0].decode(decode_header(filename)[0][1])
                            
                            attachment_data = part.get_payload(decode=True)
                            if attachment_data:
                                attachments.append({
                                    "filename": filename,
                                    "data": attachment_data,
                                    "content_type": content_type,
                                    "is_inline": False
                                })
                    except Exception as e:
                        print(f"Error processing attachment: {e}")
        else:
            # Handle non-multipart messages (simple text)
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                try:
                    content = msg.get_payload(decode=True).decode(errors='replace')
                except Exception as e:
                    print(f"Error decoding non-multipart message: {e}")
            elif content_type == "text/html":
                try:
                    html_content = msg.get_payload(decode=True).decode(errors='replace')
                except Exception as e:
                    print(f"Error decoding HTML message: {e}")
        
        # Prefer HTML content if available, otherwise use plain text
        final_content = html_content if html_content else content
        
        return final_content, attachments
    
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
        required_keys = ["email", "password", "latest_message_id"]
        
        # Add OAuth token for Gmail
        if self.provider == 'gmail':
            required_keys.append("oauth_token")
        
        # Add custom server settings for generic provider
        if self.provider == 'generic':
            required_keys.extend(["imap_server", "smtp_server", "smtp_port"])
        
        # Create reinitialize keys
        reinitialize_keys = {
            "latest_message_id": self.latest_message_id,
            "email": self.email,
            "provider": self.provider
        }
        
        # Add password if available (might be removed for security)
        if "password" in self.init_keys:
            reinitialize_keys["password"] = self.init_keys["password"]
            
        # Add OAuth token if available
        if "oauth_token" in self.init_keys:
            reinitialize_keys["oauth_token"] = self.init_keys["oauth_token"]
            
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
    """Test function for EmailServiceMapper"""
    import dotenv
    
    # Load environment variables
    dotenv.load_dotenv()
    
    # Set up email parameters
    email = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    media_dir = "media"
    
    if not os.path.exists(media_dir):
        os.makedirs(media_dir)
    
    # Initialize keys dictionary
    init_keys = {
        "email": email,
        "latest_message_id": None
    }
    
    # For standard password authentication
    if password:
        init_keys["password"] = password
    
    # Handle OAuth for Gmail
    if "@gmail.com" in email:
        # First try to get OAuth token from environment
        oauth_token = os.getenv("GMAIL_OAUTH_TOKEN")
                
        if oauth_token:
            init_keys["oauth_token"] = oauth_token
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
    
    print(f"Initializing EmailServiceMapper with: {email}")
    print(f"Authentication method: {'OAuth' if 'oauth_token' in init_keys else 'Password'}")
    
    # Create service mapper
    service_mapper = EmailServiceMapper(
        init_keys=init_keys,
        media_dir=media_dir
    )
    
    # Try to log in
    logged_in = await service_mapper.login()
    print(f"Logged in: {logged_in}")
    
    if logged_in:
        # Get new messages
        new_messages = await service_mapper.get_new_messages(limit_per_source=5)
        print(f"Found {len(new_messages)} new messages")
        
        for msg in new_messages:
            print(f"From: {msg.sender_name} <{msg.sender_id}>")
            print(f"Content: {msg.message_content[:100]}...")
            print(f"Attachments: {len(msg.file_paths)}")
            print("-" * 50)
        
        metadata = await service_mapper.get_service_metadata()
        print(f"Service metadata: {metadata}")
        
        await service_mapper.logout()

if __name__ == "__main__":
    asyncio.run(main())