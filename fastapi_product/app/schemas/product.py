from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.models.product import ProductWeight, ProductDimension, ProductPrice, ProductImage, ProductVariant

class ProductCreate(BaseModel):
    title: str
    description: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    ean: Optional[str] = None
    asin: Optional[str] = None
    color: Optional[str] = None
    weight: Optional[ProductWeight] = None
    dimensions: Optional[ProductDimension] = None
    price: ProductPrice
    discount: Optional[float] = None
    estimated_sales_revenue: Optional[float] = None
    estimated_unit_sold: Optional[int] = None
    category_ids: List[int] = []
    primary_category_id: Optional[int] = None
    attributes: Dict[str, Any] = {}
    variants: List[ProductVariant] = []
    images: List[ProductImage] = []

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    ean: Optional[str] = None
    asin: Optional[str] = None
    color: Optional[str] = None
    weight: Optional[ProductWeight] = None
    dimensions: Optional[ProductDimension] = None
    price: Optional[ProductPrice] = None
    discount: Optional[float] = None
    estimated_sales_revenue: Optional[float] = None
    estimated_unit_sold: Optional[int] = None
    category_ids: Optional[List[int]] = None
    primary_category_id: Optional[int] = None
    attributes: Optional[Dict[str, Any]] = None
    variants: Optional[List[ProductVariant]] = None
    images: Optional[List[ProductImage]] = None

class ProductResponse(BaseModel):
    product_id: str
    title: str
    description: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    ean: Optional[str] = None
    asin: Optional[str] = None
    color: Optional[str] = None
    weight: Optional[ProductWeight] = None
    dimensions: Optional[ProductDimension] = None
    price: ProductPrice
    discount: Optional[float] = None
    estimated_sales_revenue: Optional[float] = None
    estimated_unit_sold: Optional[int] = None
    category_ids: List[int] = []
    primary_category_id: Optional[int] = None
    category_breadcrumbs: Optional[List[str]] = None
    attributes: Dict[str, Any] = {}
    variants: List[ProductVariant] = []
    images: List[ProductImage] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ProductsExistRequest(BaseModel):
    product_ids: List[str]

class ProductsExistResponse(BaseModel):
    existing_ids: List[str]
    missing_ids: List[str]