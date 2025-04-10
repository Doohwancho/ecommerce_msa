from pydantic import BaseModel

class UserBase(BaseModel):
    name: str
    age: int
    occupation: str
    learning: str

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: str

    class Config:
        orm_mode = True