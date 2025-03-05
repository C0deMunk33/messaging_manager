import os
import json
import webbrowser
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import argparse

def get_gmail_oauth_token(credentials_file_path: str, token_cache_path: str = None, force_refresh: bool = False):
    """
    Obtain a Gmail OAuth token using credentials from a downloaded JSON file.
    
    Args:
        credentials_file_path: Path to the credentials.json file downloaded from Google Cloud Console
        token_cache_path: Optional path to cache the token for reuse (default: token.json in same directory)
        force_refresh: Force token refresh even if a valid token exists
    
    Returns:
        str: OAuth access token that can be used for Gmail API authentication
    """
    # Define the scopes needed for Gmail access
    SCOPES = [
        'https://mail.google.com/',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.compose',
        'https://www.googleapis.com/auth/gmail.send'
    ]
    
    # Set default token cache path if not provided
    if not token_cache_path:
        token_cache_path = os.path.join(os.path.dirname(credentials_file_path), 'token.json')
    
    creds = None
    
    # Check if we have a valid cached token (unless force refresh is requested)
    if not force_refresh and os.path.exists(token_cache_path):
        try:
            creds = Credentials.from_authorized_user_info(
                json.load(open(token_cache_path)), SCOPES)
        except Exception as e:
            print(f"Error loading cached token: {e}")
    
    # If there are no valid credentials available, prompt the user to log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                creds = None
        
        if not creds:
            try:
                # Load the credentials from the downloaded file
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_file_path, SCOPES)
                
                # Open browser for authentication
                creds = flow.run_local_server(port=0)
                
                # Save the credentials for the next run
                with open(token_cache_path, 'w') as token:
                    token.write(creds.to_json())
                    print(f"Token cached at: {token_cache_path}")
            except Exception as e:
                raise Exception(f"Failed to obtain OAuth credentials: {e}")
    
    # Return the access token
    return creds.token


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Gmail OAuth token from credentials file")
    parser.add_argument("--credentials", required=True, help="Path to credentials.json file")
    parser.add_argument("--token_path", help="Path to save token.json file")
    parser.add_argument("--force_refresh", action="store_true", help="Force token refresh")
    
    args = parser.parse_args()
    
    try:
        token = get_gmail_oauth_token(
            args.credentials, 
            args.token_path, 
            args.force_refresh
        )
        print(f"Successfully obtained OAuth token: {token}")
    except Exception as e:
        print(f"Error: {e}")