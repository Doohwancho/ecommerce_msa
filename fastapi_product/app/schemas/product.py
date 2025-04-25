from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

class Price(BaseModel):
    amount: float
    currency: str

class Weight(BaseModel):
    value: float
    unit: str

class Dimensions(BaseModel):
    length: float
    width: float
    height: float
    unit: str

class Image(BaseModel):
    url: str
    main: bool

class Variant(BaseModel):
    id: str
    sku: str
    color: str
    storage: str
    price: Price
    attributes: Dict[str, str]
    inventory: int

class ProductCreate(BaseModel):
    title: str
    description: str
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    color: Optional[str] = None
    category_ids: List[int] = []
    primary_category_id: Optional[int] = None
    category_breadcrumbs: Optional[List[str]] = None
    price: Price
    stock: int = Field(default=0, ge=0)
    weight: Optional[Weight] = None
    dimensions: Optional[Dimensions] = None
    attributes: Optional[Dict[str, str]] = None
    variants: Optional[List[Variant]] = None
    images: Optional[List[Image]] = None

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    color: Optional[str] = None
    category_ids: Optional[List[int]] = None
    primary_category_id: Optional[int] = None
    category_breadcrumbs: Optional[List[str]] = None
    price: Optional[Price] = None
    stock: Optional[int] = Field(default=None, ge=0)
    weight: Optional[Weight] = None
    dimensions: Optional[Dimensions] = None
    attributes: Optional[Dict[str, str]] = None
    variants: Optional[List[Variant]] = None
    images: Optional[List[Image]] = None

class ProductResponse(BaseModel):
    product_id: str
    title: str
    description: str
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    color: Optional[str] = None
    category_ids: List[int] = []
    primary_category_id: Optional[int] = None
    category_breadcrumbs: Optional[List[str]] = None
    price: Price
    weight: Optional[Weight] = None
    dimensions: Optional[Dimensions] = None
    attributes: Optional[Dict[str, str]] = None
    variants: Optional[List[Variant]] = None
    images: Optional[List[Image]] = None
    created_at: Optional[datetime] = None

class ProductInventoryResponse(BaseModel):
    product_id: str
    stock: int = Field(default=0, ge=0)
    stock_reserved: int = Field(default=0, ge=0)
    available_stock: int = Field(default=0, ge=0)  # stock - stock_reserved

class ProductsExistRequest(BaseModel):
    product_ids: List[str]

class ProductsExistResponse(BaseModel):
    existing_ids: List[str]
    missing_ids: List[str]

# class ConfirmInventoryResponse(BaseModel):
#     success: bool
#     message: str
