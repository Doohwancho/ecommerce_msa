# app/schemas/user.py
from pydantic import BaseModel

class User(BaseModel):
    Name: str
    Age: int
    Occupation: str
    Learning: str