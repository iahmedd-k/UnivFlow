import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TemplatePlaceholder:
    key: str
    value: str
    description: str


class GoogleDocsTemplateEngine:
    """
    Handles Google Docs template processing:
    1. Fetch user's template
    2. Replace placeholders with user/assignment data
    3. Insert solution content
    4. Apply formatting
    5. Create new document in user's Drive
    """
    
    DEFAULT_PLACEHOLDERS = {
        "STUDENT_NAME": "Student's full name",
        "STUDENT_ID": "Student ID number",
        "COURSE_NAME": "Course full name",
        "COURSE_CODE": "Course code (e.g., CS101)",
        "ASSIGNMENT_TITLE": "Assignment title",
        "INSTRUCTOR_NAME": "Instructor/Professor name",
        "SUBMISSION_DATE": "Date of submission (formatted)",
        "DUE_DATE": "Assignment due date",
        "UNIVERSITY_NAME": "University name",
        "SEMESTER": "Current semester/term",
        "SECTION": "Course section",
        "EMAIL": "Student email",
        "SOLUTION_CONTENT": "Main solution content (auto-filled)",
    }
    
    def __init__(self, drive_service=None, docs_service=None):
        self.drive_service = drive_service
        self.docs_service = docs_service
    
    def set_services(self, drive_service, docs_service):
        self.drive_service = drive_service
        self.docs_service = docs_service
    
    async def create_submission_document(
        self,
        template_doc_id: str,
        placeholders: Dict[str, str],
        solution_content: str,
        assignment_metadata: Dict[str, Any],
        user_metadata: Dict[str, Any],
        destination_folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new Google Doc from template with filled placeholders.
        
        Returns: {doc_id, url, drive_file_id, title}
        """
        if not self.drive_service or not self.docs_service:
            raise ValueError("Google Drive and Docs services not configured")
        
        # 1. Copy template to new document
        new_title = self._generate_document_title(assignment_metadata, user_metadata)
        
        copied_file = self.drive_service.files().copy(
            fileId=template_doc_id,
            body={"name": new_title, "parents": [destination_folder_id] if destination_folder_id else []}
        ).execute()
        
        new_doc_id = copied_file["id"]
        drive_file_id = copied_file["id"]
        
        # 2. Prepare all replacements
        all_replacements = self._prepare_replacements(
            placeholders, solution_content, assignment_metadata, user_metadata
        )
        
        # 3. Apply replacements to document
        await self._apply_replacements(new_doc_id, all_replacements)
        
        # 4. Insert solution content at placeholder location
        await self._insert_solution_content(new_doc_id, solution_content)
        
        # 5. Apply formatting
        await self._apply_formatting(new_doc_id, assignment_metadata)
        
        # 6. Get document URL
        doc = self.docs_service.documents().get(documentId=new_doc_id).execute()
        
        return {
            "doc_id": new_doc_id,
            "url": f"https://docs.google.com/document/d/{new_doc_id}/edit",
            "drive_file_id": drive_file_id,
            "title": new_title,
            "editable_url": f"https://docs.google.com/document/d/{new_doc_id}/edit?usp=sharing"
        }
    
    def _generate_document_title(
        self,
        assignment_metadata: Dict[str, Any],
        user_metadata: Dict[str, Any]
    ) -> str:
        """Generate document title."""
        assignment_title = assignment_metadata.get("title", "Assignment")
        student_name = user_metadata.get("name", "Student")
        date_str = datetime.now().strftime("%Y-%m-%d")
        course_code = assignment_metadata.get("course_code", "")
        
        return f"{assignment_title} - {student_name} - {course_code} - {date_str}"
    
    def _prepare_replacements(
        self,
        user_placeholders: Dict[str, str],
        solution_content: str,
        assignment_metadata: Dict[str, Any],
        user_metadata: Dict[str, Any]
    ) -> Dict[str, str]:
        """Prepare all placeholder replacements."""
        replacements = {}
        
        # Default placeholders from user metadata
        defaults = {
            "STUDENT_NAME": user_metadata.get("name", ""),
            "STUDENT_ID": user_metadata.get("student_id", ""),
            "EMAIL": user_metadata.get("email", ""),
            "UNIVERSITY_NAME": user_metadata.get("university", ""),
        }
        
        # Assignment metadata
        assignment_defaults = {
            "COURSE_NAME": assignment_metadata.get("course_name", ""),
            "COURSE_CODE": assignment_metadata.get("course_code", ""),
            "ASSIGNMENT_TITLE": assignment_metadata.get("title", ""),
            "INSTRUCTOR_NAME": assignment_metadata.get("instructor", ""),
            "DUE_DATE": self._format_date(assignment_metadata.get("due_date")),
            "SEMESTER": assignment_metadata.get("semester", ""),
            "SECTION": assignment_metadata.get("section", ""),
        }
        
        # Current date
        defaults["SUBMISSION_DATE"] = datetime.now().strftime("%B %d, %Y")
        
        # Merge: user placeholders override defaults
        replacements.update(defaults)
        replacements.update(assignment_defaults)
        replacements.update(user_placeholders)
        
        # Solution content placeholder
        replacements["SOLUTION_CONTENT"] = solution_content
        
        return replacements
    
    def _format_date(self, date_value: Any) -> str:
        """Format date for display."""
        if not date_value:
            return ""
        if isinstance(date_value, str):
            try:
                date_value = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
            except:
                return date_value
        if isinstance(date_value, datetime):
            return date_value.strftime("%B %d, %Y")
        return str(date_value)
    
    async def _apply_replacements(self, doc_id: str, replacements: Dict[str, str]):
        """Apply all placeholder replacements using batchUpdate."""
        requests = []
        
        for placeholder, value in replacements.items():
            if not value:
                continue
            
            # Search for placeholder pattern: {{PLACEHOLDER}} or {PLACEHOLDER}
            patterns = [
                f"{{{{{placeholder}}}}}",
                f"{{{placeholder}}}",
                f"[[{placeholder}]]",
                f"{{{{ {placeholder} }}}}"  # With spaces
            ]
            
            for pattern in patterns:
                requests.append({
                    "replaceAllText": {
                        "containsText": {
                            "text": pattern,
                            "matchCase": False
                        },
                        "replaceText": value
                    }
                })
        
        if requests:
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests}
            ).execute()
    
    async def _insert_solution_content(self, doc_id: str, solution_content: str):
        """Insert solution content at the SOLUTION_CONTENT placeholder location."""
        # First, find the placeholder location
        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        
        placeholder_index = self._find_placeholder_index(doc, "SOLUTION_CONTENT")
        
        if placeholder_index is not None:
            # Replace placeholder with actual content
            requests = [
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": placeholder_index,
                            "endIndex": placeholder_index + len("{{SOLUTION_CONTENT}}")
                        }
                    }
                },
                {
                    "insertText": {
                        "location": {"index": placeholder_index},
                        "text": solution_content
                    }
                }
            ]
            
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests}
            ).execute()
        else:
            # Append to end of document
            end_index = self._get_document_end_index(doc)
            requests = [{
                "insertText": {
                    "location": {"index": end_index},
                    "text": f"\n\n---\n\n{solution_content}"
                }
            }]
            
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests}
            ).execute()
    
    def _find_placeholder_index(self, doc: Dict, placeholder: str) -> Optional[int]:
        """Find the start index of a placeholder in the document."""
        patterns = [f"{{{{{placeholder}}}}}", f"{{{placeholder}}}"]
        
        content = doc.get("body", {}).get("content", [])
        
        for element in content:
            if "paragraph" in element:
                for pe in element["paragraph"].get("elements", []):
                    if "textRun" in pe:
                        text = pe["textRun"].get("content", "")
                        for pattern in patterns:
                            idx = text.find(pattern)
                            if idx >= 0:
                                return pe.get("startIndex", 0) + idx
        return None
    
    def _get_document_end_index(self, doc: Dict) -> int:
        """Get the end index of the document body."""
        content = doc.get("body", {}).get("content", [])
        if not content:
            return 1
        last_element = content[-1]
        return last_element.get("endIndex", 1) - 1
    
    async def _apply_formatting(
        self,
        doc_id: str,
        assignment_metadata: Dict[str, Any]
    ):
        """Apply consistent formatting to the document."""
        requests = []
        
        # Get document to analyze structure
        doc = self.docs_service.documents().get(documentId=doc_id).execute()
        content = doc.get("body", {}).get("content", [])
        
        # Apply default styling to solution content area
        # This is a simplified version - in production, you'd want more sophisticated formatting
        
        if requests:
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests}
            ).execute()
    
    async def update_document_content(
        self,
        doc_id: str,
        updates: Dict[str, str]
    ) -> bool:
        """Update specific content in an existing document."""
        requests = []
        
        for placeholder, value in updates.items():
            patterns = [f"{{{{{placeholder}}}}}", f"{{{placeholder}}}"]
            for pattern in patterns:
                requests.append({
                    "replaceAllText": {
                        "containsText": {"text": pattern, "matchCase": False},
                        "replaceText": value
                    }
                })
        
        if requests:
            self.docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": requests}
            ).execute()
        
        return True
    
    def get_default_template_structure(self) -> str:
        """Return a default template structure as text (for creating new templates)."""
        return """{{UNIVERSITY_LOGO}}

{{UNIVERSITY_NAME}}

{{COURSE_NAME}} ({{COURSE_CODE}})
{{SEMESTER}} - Section {{SECTION}}

{{ASSIGNMENT_TITLE}}

Submitted by: {{STUDENT_NAME}}
Student ID: {{STUDENT_ID}}
Email: {{EMAIL}}
Instructor: {{INSTRUCTOR_NAME}}
Date Submitted: {{SUBMISSION_DATE}}
Due Date: {{DUE_DATE}}

---

{{SOLUTION_CONTENT}}

---

Declaration: I certify that this work is my own and all sources have been properly acknowledged.

Signature: _________________________  Date: {{SUBMISSION_DATE}}"""
    
    async def create_default_template(
        self,
        user_id: str,
        user_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a default template for a user."""
        if not self.drive_service or not self.docs_service:
            raise ValueError("Google services not configured")
        
        template_content = self.get_default_template_structure()
        
        # Create new document
        doc = self.docs_service.documents().create(
            body={"title": f"Uniflow Template - {user_metadata.get('name', 'User')}"}
        ).execute()
        
        doc_id = doc["documentId"]
        
        # Insert template content
        requests = [{
            "insertText": {
                "location": {"index": 1},
                "text": template_content
            }
        }]
        
        self.docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()
        
        # Move to user's Uniflow folder
        folder_id = await self._get_or_create_uniflow_folder(user_id)
        self.drive_service.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents="root"
        ).execute()
        
        return {
            "doc_id": doc_id,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "title": doc["title"]
        }
    
    async def _get_or_create_uniflow_folder(self, user_id: str) -> str:
        """Get or create the Uniflow folder in user's Drive."""
        # Search for existing folder
        results = self.drive_service.files().list(
            q="name='Uniflow' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive"
        ).execute()
        
        folders = results.get("files", [])
        if folders:
            return folders[0]["id"]
        
        # Create folder
        folder = self.drive_service.files().create(
            body={
                "name": "Uniflow",
                "mimeType": "application/vnd.google-apps.folder"
            }
        ).execute()
        
        # Create subfolders
        for subfolder_name in ["Assignments", "Templates", "Archived"]:
            subfolder = self.drive_service.files().create(
                body={
                    "name": subfolder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [folder["id"]]
                }
            ).execute()
        
        return folder["id"]