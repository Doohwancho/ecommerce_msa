from app.config.database import get_mysql_db
from app.services.category_manager import CategoryManager
from sqlalchemy.orm import Session
from fastapi import Depends

def get_category_manager(db: Session = Depends(get_mysql_db)):
    return CategoryManager(db)
