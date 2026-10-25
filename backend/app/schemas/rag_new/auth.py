from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=2, max_length=50)

    last_name: str = Field(min_length=2, max_length=50)

    email: EmailStr

    password: str = Field(min_length=8, max_length=128)

    confirm_password: str

    @model_validator(mode="after")
    def validate_passwords(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")

        return self


class LoginRequest(BaseModel):
    email: EmailStr

    password: str