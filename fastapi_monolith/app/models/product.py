from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ProductDimension(BaseModel):
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    dimensionUnit: Optional[str] = "INCH"

class ProductWeight(BaseModel):
    value: float
    unit: str = "OUNCE"

class ProductPrice(BaseModel):
    regular: float
    sale: Optional[float] = None
    currency: str = "USD"

class ProductVariant(BaseModel):
    sku: str
    color: Optional[str] = None
    size: Optional[str] = None
    storage: Optional[str] = None
    price: float
    inventory: int = 0

class ProductImage(BaseModel):
    url: str
    main: bool = False

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
