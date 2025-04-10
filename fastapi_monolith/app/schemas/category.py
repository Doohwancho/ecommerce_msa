from typing import Optional, List
from pydantic import BaseModel

class CategoryBase(BaseModel):
    name: str

class CategoryCreate(CategoryBase):
    parent_id: Optional[int] = None

class CategoryResponse(CategoryBase):
    category_id: int
    parent_id: Optional[int]
    level: int
    path: str

    class Config:
        orm_mode = True

class ProductCategoryBase(BaseModel):
    product_id: str
    category_id: int
    is_primary: bool = False

class ProductCategoryResponse(ProductCategoryBase):
    class Config:
        orm_mode = True
