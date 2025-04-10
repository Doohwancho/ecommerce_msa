from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class CategoryBase(BaseModel):
    name: str
    parent_id: Optional[int] = None

class CategoryCreate(CategoryBase):
    pass

class CategoryResponse(BaseModel):
    category_id: int
    name: str
    parent_id: Optional[int]
    level: int
    path: str

    class Config:
        orm_mode = True

class ProductCategoryBase(BaseModel):
    product_id: str
    category_id: int
    is_primary: bool = False

class ProductCategoryResponse(BaseModel):
    product_id: str
    category_id: int
    is_primary: bool
    category: CategoryResponse

    class Config:
        orm_mode = True