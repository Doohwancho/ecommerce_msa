import logging

# 기본 로거 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 로거 생성
logger = logging.getLogger("payment_service")