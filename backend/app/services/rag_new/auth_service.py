from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.token import TokenResponse
from app.schemas.user import UserResponse


class AuthService:

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    @staticmethod
    def _token_response(user: User) -> TokenResponse:
        access_token = create_access_token(
            subject=user.id,
            extra_claims={"role": user.role.value},
        )
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )

    def register(self, data: RegisterRequest) -> TokenResponse:
        existing_user = self.user_repository.get_by_email(data.email)

        if existing_user:
            raise ConflictError("Email already registered")

        password_hash = hash_password(data.password)

        user = self.user_repository.create(
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            password_hash=password_hash,
        )

        return self._token_response(user)

    def login(self, data: LoginRequest) -> TokenResponse:
        user = self.user_repository.get_by_email(data.email)
        if user is None:
            raise UnauthorizedError("Incorrect email or password")

        if not verify_password(data.password, user.password_hash):
            raise UnauthorizedError("Incorrect email or password")

        if not user.is_active:
            raise UnauthorizedError("Account is inactive")

        return self._token_response(user)

    def get_me(self, user_id: int) -> User:
        user = self.user_repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")

        return user
