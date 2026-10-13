from .common import *
from .enums import *


class GoogleCredential(Base):
    __tablename__ = "google_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, unique=True, index=True, default="legacy")
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    token_uri = Column(String(500))
    client_id = Column(String(500))
    client_secret = Column(String(500))
    scopes = Column(Text)
    expiry = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
