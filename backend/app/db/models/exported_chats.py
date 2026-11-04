"""Persistent exported web AI chats (ChatGPT, Claude, Gemini)."""

from .common import *


class ExportedChat(Base):
    __tablename__ = "exported_chats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source_platform = Column(String(50), nullable=False, default="chatgpt")  # 'chatgpt' | 'claude' | 'gemini' | 'generic'
    source_url = Column(String(1000), nullable=False)
    is_public = Column(Boolean, nullable=False, default=True)
    turn_count = Column(Integer, nullable=False, default=0)
    has_images = Column(Boolean, nullable=False, default=False)
    has_diagrams = Column(Boolean, nullable=False, default=False)
    file_path = Column(String(1000), nullable=False)  # Local storage path or relative URL
    file_url = Column(String(1000), nullable=True)    # Download URL or S3 URL
    google_drive_file_id = Column(String(255), nullable=True)
    file_size_bytes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def google_drive_url(self):
        if not self.google_drive_file_id:
            return None
        return f"https://drive.google.com/file/d/{self.google_drive_file_id}/view"

