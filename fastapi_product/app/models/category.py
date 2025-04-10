from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from app.config.database import Base

class Category(Base):
    __tablename__ = 'categories'
    
    category_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey('categories.category_id', ondelete='SET NULL'), nullable=True)
    level = Column(Integer, nullable=False, default=0)
    path = Column(String(255), nullable=False)
    
    # 관계 설정
    products = relationship("ProductCategory", back_populates="category", cascade="all, delete-orphan")

class ProductCategory(Base):
    """상품과 카테고리 간의 다대다 관계를 관리하는 테이블"""
    __tablename__ = 'product_categories'
    
    product_id = Column(String(24), primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.category_id', ondelete='CASCADE'), primary_key=True)
    is_primary = Column(Boolean, default=False)
    
    # 인덱스 생성
    __table_args__ = (
        Index('idx_category', 'category_id'),
        Index('idx_product', 'product_id'),
        Index('idx_primary', 'is_primary'),
    )
    
    # 관계 설정
    category = relationship("Category", back_populates="products")