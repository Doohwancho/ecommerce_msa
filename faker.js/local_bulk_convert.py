import json
import requests
import time
import logging
from tqdm import tqdm
import ijson  # 스트리밍 JSON 파서
from decimal import Decimal

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='es_import.log'
)
logger = logging.getLogger(__name__)

# Elasticsearch 설정
ES_URL = "http://localhost:9201"
INDEX_NAME = "my_db.products"
BATCH_SIZE = 500  # 더 작은 배치 사이즈
MAX_RETRIES = 5
TIMEOUT = 120  # 더 긴 타임아웃

# Decimal 타입을 처리하는 JSON 인코더
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def stream_json_file(filename):
    """대용량 JSON 파일을 메모리 효율적으로 스트리밍"""
    with open(filename, 'rb') as f:
        # JSON 배열 내의 각 객체를 하나씩 파싱
        items = ijson.items(f, 'item')
        for item in items:
            yield item

def create_bulk_actions(products_generator):
    """메모리 효율적인 방식으로 벌크 액션 생성"""
    for product in products_generator:
        # _id 필드가 다른 형식으로 제공될 수 있으므로 여러 가능성 확인
        if isinstance(product.get("_id"), dict) and "$oid" in product.get("_id", {}):
            product_id = product["_id"]["$oid"]
        elif "_id" in product:
            product_id = str(product["_id"])
        else:
            # ID가 없으면 기본값으로 설정
            product_id = None
        
        # 문서 복사본 생성 및 _id 필드 제거
        product_copy = product.copy()
        if "_id" in product_copy:
            del product_copy["_id"]
        
        # 벌크 액션 생성 (index 명령과 문서)
        index_action = {"index": {"_index": INDEX_NAME}}
        if product_id:
            index_action["index"]["_id"] = product_id
        
        yield index_action
        yield product_copy

def convert_decimal_in_dict(obj):
    """재귀적으로 딕셔너리 내의 모든 Decimal 값을 float로 변환"""
    if isinstance(obj, dict):
        return {k: convert_decimal_in_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimal_in_dict(i) for i in obj]
    elif isinstance(obj, Decimal):
        return float(obj)
    else:
        return obj

def send_bulk_request(batch_data, retry_count=0):
    """벌크 요청 전송 및 오류 처리"""
    try:
        # Decimal을 float로 변환
        converted_batch = [convert_decimal_in_dict(item) for item in batch_data]
        
        # 벌크 데이터를 NDJSON 형식으로 변환
        ndjson_data = '\n'.join([json.dumps(doc, cls=DecimalEncoder) for doc in converted_batch]) + '\n'
        
        # Elasticsearch 벌크 API 호출
        response = requests.post(
            f"{ES_URL}/_bulk",
            headers={"Content-Type": "application/x-ndjson"},
            data=ndjson_data,
            timeout=TIMEOUT
        )
        
        # 응답 확인
        result = response.json()
        if result.get('errors'):
            error_count = sum(1 for item in result.get('items', []) if item.get('index', {}).get('error'))
            logger.warning(f"배치에서 {error_count}/{len(batch_data)//2} 문서에 오류 발생")
            
            # 특정 오류가 있는지 확인
            for i, item in enumerate(result.get('items', [])):
                if 'error' in item.get('index', {}):
                    error = item['index']['error']
                    error_type = error.get('type', '')
                    logger.warning(f"오류 유형: {error_type}, 이유: {error.get('reason', '')}")
                    
                    if error_type in ['es_rejected_execution_exception', 'circuit_breaking_exception']:
                        # 서버 과부하 또는 메모리 부족 오류인 경우 재시도
                        if retry_count < MAX_RETRIES:
                            logger.warning(f"서버 과부하 감지, {retry_count+1}번째 재시도 중...")
                            time.sleep(10 * (retry_count + 1))  # 백오프 전략
                            return send_bulk_request(batch_data, retry_count + 1)
            
            return False
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"요청 오류: {str(e)}")
        if retry_count < MAX_RETRIES:
            logger.warning(f"네트워크 오류, {retry_count+1}번째 재시도 중...")
            time.sleep(5 * (retry_count + 1))
            return send_bulk_request(batch_data, retry_count + 1)
        return False
    except json.JSONDecodeError as e:
        logger.error(f"JSON 인코딩 오류: {str(e)}")
        logger.error(f"문제가 된 데이터 일부: {str(batch_data[0])[:200]}...")
        if retry_count < MAX_RETRIES:
            logger.warning(f"JSON 오류, {retry_count+1}번째 재시도 중...")
            time.sleep(5 * (retry_count + 1))
            return send_bulk_request(batch_data, retry_count + 1)
        return False

def main():
    """메인 임포트 함수"""
    filename = 'faker.js/products.json'
    
    # 진행 상황을 추적하기 위한 카운터
    success_count = 0
    error_count = 0
    batch_count = 0
    
    try:
        # 스트리밍 방식으로 JSON 파싱
        products_generator = stream_json_file(filename)
        
        # 벌크 액션 생성
        bulk_actions = create_bulk_actions(products_generator)
        
        # 배치 처리
        batch = []
        for action in tqdm(bulk_actions, desc="처리 중"):
            batch.append(action)
            
            # 배치가 가득 차면 요청 전송
            if len(batch) >= BATCH_SIZE * 2:  # 각 문서당 2개 액션 (index + 데이터)
                success = send_bulk_request(batch)
                batch_count += 1
                
                if success:
                    success_count += BATCH_SIZE
                    logger.info(f"배치 {batch_count} 성공적으로 임포트됨")
                else:
                    error_count += BATCH_SIZE
                    logger.error(f"배치 {batch_count} 임포트 중 오류 발생")
                
                # 배치 초기화 및 Elasticsearch에 휴식 시간 제공
                batch = []
                time.sleep(1)
        
        # 남은 문서 처리
        if batch:
            success = send_bulk_request(batch)
            batch_count += 1
            
            if success:
                success_count += len(batch) // 2
                logger.info(f"마지막 배치 {batch_count} 성공적으로 임포트됨")
            else:
                error_count += len(batch) // 2
                logger.error(f"마지막 배치 {batch_count} 임포트 중 오류 발생")
        
        logger.info(f"임포트 완료: {success_count} 성공, {error_count} 실패")
        print(f"임포트 완료: {success_count} 성공, {error_count} 실패")
        
    except Exception as e:
        logger.critical(f"예상치 못한 오류: {str(e)}")
        print(f"오류 발생: {str(e)}")

if __name__ == "__main__":
    main()