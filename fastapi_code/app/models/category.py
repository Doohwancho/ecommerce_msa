from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.config.database import Base

class Category(Base):
    """
    카테고리 계층 구조를 관리하는 테이블
    - level: 카테고리 깊이 (최상위=0, 하위=1, 그 다음 하위=2...)
    - path: 전체 경로를 저장 (예: "1/4/28")
    """
    __tablename__ = 'categories'
    
    category_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    parent_id = Column(Integer, ForeignKey('categories.category_id', ondelete='CASCADE'), nullable=True)
    level = Column(Integer, nullable=False, default=0)
    path = Column(String(255), nullable=False)
    
    # 인덱스 생성
    __table_args__ = (
        Index('idx_parent', 'parent_id'),
        Index('idx_path', 'path'),
    )
    
    # 관계 설정
    children = relationship("Category", 
                           backref="parent", 
                           remote_side=[category_id],
                           cascade="all, delete-orphan",
                           single_parent=True)
    products = relationship("ProductCategory", back_populates="category")


class ProductCategory(Base):
    """
    상품과 카테고리 간의 다대다 관계를 관리하는 테이블
    - is_primary: 상품의 주 카테고리인지 여부
    """
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
