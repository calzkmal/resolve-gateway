import os
import requests
# import boto3
import os

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from dotenv import load_dotenv
load_dotenv()

# ================== TEMP MEDIA DIRECTORY ==================
MEDIA_TEMP_DIR = "C:/resolve_presets"
os.makedirs(MEDIA_TEMP_DIR, exist_ok=True)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ================== GOOGLE DRIVE UPLOAD/DOWNLOAD ==================
def get_oauth_creds(client_secret_json: str, token_path: str = "token.json"):
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret_json, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds

def upload_file(file_path: str, drive_folder_id: str):
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")

    creds = get_oauth_creds(os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_JSON"))
    drive = build("drive", "v3", credentials=creds)

    media = MediaFileUpload(file_path, resumable=True)

    file_metadata = {
        "name": os.path.basename(file_path),
        "parents": [drive_folder_id]
    }

    request = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name"
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploading {int(status.progress() * 100)}%")

    return response

def download_media(url: str) -> str:
    local_path = os.path.join(MEDIA_TEMP_DIR, "Bg_Media_4K.mp4")
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
    return local_path
