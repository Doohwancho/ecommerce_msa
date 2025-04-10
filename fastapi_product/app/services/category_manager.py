from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.category import Category, ProductCategory
from app.config.logging import logger

class CategoryManager:
    def __init__(self, db_session: Session):
        self.session = db_session
    
    def create_category(self, name: str, parent_id: Optional[int] = None):
        """새 카테고리 생성"""
        try:
            if parent_id is None:
                # 최상위 카테고리 생성
                new_category = Category(
                    name=name,
                    level=0,
                    path=""  # 임시 path
                )
                self.session.add(new_category)
                self.session.flush()  # ID 생성을 위해 flush
                
                # path 업데이트
                new_category.path = str(new_category.category_id)
                
            else:
                # 하위 카테고리 생성
                parent = self.session.query(Category).filter_by(category_id=parent_id).one()
                
                new_category = Category(
                    name=name,
                    parent_id=parent_id,
                    level=parent.level + 1,
                    path=""  # 임시 path
                )
                self.session.add(new_category)
                self.session.flush()  # ID 생성을 위해 flush
                
                # path 업데이트
                new_category.path = f"{parent.path}/{new_category.category_id}"
            
            self.session.commit()
            return new_category
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error creating category: {str(e)}")
            raise e
    
    def get_subcategories(self, category_id: int) -> List[Category]:
        """특정 카테고리의 모든 하위 카테고리 조회"""
        parent = self.session.query(Category).filter_by(category_id=category_id).one()
        return self.session.query(Category).filter(
            Category.path.like(f"{parent.path}/%")
        ).all()
    
    def get_category(self, category_id: int) -> Category:
        """카테고리 ID로 카테고리 조회"""
        return self.session.query(Category).filter_by(category_id=category_id).one()
    
    def get_categories(self) -> List[Category]:
        """모든 카테고리 조회"""
        return self.session.query(Category).all()
    
    def associate_product_with_category(self, product_id: str, category_id: int, is_primary: bool = False):
        """상품을 카테고리와 연결"""
        # 이미 연결이 있는지 확인
        existing = self.session.query(ProductCategory).filter_by(
            product_id=product_id, category_id=category_id
        ).first()
        
        if existing:
            # 이미 연결이 있으면 is_primary만 업데이트
            existing.is_primary = is_primary
        else:
            # 새 연결 생성
            product_category = ProductCategory(
                product_id=product_id,
                category_id=category_id,
                is_primary=is_primary
            )
            self.session.add(product_category)
        
        # 다른 카테고리가 주 카테고리로 설정되어 있는 경우 처리
        if is_primary:
            self.session.query(ProductCategory).filter(
                ProductCategory.product_id == product_id,
                ProductCategory.category_id != category_id
            ).update({ProductCategory.is_primary: False})
        
        self.session.commit()
    
    def get_products_in_category(self, category_id: int) -> List[str]:
        """카테고리에 속한 모든 상품 ID 목록 조회"""
        products = self.session.query(ProductCategory.product_id).filter_by(
            category_id=category_id
        ).all()
        return [p[0] for p in products]
    
    def get_products_in_category_with_subcategories(self, category_id: int) -> List[str]:
        """카테고리와 모든 하위 카테고리에 속한 상품 ID 목록 조회"""
        # 현재 카테고리 및 모든 하위 카테고리 가져오기
        parent = self.session.query(Category).filter_by(category_id=category_id).one()
        subcategory_ids = [category_id]
        
        subcategories = self.session.query(Category).filter(
            Category.path.like(f"{parent.path}/%")
        ).all()
        
        for subcategory in subcategories:
            subcategory_ids.append(subcategory.category_id)
        
        # 모든 관련 카테고리에서 상품 조회
        products = self.session.query(ProductCategory.product_id).filter(
            ProductCategory.category_id.in_(subcategory_ids)
        ).distinct().all()
        
        return [p[0] for p in products]