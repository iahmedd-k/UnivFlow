from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User, UserRole


class UserRepository:

    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)

        return self.db.scalar(statement)

    def get_by_id(self, user_id: int) -> User | None:
        statement = select(User).where(User.id == user_id)

        return self.db.scalar(statement)

    def create(
        self,
        first_name: str,
        last_name: str,
        email: str,
        password_hash: str,
        role: UserRole = UserRole.USER,
    ) -> User:

        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password_hash=password_hash,
            role=role,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user

    def set_role(self, user: User, role: UserRole) -> User:
        user.role = role
        self.db.commit()
        self.db.refresh(user)

        return user
