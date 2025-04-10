from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class ProductDimensionSchema(BaseModel):
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    dimensionUnit: Optional[str] = "INCH"

class ProductWeightSchema(BaseModel):
    value: float
    unit: str = "OUNCE"

class ProductPriceSchema(BaseModel):
    regular: float
    sale: Optional[float] = None
    currency: str = "USD"

class ProductVariantSchema(BaseModel):
    sku: str
    color: Optional[str] = None
    size: Optional[str] = None
    storage: Optional[str] = None
    price: float
    inventory: int = 0

class ProductImageSchema(BaseModel):
    url: str
    main: bool = False

class ProductBase(BaseModel):
    title: str
    description: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    sku: Optional[str] = None
    upc: Optional[str] = None
    ean: Optional[str] = None
    asin: Optional[str] = None
    color: Optional[str] = None
    
    category_ids: List[int] = []
    primary_category_id: Optional[int] = None
    category_breadcrumbs: Optional[List[str]] = None

class ProductCreate(ProductBase):
    price: ProductPriceSchema
    weight: Optional[ProductWeightSchema] = None
    dimensions: Optional[ProductDimensionSchema] = None
    attributes: Dict[str, Any] = {}
    variants: List[ProductVariantSchema] = []
    images: List[ProductImageSchema] = []

class ProductUpdate(ProductBase):
    price: Optional[ProductPriceSchema] = None
    weight: Optional[ProductWeightSchema] = None
    dimensions: Optional[ProductDimensionSchema] = None
    attributes: Optional[Dict[str, Any]] = None
    variants: Optional[List[ProductVariantSchema]] = None
    images: Optional[List[ProductImageSchema]] = None
    discount: Optional[float] = None
    estimated_sales_revenue: Optional[float] = None
    estimated_unit_sold: Optional[int] = None

class ProductResponse(ProductBase):
    product_id: str
    price: ProductPriceSchema
    weight: Optional[ProductWeightSchema] = None
    dimensions: Optional[ProductDimensionSchema] = None
    discount: Optional[float] = None
    estimated_sales_revenue: Optional[float] = None
    estimated_unit_sold: Optional[int] = None
    attributes: Dict[str, Any] = {}
    variants: List[ProductVariantSchema] = []
    images: List[ProductImageSchema] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
