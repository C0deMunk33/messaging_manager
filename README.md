# messaging_manager

ollama pull huggingface.co/bartowski/Qwen2.5-14B-Instruct-1M-GGUF (see common.py, there's a TODO)
ollama pull minicpm-v
serve ollama
get service keys (see below)
create env (see .env.example)
poetry run python -m messaging_manager.run


TODO:
writing samples
persona
profiling
vector memory
graph memory


# Service Keys:
## Telegram Keys:
go Here: https://my.telegram.org/apps

## Gmail OAuth Setup

### Step 1: Create Google Cloud Project and OAuth Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Gmail API for your project:
   - Go to "APIs & Services" > "Library"
   - Search for "Gmail API" and enable it
4. Configure the OAuth consent screen:
   - Go to "APIs & Services" > "OAuth consent screen"
   - Select "External" user type (for personal projects)
   - Fill in the required app information (app name, support email)
   - Add the following scopes:
     - `https://mail.google.com/`
     - `https://www.googleapis.com/auth/gmail.modify`
     - `https://www.googleapis.com/auth/gmail.compose`
     - `https://www.googleapis.com/auth/gmail.send`
   - Add your Gmail address as a test user
5. Create OAuth credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Application type: "Desktop application"
   - Give it a name (e.g., "Email Service Mapper")
   - Click "Create" and download the JSON file
6. Add Test user
   - Go to Google Cloud Console > APIs & Services > OAuth consent screen
   - Click "Audience"
   - Under "Test users" click "+ Add Users"
   - Add your email

### Step 2: Generate an OAuth Token

Use the standalone utility to get an OAuth token:

```bash
poetry run python messaging_manager/libs/gmail_oauth_utils.py --credentials  path/to/credentials.json
```

This will:
1. Open a browser window asking you to sign in to your Google account
2. Request permission to access your Gmail account (you may have to bypass safty check)
3. After you grant permission, generate and display an OAuth token

The token will be printed to the console, which you can copy for use in your `.env` file.
