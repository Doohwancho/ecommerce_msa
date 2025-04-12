from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ProductWeight(BaseModel):
    value: float
    unit: str

class ProductDimension(BaseModel):
    length: float
    width: float
    height: float
    unit: str

class ProductPrice(BaseModel):
    amount: float
    currency: str = "USD"

class ProductImage(BaseModel):
    url: str
    alt: Optional[str] = None
    position: Optional[int] = None

class ProductVariant(BaseModel):
    id: str
    attributes: Dict[str, Any]
    price: Optional[ProductPrice] = None
    stock: Optional[int] = None
    images: Optional[List[ProductImage]] = None

class Product(BaseModel):
    product_id: str
    title: str
    description: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    
    # 식별 정보
    upc: Optional[str] = None
    ean: Optional[str] = None
    asin: Optional[str] = None
    
    # 물리적 특성
    color: Optional[str] = None
    weight: Optional[ProductWeight] = None
    dimensions: Optional[ProductDimension] = None
    
    # 가격 및 판매 정보
    price: ProductPrice
    stock: Optional[int] = None
    discount: Optional[float] = None
    estimated_sales_revenue: Optional[float] = None
    estimated_unit_sold: Optional[int] = None
    
    # 카테고리 정보
    category_ids: List[int] = []
    primary_category_id: Optional[int] = None
    category_breadcrumbs: Optional[List[str]] = None
    
    # 추가 정보
    attributes: Dict[str, Any] = {}
    variants: List[ProductVariant] = []
    images: List[ProductImage] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None