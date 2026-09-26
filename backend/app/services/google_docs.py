import json
from typing import Optional, List, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import GoogleCredential
from app.core.logging import logger
import io


class GoogleDocsService:
    def __init__(self, db: Session):
        self.db = db
        self.docs_service = None
        self.drive_service = None
        self._load_credentials()

    def _load_credentials(self) -> bool:
        cred_row = self.db.query(GoogleCredential).first()
        if not cred_row:
            logger.warning("No Google credentials found")
            return False

        try:
            creds = Credentials(
                token=cred_row.access_token,
                refresh_token=cred_row.refresh_token,
                token_uri=cred_row.token_uri,
                client_id=cred_row.client_id,
                client_secret=cred_row.client_secret,
                scopes=json.loads(cred_row.scopes) if cred_row.scopes else [],
            )

            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                cred_row.access_token = creds.token
                cred_row.expiry = creds.expiry
                self.db.commit()

            self.docs_service = build("docs", "v1", credentials=creds)
            self.drive_service = build("drive", "v3", credentials=creds)
            logger.info("Google Docs/Drive services initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Google Docs/Drive: {e}")
            return False

    # ===== Google Docs =====

    def get_document(self, document_id: str) -> Optional[Dict]:
        """Get document content and metadata"""
        try:
            doc = self.docs_service.documents().get(documentId=document_id).execute()
            return doc
        except HttpError as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return None

    def get_document_text(self, document_id: str) -> str:
        """Extract plain text from document"""
        doc = self.get_document(document_id)
        if not doc:
            return ""
        
        text = ""
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                for elem in element["paragraph"].get("elements", []):
                    if "textRun" in elem:
                        text += elem["textRun"].get("content", "")
        return text

    def create_document(self, title: str, content: str = "") -> Optional[Dict]:
        """Create a new Google Doc"""
        try:
            doc = self.docs_service.documents().create(body={"title": title}).execute()
            doc_id = doc.get("documentId")
            
            if content:
                self.append_text(doc_id, content)
            
            return self.get_document(doc_id)
        except HttpError as e:
            logger.error(f"Error creating document: {e}")
            return None

    def append_text(self, document_id: str, text: str) -> bool:
        """Append text to document"""
        try:
            requests = [{
                "insertText": {
                    "location": {"index": 1},
                    "text": text
                }
            }]
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": requests}
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"Error appending text: {e}")
            return False

    def replace_text(self, document_id: str, search: str, replace: str) -> bool:
        """Replace text in document"""
        try:
            requests = [{
                "replaceAllText": {
                    "containsText": {"text": search, "matchCase": True},
                    "replaceText": replace
                }
            }]
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": requests}
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"Error replacing text: {e}")
            return False

    # ===== Google Drive =====

    def list_files(self, folder_id: str = None, query: str = None, page_size: int = 100) -> List[Dict]:
        """List files in Drive"""
        try:
            q_parts = []
            if folder_id:
                q_parts.append(f"'{folder_id}' in parents")
            if query:
                q_parts.append(query)
            
            q = " and ".join(q_parts) if q_parts else None
            
            results = self.drive_service.files().list(
                q=q,
                pageSize=page_size,
                fields="nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink)"
            ).execute()
            return results.get("files", [])
        except HttpError as e:
            logger.error(f"Error listing files: {e}")
            return []

    def get_file(self, file_id: str) -> Optional[Dict]:
        """Get file metadata"""
        try:
            return self.drive_service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, description"
            ).execute()
        except HttpError as e:
            logger.error(f"Error getting file {file_id}: {e}")
            return None

    def download_file(self, file_id: str) -> Optional[bytes]:
        """Download file content"""
        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            file_io = io.BytesIO()
            downloader = MediaIoBaseDownload(file_io, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            return file_io.getvalue()
        except HttpError as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            return None

    def upload_file(self, name: str, content: bytes, mime_type: str, folder_id: str = None) -> Optional[Dict]:
        """Upload file to Drive"""
        try:
            metadata = {"name": name}
            if folder_id:
                metadata["parents"] = [folder_id]
            
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)
            file = self.drive_service.files().create(
                body=metadata,
                media_body=media,
                fields="id, name, mimeType, size, webViewLink"
            ).execute()
            return file
        except HttpError as e:
            logger.error(f"Error uploading file: {e}")
            return None

    def create_folder(self, name: str, parent_id: str = None) -> Optional[Dict]:
        """Create folder in Drive"""
        try:
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            if parent_id:
                metadata["parents"] = [parent_id]
            
            folder = self.drive_service.files().create(
                body=metadata,
                fields="id, name, webViewLink"
            ).execute()
            return folder
        except HttpError as e:
            logger.error(f"Error creating folder: {e}")
            return None

    def share_file(self, file_id: str, email: str, role: str = "reader") -> bool:
        """Share file with email"""
        try:
            permission = {
                "type": "user",
                "role": role,
                "emailAddress": email
            }
            self.drive_service.permissions().create(
                fileId=file_id,
                body=permission,
                sendNotificationEmail=False
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"Error sharing file: {e}")
            return False

    def export_doc_as_pdf(self, document_id: str) -> Optional[bytes]:
        """Export Google Doc as PDF"""
        try:
            return self.drive_service.files().export(
                fileId=document_id,
                mimeType="application/pdf"
            ).execute()
        except HttpError as e:
            logger.error(f"Error exporting as PDF: {e}")
            return None

    def export_doc_as_docx(self, document_id: str) -> Optional[bytes]:
        """Export Google Doc as DOCX"""
        try:
            return self.drive_service.files().export(
                fileId=document_id,
                mimeType="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ).execute()
        except HttpError as e:
            logger.error(f"Error exporting as DOCX: {e}")
            return None


def get_google_docs_service(db: Session = None) -> Optional[GoogleDocsService]:
    if db is None:
        db = next(get_db())
    service = GoogleDocsService(db)
    return service if service.docs_service else None