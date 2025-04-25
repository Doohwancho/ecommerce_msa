from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.config.database import Base

class Product(Base):
    """상품 모델"""
    __tablename__ = "products"

    product_id = Column(String(50), primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    price = Column(Integer, nullable=False)
    stock = Column(Integer, default=0)
    stock_reserved = Column(Integer, default=0)  # 예약된 재고
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    categories = relationship("ProductCategory", back_populates="product")

class Category(Base):
    """카테고리 모델"""
    __tablename__ = "categories"

    category_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.category_id"), nullable=True)
    level = Column(Integer, default=0)
    path = Column(String(255), nullable=False)

    # Relationships
    parent = relationship("Category", remote_side=[category_id], backref="children")
    products = relationship("ProductCategory", back_populates="category")

class ProductCategory(Base):
    """상품-카테고리 연결 모델"""
    __tablename__ = "product_categories"

    product_id = Column(String(50), ForeignKey("products.product_id"), primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.category_id"), primary_key=True)
    is_primary = Column(Boolean, default=False)

    # Relationships
    product = relationship("Product", back_populates="categories")
    category = relationship("Category", back_populates="products")