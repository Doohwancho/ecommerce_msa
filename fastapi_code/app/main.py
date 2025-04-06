from fastapi import FastAPI
from app.api.api import api_router
from app.config.database import Base, engine, SessionLocal
from app.core.init_db import initialize_categories

# 애플리케이션 생성
app = FastAPI(title="E-commerce API")

# API 라우터 등록
app.include_router(api_router)

# 테이블 생성
Base.metadata.create_all(bind=engine)

@app.get("/")
def read_root():
    return "Hello from the E-commerce API!"

@app.get("/health")
def health_check():
    return {"status": "OK"}

# 애플리케이션 시작 시 초기화 이벤트 핸들러
@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    try:
        initialize_categories(db)
    finally:
        db.close()


# import logging
# from logging.config import dictConfig
# # import logstash 
# import socket
# from fastapi import FastAPI, HTTPException, Depends
# from pymongo import MongoClient
# from pydantic import BaseModel
# import os
# from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, Index
# from sqlalchemy.ext.declarative import declarative_base
# from sqlalchemy.orm import relationship, sessionmaker, Session
# from typing import List, Optional

# ##########################################
# ####           Logging            ########
# ##########################################

# # 로깅 설정
# # LOGSTASH_HOST = 'logstash-service'
# # LOGSTASH_PORT = 5044

# log_config = {
#     "version": 1,
#     "disable_existing_loggers": False,
#     "formatters": {
#         "json": {
#             "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
#             "format": "%(asctime)s %(levelname)s %(name)s %(message)s %(hostname)s",
#             "datefmt": "%Y-%m-%d %H:%M:%S",
#         }
#     },
#     "handlers": {
#         "console": {
#             "class": "logging.StreamHandler",
#             "formatter": "json",
#             "stream": "ext://sys.stdout",
#         },
#         # "logstash": {
#         #     "class": "logstash.TCPLogstashHandler",
#         #     "host": "logstash-service",
#         #     "port": 5044,
#         #     "version": 1,
#         #     "message_type": "python-logstash",
#         #     "tags": ["fastapi"]
#         # }
#     },
#     "loggers": {
#         "app": {
#             # "handlers": ["console", "logstash"], # logstash를 안쓰면 주석처리 
#             "handlers": ["console"],
#             "level": "INFO",
#             "propagate": True
#         },
#     }
# }

# # 로깅 설정 적용
# dictConfig(log_config)
# logger = logging.getLogger("app")

# # hostname 추가
# logger = logging.LoggerAdapter(logger, {'hostname': socket.gethostname()})



# app = FastAPI()



# ##########################################
# ####           MongoDB            ########
# ##########################################
# try:
#     mongo_client = MongoClient(f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@{os.getenv('MONGODB_URL')}")
#     print("DB Connection successful")
# except Exception as e: print(e)


# # If the database and collection do not exist, MongoDB will create them automatically
# mongo_db = mongo_client.my_db
# user_collection = mongo_db.my_collection

# ##########################################
# ####           Entity             ########
# ##########################################
# class User(BaseModel): # Define a Pydantic model for the User data
#     Name: str
#     Age: int
#     Occupation: str
#     Learning: str



# ##########################################
# ####           Mysql              ########
# ##########################################
# # MySQL 설정
# MYSQL_USER = os.getenv("MYSQL_USER", "root")
# MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "password")
# MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql-service")
# MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "shop")

# SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DATABASE}"

# engine = create_engine(SQLALCHEMY_DATABASE_URL)
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Base = declarative_base()

# # # MySQL 모델
# # class CategoryDB(Base):
# #     __tablename__ = "categories"

# #     id = Column(Integer, primary_key=True, index=True)
# #     name = Column(String(50), unique=True, index=True)
# #     description = Column(String(200))

# # # Pydantic 모델
# # class CategoryBase(BaseModel):
# #     name: str
# #     description: Optional[str] = None

# # class CategoryCreate(CategoryBase):
# #     pass

# # class Category(CategoryBase):
# #     id: int

# #     class Config:
# #         orm_mode = True

# # # 데이터베이스 테이블 생성
# # Base.metadata.create_all(bind=engine)

# class Category(Base):
#     """
#     카테고리 계층 구조를 관리하는 테이블
#     - level: 카테고리 깊이 (최상위=0, 하위=1, 그 다음 하위=2...)
#     - path: 전체 경로를 저장 (예: "1/4/28")
#     """
#     __tablename__ = 'categories'
    
#     category_id = Column(Integer, primary_key=True, autoincrement=True)
#     name = Column(String(100), nullable=False)
#     parent_id = Column(Integer, ForeignKey('categories.category_id', ondelete='CASCADE'), nullable=True)
#     level = Column(Integer, nullable=False, default=0)
#     path = Column(String(255), nullable=False)
    
#     # 인덱스 생성
#     __table_args__ = (
#         Index('idx_parent', 'parent_id'),
#         Index('idx_path', 'path'),
#     )
    
#     # 관계 설정
#     children = relationship("Category", 
#                            backref="parent", 
#                            remote_side=[category_id],
#                            cascade="all, delete-orphan")
#     products = relationship("ProductCategory", back_populates="category")

# class ProductCategory(Base):
#     """
#     상품과 카테고리 간의 다대다 관계를 관리하는 테이블
#     - is_primary: 상품의 주 카테고리인지 여부
#     """
#     __tablename__ = 'product_categories'
    
#     product_id = Column(String(24), primary_key=True)
#     category_id = Column(Integer, ForeignKey('categories.category_id', ondelete='CASCADE'), primary_key=True)
#     is_primary = Column(Boolean, default=False)
    
#     # 인덱스 생성
#     __table_args__ = (
#         Index('idx_category', 'category_id'),
#         Index('idx_product', 'product_id'),
#         Index('idx_primary', 'is_primary'),
#     )
    
#     # 관계 설정
#     category = relationship("Category", back_populates="products")


# # 데이터베이스 테이블 생성
# Base.metadata.create_all(engine)

# # 카테고리 관리를 위한 클래스
# class CategoryManager:
#     def __init__(self, db_session):
#         self.session = db_session
    
#     def create_category(self, name, parent_id=None):
#         """새 카테고리 생성"""
#         try:
#             if parent_id is None:
#                 # 최상위 카테고리 생성
#                 new_category = Category(
#                     name=name,
#                     level=0,
#                     path=""  # 임시 path
#                 )
#                 self.session.add(new_category)
#                 self.session.flush()  # ID 생성을 위해 flush
                
#                 # path 업데이트
#                 new_category.path = str(new_category.category_id)
                
#             else:
#                 # 하위 카테고리 생성
#                 parent = self.session.query(Category).filter_by(category_id=parent_id).one()
                
#                 new_category = Category(
#                     name=name,
#                     parent_id=parent_id,
#                     level=parent.level + 1,
#                     path=""  # 임시 path
#                 )
#                 self.session.add(new_category)
#                 self.session.flush()  # ID 생성을 위해 flush
                
#                 # path 업데이트
#                 new_category.path = f"{parent.path}/{new_category.category_id}"
            
#             self.session.commit()
#             return new_category
#         except Exception as e:
#             self.session.rollback()
#             raise e
    
#     def get_subcategories(self, category_id):
#         """특정 카테고리의 모든 하위 카테고리 조회"""
#         parent = self.session.query(Category).filter_by(category_id=category_id).one()
#         return self.session.query(Category).filter(
#             Category.path.like(f"{parent.path}/%")
#         ).all()
    
#     def get_ancestors(self, category_id):
#         """특정 카테고리의 모든 상위 카테고리 조회"""
#         category = self.session.query(Category).filter_by(category_id=category_id).one()
        
#         # path에서 ID 추출
#         path_ids = category.path.split("/")
#         ancestors = []
        
#         # 마지막 ID는 현재 카테고리이므로 제외
#         for ancestor_id in path_ids[:-1]:
#             ancestor = self.session.query(Category).filter_by(category_id=int(ancestor_id)).one()
#             ancestors.append(ancestor)
        
#         return ancestors
    
#     def move_category(self, category_id, new_parent_id=None):
#         """카테고리 이동 (다른 부모 아래로)"""
#         try:
#             category = self.session.query(Category).filter_by(category_id=category_id).one()
#             old_path = category.path
            
#             if new_parent_id is None:
#                 # 최상위 카테고리로 이동
#                 category.parent_id = None
#                 category.level = 0
#                 category.path = str(category.category_id)
#             else:
#                 # 다른 부모 아래로 이동
#                 new_parent = self.session.query(Category).filter_by(category_id=new_parent_id).one()
                
#                 # 순환 참조 방지
#                 if new_parent.path.startswith(f"{old_path}/"):
#                     raise ValueError("Cannot move a category to its own descendant")
                
#                 category.parent_id = new_parent_id
#                 category.level = new_parent.level + 1
#                 category.path = f"{new_parent.path}/{category.category_id}"
            
#             # 모든 하위 카테고리의 level과 path 업데이트
#             subcategories = self.session.query(Category).filter(
#                 Category.path.like(f"{old_path}/%")
#             ).all()
            
#             for subcat in subcategories:
#                 # 이전 경로에서 새 경로로 변경
#                 subcat.path = subcat.path.replace(old_path, category.path, 1)
#                 # level 업데이트
#                 subcat.level = subcat.path.count('/') 
            
#             self.session.commit()
#             return True
#         except Exception as e:
#             self.session.rollback()
#             raise e

#     def associate_product_with_category(self, product_id, category_id, is_primary=False):
#         """상품과 카테고리 연결"""
#         try:
#             # 기존 연결이 있는지 확인
#             existing = self.session.query(ProductCategory).filter_by(
#                 product_id=product_id, category_id=category_id
#             ).first()
            
#             if existing:
#                 # 기존 연결이 있으면 is_primary만 업데이트
#                 existing.is_primary = is_primary
#             else:
#                 # 새 연결 생성
#                 new_association = ProductCategory(
#                     product_id=product_id,
#                     category_id=category_id,
#                     is_primary=is_primary
#                 )
#                 self.session.add(new_association)
            
#             # is_primary=True로 설정하면 다른 카테고리의 is_primary를 False로 변경
#             if is_primary:
#                 self.session.query(ProductCategory).filter(
#                     ProductCategory.product_id == product_id,
#                     ProductCategory.category_id != category_id
#                 ).update({ProductCategory.is_primary: False})
            
#             self.session.commit()
#             return True
#         except Exception as e:
#             self.session.rollback()
#             raise e
    
#     def get_products_by_category(self, category_id, include_subcategories=False):
#         """카테고리의 모든 상품 조회"""
#         if not include_subcategories:
#             # 특정 카테고리의 상품만 조회
#             return self.session.query(ProductCategory).filter_by(category_id=category_id).all()
#         else:
#             # 하위 카테고리의 상품도 포함하여 조회
#             category = self.session.query(Category).filter_by(category_id=category_id).one()
            
#             return self.session.query(ProductCategory).join(
#                 Category, ProductCategory.category_id == Category.category_id
#             ).filter(
#                 Category.path.like(f"{category.path}%")
#             ).all()

# # Dependency
# def get_mysql_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()


# ##############################################
# ####   Controller / Service / Repository  ####
# ##############################################
# @app.get("/")
# def read_root():
#     return "Hello from the other sideeeeeee!!!!!!!!"


# @app.post("/create_user/")
# async def create_user(user: User):
#     try:
#         logger.info(f"Creating user: {user.Name}")
#         result = user_collection.insert_one(user.dict())
#         logger.info(f"User created successfully: {user.Name}")
#         return {"message": "User created successfully", "id": str(result.inserted_id)}
#     except Exception as e:
#         logger.error(f"Error creating user {user.Name}: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))



# @app.get("/get_users/{name}")
# async def get_user(name: str):
#     try:
#         logger.info(f"Fetching user: {name}")
#         user = user_collection.find_one({"Name": name})
#         if user:
#             # ObjectId를 문자열로 변환
#             user["_id"] = str(user["_id"])
#             logger.info(f"User found: {name}")
#             return user
#         logger.warning(f"User not found: {name}")
#         raise HTTPException(status_code=404, detail="User not found")
#     except Exception as e:
#         logger.error(f"Error fetching user {name}: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/health")
# def health_check():
#     return {"status": "OK"}




# # Category CRUD endpoints
# @app.post("/categories/", response_model=Category)
# def create_category(category: CategoryCreate, mysql_db: Session = Depends(get_mysql_db)):
#     db_category = CategoryDB(name=category.name, description=category.description)
#     try:
#         mysql_db.add(db_category)
#         mysql_db.commit()
#         mysql_db.refresh(db_category)
#         return db_category
#     except Exception as e:
#         mysql_db.rollback()
#         raise HTTPException(status_code=400, detail=str(e))


# @app.get("/categories/", response_model=List[Category])
# def read_categories(skip: int = 0, limit: int = 100, mysql_db: Session = Depends(get_mysql_db)):
#     categories = mysql_db.query(CategoryDB).offset(skip).limit(limit).all()
#     return categories

# @app.get("/categories/{category_id}", response_model=Category)
# def read_category(category_id: int, mysql_db: Session = Depends(get_mysql_db)):
#     category = mysql_db.query(CategoryDB).filter(CategoryDB.id == category_id).first()
#     if category is None:
#         raise HTTPException(status_code=404, detail="Category not found")
#     return category

# @app.put("/categories/{category_id}", response_model=Category)
# def update_category(category_id: int, category: CategoryCreate, mysql_db: Session = Depends(get_mysql_db)):
#     db_category = mysql_db.query(CategoryDB).filter(CategoryDB.id == category_id).first()
#     if db_category is None:
#         raise HTTPException(status_code=404, detail="Category not found")
    
#     db_category.name = category.name
#     db_category.description = category.description
    
#     try:
#         mysql_db.commit()
#         mysql_db.refresh(db_category)
#         return db_category
#     except Exception as e:
#         mysql_db.rollback()
#         raise HTTPException(status_code=400, detail=str(e))

# @app.delete("/categories/{category_id}")
# def delete_category(category_id: int, mysql_db: Session = Depends(get_mysql_db)):
#     db_category = mysql_db.query(CategoryDB).filter(CategoryDB.id == category_id).first()
#     if db_category is None:
#         raise HTTPException(status_code=404, detail="Category not found")
    
#     try:
#         mysql_db.delete(db_category)
#         mysql_db.commit()
#         return {"message": "Category deleted successfully"}
#     except Exception as e:
#         mysql_db.rollback()
#         raise HTTPException(status_code=400, detail=str(e))