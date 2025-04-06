from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.category import Category, ProductCategory

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
            raise e
    
    def get_subcategories(self, category_id: int) -> List[Category]:
        """특정 카테고리의 모든 하위 카테고리 조회"""
        parent = self.session.query(Category).filter_by(category_id=category_id).one()
        return self.session.query(Category).filter(
            Category.path.like(f"{parent.path}/%")
        ).all()
    
    def get_ancestors(self, category_id: int) -> List[Category]:
        """특정 카테고리의 모든 상위 카테고리 조회"""
        category = self.session.query(Category).filter_by(category_id=category_id).one()
        
        # path에서 ID 추출
        path_ids = category.path.split("/")
        ancestors = []
        
        # 마지막 ID는 현재 카테고리이므로 제외
        for ancestor_id in path_ids[:-1]:
            ancestor = self.session.query(Category).filter_by(category_id=int(ancestor_id)).one()
            ancestors.append(ancestor)
        
        return ancestors
    
    def move_category(self, category_id: int, new_parent_id: Optional[int] = None) -> bool:
        """카테고리 이동 (다른 부모 아래로)"""
        try:
            category = self.session.query(Category).filter_by(category_id=category_id).one()
            old_path = category.path
            
            if new_parent_id is None:
                # 최상위 카테고리로 이동
                category.parent_id = None
                category.level = 0
                category.path = str(category.category_id)
            else:
                # 다른 부모 아래로 이동
                new_parent = self.session.query(Category).filter_by(category_id=new_parent_id).one()
                
                # 순환 참조 방지
                if new_parent.path.startswith(f"{old_path}/"):
                    raise ValueError("Cannot move a category to its own descendant")
                
                category.parent_id = new_parent_id
                category.level = new_parent.level + 1
                category.path = f"{new_parent.path}/{category.category_id}"
            
            # 모든 하위 카테고리의 level과 path 업데이트
            subcategories = self.session.query(Category).filter(
                Category.path.like(f"{old_path}/%")
            ).all()
            
            for subcat in subcategories:
                # 이전 경로에서 새 경로로 변경
                subcat.path = subcat.path.replace(old_path, category.path, 1)
                # level 업데이트
                subcat.level = subcat.path.count('/') 
            
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            raise e

    def associate_product_with_category(self, product_id: str, category_id: int, is_primary: bool = False) -> bool:
        """상품과 카테고리 연결"""
        try:
            # 기존 연결이 있는지 확인
            existing = self.session.query(ProductCategory).filter_by(
                product_id=product_id, category_id=category_id
            ).first()
            
            if existing:
                # 기존 연결이 있으면 is_primary만 업데이트
                existing.is_primary = is_primary
            else:
                # 새 연결 생성
                new_association = ProductCategory(
                    product_id=product_id,
                    category_id=category_id,
                    is_primary=is_primary
                )
                self.session.add(new_association)
            
            # is_primary=True로 설정하면 다른 카테고리의 is_primary를 False로 변경
            if is_primary:
                self.session.query(ProductCategory).filter(
                    ProductCategory.product_id == product_id,
                    ProductCategory.category_id != category_id
                ).update({ProductCategory.is_primary: False})
            
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            raise e
    
    def get_products_by_category(self, category_id: int, include_subcategories: bool = False) -> List[ProductCategory]:
        """카테고리의 모든 상품 조회"""
        if not include_subcategories:
            # 특정 카테고리의 상품만 조회
            return self.session.query(ProductCategory).filter_by(category_id=category_id).all()
        else:
            # 하위 카테고리의 상품도 포함하여 조회
            category = self.session.query(Category).filter_by(category_id=category_id).one()
            
            return self.session.query(ProductCategory).join(
                Category, ProductCategory.category_id == Category.category_id
            ).filter(
                Category.path.like(f"{category.path}%")
            ).all()
