import json
from typing import Optional, List, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import GoogleCredential
from app.core.config import settings
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
                token_uri=cred_row.token_uri or "https://oauth2.googleapis.com/token",
                client_id=cred_row.client_id or settings.google_client_id,
                client_secret=cred_row.client_secret or settings.google_client_secret,
                scopes=None,
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

    def get_document_end_index(self, document_id: str) -> int:
        """Get the true end index of the document body."""
        doc = self.get_document(document_id)
        if not doc:
            return 1
        content = doc.get("body", {}).get("content", [])
        if not content:
            return 1
        last_element = content[-1]
        return max(1, last_element.get("endIndex", 1) - 1)

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
        """Append text to the end of the document"""
        try:
            end_index = self.get_document_end_index(document_id)
            requests = [{
                "insertText": {
                    "location": {"index": end_index},
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

    def insert_page_break(self, document_id: str, index: Optional[int] = None) -> bool:
        """Insert a page break at given index or end of document."""
        try:
            target_index = index if index is not None else self.get_document_end_index(document_id)
            requests = [{
                "insertPageBreak": {
                    "location": {"index": target_index}
                }
            }]
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": requests}
            ).execute()
            return True
        except Exception as e:
            logger.warning(f"Error inserting page break into doc {document_id}: {e}")
            return False

    def append_styled_block(
        self,
        document_id: str,
        text: str,
        style_type: str = "NORMAL",  # "TITLE", "HEADING_1", "HEADING_2", "HEADING_3", "CODE", "BOLD_LABEL"
        font_size: Optional[float] = None,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        alignment: Optional[str] = None,  # "CENTER", "START", "END", "JUSTIFIED"
        space_above: Optional[float] = None,
        space_below: Optional[float] = None,
        line_spacing: Optional[float] = None,
        color_rgb: Optional[tuple] = None,
        font_family: Optional[str] = None,
    ) -> bool:
        """Append text to the document and apply typography styles (headings, colors, alignments, code fonts)."""
        if not text:
            return True
        try:
            start_index = self.get_document_end_index(document_id)
            insert_req = {
                "insertText": {
                    "location": {"index": start_index},
                    "text": text
                }
            }
            end_index = start_index + len(text)
            requests = [insert_req]

            para_named_style = None
            if style_type == "TITLE":
                para_named_style = "TITLE"
            elif style_type == "HEADING_1":
                para_named_style = "HEADING_1"
            elif style_type == "HEADING_2":
                para_named_style = "HEADING_2"
            elif style_type == "HEADING_3":
                para_named_style = "HEADING_3"

            para_style: Dict[str, Any] = {}
            para_fields: List[str] = []

            if para_named_style:
                para_style["namedStyleType"] = para_named_style
                para_fields.append("namedStyleType")

            if space_above is not None:
                para_style["spaceAbove"] = {"magnitude": space_above, "unit": "PT"}
                para_fields.append("spaceAbove")
            elif para_named_style:
                para_style["spaceAbove"] = {"magnitude": 14, "unit": "PT"}
                para_fields.append("spaceAbove")

            if space_below is not None:
                para_style["spaceBelow"] = {"magnitude": space_below, "unit": "PT"}
                para_fields.append("spaceBelow")
            elif para_named_style:
                para_style["spaceBelow"] = {"magnitude": 6, "unit": "PT"}
                para_fields.append("spaceBelow")

            if alignment:
                para_style["alignment"] = alignment
                para_fields.append("alignment")

            if line_spacing is not None:
                para_style["lineSpacing"] = line_spacing
                para_fields.append("lineSpacing")

            if para_fields:
                requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "paragraphStyle": para_style,
                        "fields": ",".join(para_fields)
                    }
                })

            text_style: Dict[str, Any] = {}
            fields: List[str] = []

            if bold or style_type in ("TITLE", "HEADING_1", "HEADING_2", "HEADING_3", "BOLD_LABEL"):
                text_style["bold"] = True
                fields.append("bold")
            elif bold is False and style_type == "NORMAL":
                text_style["bold"] = False
                fields.append("bold")

            if italic:
                text_style["italic"] = True
                fields.append("italic")
            elif italic is False:
                text_style["italic"] = False
                fields.append("italic")

            if underline:
                text_style["underline"] = True
                fields.append("underline")
            elif underline is False:
                text_style["underline"] = False
                fields.append("underline")

            if font_size:
                text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
                fields.append("fontSize")
            elif style_type == "TITLE":
                text_style["fontSize"] = {"magnitude": 22, "unit": "PT"}
                fields.append("fontSize")
            elif style_type == "HEADING_1":
                text_style["fontSize"] = {"magnitude": 16, "unit": "PT"}
                fields.append("fontSize")
            elif style_type == "HEADING_2":
                text_style["fontSize"] = {"magnitude": 13, "unit": "PT"}
                fields.append("fontSize")
            elif style_type == "HEADING_3":
                text_style["fontSize"] = {"magnitude": 11, "unit": "PT"}
                fields.append("fontSize")
            elif style_type == "CODE":
                text_style["fontSize"] = {"magnitude": 9.5, "unit": "PT"}
                fields.append("fontSize")

            if font_family:
                text_style["weightedFontFamily"] = {"fontFamily": font_family}
                fields.append("weightedFontFamily")
            elif style_type == "CODE":
                text_style["weightedFontFamily"] = {"fontFamily": "Consolas"}
                fields.append("weightedFontFamily")

            if color_rgb:
                text_style["foregroundColor"] = {
                    "color": {"rgbColor": {"red": color_rgb[0], "green": color_rgb[1], "blue": color_rgb[2]}}
                }
                fields.append("foregroundColor")
            elif style_type in ("TITLE", "HEADING_1"):
                text_style["foregroundColor"] = {
                    "color": {"rgbColor": {"red": 0.1, "green": 0.2, "blue": 0.5}}
                }
                fields.append("foregroundColor")
            elif style_type in ("HEADING_2", "HEADING_3"):
                text_style["foregroundColor"] = {
                    "color": {"rgbColor": {"red": 0.15, "green": 0.22, "blue": 0.35}}
                }
                fields.append("foregroundColor")

            if fields:
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "textStyle": text_style,
                        "fields": ",".join(fields)
                    }
                })

            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": requests}
            ).execute()
            return True
        except Exception as e:
            logger.warning(f"Failed to append styled block: {e}")
            return self.append_text(document_id, text)

    def create_academic_intro_page(
        self,
        document_id: str,
        lab_name: str,
        assignment_title: str,
        student_name: str,
        roll_no: str,
        section: str,
        teacher_name: str,
        submission_date: str,
        university_name: str = "AIR UNIVERSITY , ISLAMABAD"
    ) -> bool:
        """
        Build the standard Air University introductory cover page matching official template design.
        Includes Lab Name, Assignment Title, University Logo, Submitted by/to, Section, Date & Institution.
        """
        import os
        from pathlib import Path
        try:
            # 1. Lab / Course Name (Calibri 20pt, Centered)
            self.append_styled_block(
                document_id,
                f"{lab_name.strip()}\n",
                font_family="Calibri",
                font_size=20,
                bold=False,
                alignment="CENTER",
                space_above=12,
                space_below=6,
                color_rgb=(0, 0, 0)
            )

            # 2. Assignment / Lab No (Calibri 17pt, Bold, Centered)
            self.append_styled_block(
                document_id,
                f"{assignment_title.strip()}\n\n",
                font_family="Calibri",
                font_size=17,
                bold=True,
                alignment="CENTER",
                space_above=6,
                space_below=14,
                color_rgb=(0, 0, 0)
            )

            # 3. University Emblem / Logo
            logo_path = Path(__file__).resolve().parent.parent / "assets" / "university_logo.png"
            if logo_path.exists():
                try:
                    logo_bytes = logo_path.read_bytes()
                    self.insert_image_from_bytes(
                        document_id=document_id,
                        image_bytes=logo_bytes,
                        filename="air_university_logo.png",
                        width_pt=160
                    )
                    # Center paragraph containing the logo
                    end_idx = self.get_document_end_index(document_id)
                    try:
                        self.docs_service.documents().batchUpdate(
                            documentId=document_id,
                            body={"requests": [{
                                "updateParagraphStyle": {
                                    "range": {"startIndex": max(1, end_idx - 2), "endIndex": end_idx},
                                    "paragraphStyle": {"alignment": "CENTER", "spaceAbove": {"magnitude": 10, "unit": "PT"}, "spaceBelow": {"magnitude": 14, "unit": "PT"}},
                                    "fields": "alignment,spaceAbove,spaceBelow"
                                }
                            }]}
                        ).execute()
                    except Exception as align_err:
                        logger.debug(f"Could not center logo paragraph: {align_err}")
                except Exception as img_err:
                    logger.warning(f"Could not insert university logo image: {img_err}")
            
            # Spacer
            self.append_styled_block(document_id, "\n", font_size=10, space_below=6)

            # 4. Submitted by: (Calibri 16pt, Bold, Underlined, Centered)
            self.append_styled_block(
                document_id,
                "Submitted by:\n",
                font_family="Calibri",
                font_size=16,
                bold=True,
                underline=True,
                alignment="CENTER",
                space_above=12,
                space_below=6,
                color_rgb=(0, 0, 0)
            )

            # 5. Student Name (Calibri 14pt, Italic, Centered)
            self.append_styled_block(
                document_id,
                f"{student_name.strip()}\n\n",
                font_family="Calibri",
                font_size=14,
                italic=True,
                bold=False,
                alignment="CENTER",
                space_above=4,
                space_below=4,
                color_rgb=(0, 0, 0)
            )

            # 6. Roll No & Section (Calibri 14pt, Centered)
            roll_str = f"Roll No: {roll_no.strip()}" if not roll_no.lower().startswith("roll") else roll_no.strip()
            sec_str = f"Section: {section.strip()}" if not section.lower().startswith("section") else section.strip()
            self.append_styled_block(
                document_id,
                f"{roll_str}\n{sec_str}\n\n\n",
                font_family="Calibri",
                font_size=14,
                bold=False,
                alignment="CENTER",
                space_above=4,
                space_below=10,
                color_rgb=(0, 0, 0)
            )

            # 7. Submitted to: (Calibri 16pt, Bold, Underlined, Centered)
            self.append_styled_block(
                document_id,
                "Submitted to:\n",
                font_family="Calibri",
                font_size=16,
                bold=True,
                underline=True,
                alignment="CENTER",
                space_above=10,
                space_below=6,
                color_rgb=(0, 0, 0)
            )

            # 8. Teacher Name (Calibri 14pt, Italic, Centered)
            self.append_styled_block(
                document_id,
                f"{teacher_name.strip()}\n\n",
                font_family="Calibri",
                font_size=14,
                italic=True,
                bold=False,
                alignment="CENTER",
                space_above=4,
                space_below=6,
                color_rgb=(0, 0, 0)
            )

            # 9. Dated: (Calibri 14pt, Centered)
            dated_str = f"Dated: {submission_date.strip()}" if not submission_date.lower().startswith("dated") else submission_date.strip()
            self.append_styled_block(
                document_id,
                f"{dated_str}\n\n\n",
                font_family="Calibri",
                font_size=14,
                bold=False,
                alignment="CENTER",
                space_above=4,
                space_below=16,
                color_rgb=(0, 0, 0)
            )

            # 10. AIR UNIVERSITY , ISLAMABAD (Calibri 14pt, Centered)
            self.append_styled_block(
                document_id,
                f"{university_name.strip().upper()}\n",
                font_family="Calibri",
                font_size=14,
                bold=True,
                alignment="CENTER",
                space_above=8,
                space_below=12,
                color_rgb=(0, 0, 0)
            )

            # 11. Dedicated Page Break after Cover Page
            self.insert_page_break(document_id)
            return True
        except Exception as e:
            logger.error(f"Error creating academic intro page on doc {document_id}: {e}")
            return False

    def insert_image_from_bytes(
        self,
        document_id: str,
        image_bytes: bytes,
        filename: str = "screenshot.png",
        index: Optional[int] = None,
        width_pt: float = 460
    ) -> bool:
        """Upload image bytes to Google Drive and insert as inline image into the Google Doc."""
        if not image_bytes or not self.drive_service or not self.docs_service:
            return False
        try:
            file_meta = self.upload_file(name=filename, content=image_bytes, mime_type="image/png")
            if not file_meta or not file_meta.get("id"):
                logger.warning(f"Failed to upload screenshot image {filename} to Google Drive")
                return False
            file_id = file_meta["id"]

            # Make public reader so Docs API can fetch the image URL
            try:
                self.drive_service.permissions().create(
                    fileId=file_id,
                    body={"role": "reader", "type": "anyone"}
                ).execute()
            except Exception as perm_err:
                logger.warning(f"Could not set public permissions on drive file {file_id}: {perm_err}")

            target_index = index if index is not None else self.get_document_end_index(document_id)
            image_uri = f"https://lh3.googleusercontent.com/d/{file_id}"
            
            requests = [{
                "insertInlineImage": {
                    "location": {"index": target_index},
                    "uri": image_uri,
                    "objectSize": {
                        "width": {"magnitude": width_pt, "unit": "PT"}
                    }
                }
            }]
            self.docs_service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": requests}
            ).execute()
            logger.info(f"Successfully inserted image {filename} into doc {document_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to insert image into Google Doc {document_id}: {e}")
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
        """Download file content, automatically exporting Google Docs/Sheets/Slides to PDF."""
        try:
            # Check metadata to handle native Google Workspace formats
            meta = self.get_file(file_id)
            mime_type = meta.get("mimeType", "") if meta else ""

            if mime_type.startswith("application/vnd.google-apps."):
                if "folder" in mime_type:
                    logger.warning(f"File {file_id} is a Google Drive folder; cannot download as binary.")
                    return None
                
                export_mime = "application/pdf"
                logger.info(f"Exporting Google Workspace doc {file_id} ({mime_type}) to {export_mime}")
                try:
                    request = self.drive_service.files().export_media(fileId=file_id, mimeType=export_mime)
                    file_io = io.BytesIO()
                    downloader = MediaIoBaseDownload(file_io, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                    return file_io.getvalue()
                except Exception as export_err:
                    logger.debug(f"export_media fallback to direct export for {file_id}: {export_err}")
                    return self.drive_service.files().export(fileId=file_id, mimeType=export_mime).execute()

            # Binary file download (PDF, DOCX, ZIP, images, etc.)
            request = self.drive_service.files().get_media(fileId=file_id)
            file_io = io.BytesIO()
            downloader = MediaIoBaseDownload(file_io, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            return file_io.getvalue()
        except HttpError as e:
            if "Only files with binary content can be downloaded" in str(e):
                try:
                    logger.info(f"Retrying download of {file_id} via export_media to PDF...")
                    return self.drive_service.files().export(fileId=file_id, mimeType="application/pdf").execute()
                except Exception as inner_e:
                    logger.error(f"Fallback export failed for {file_id}: {inner_e}")
            logger.error(f"Error downloading file {file_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading file {file_id}: {e}")
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

    def download_file(self, file_id: str) -> Optional[bytes]:
        """Download binary file content from Google Drive"""
        try:
            request = self.drive_service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            return fh.getvalue()
        except Exception as e:
            logger.error(f"Error downloading file {file_id} from Drive: {e}")
            return None


def get_google_docs_service(db: Session = None) -> Optional[GoogleDocsService]:
    if db is None:
        db = next(get_db())
    service = GoogleDocsService(db)
    return service if service.docs_service else None