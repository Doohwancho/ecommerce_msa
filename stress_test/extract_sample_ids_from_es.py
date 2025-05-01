import json
import requests

# Elasticsearch 설정
ES_URL = "http://localhost:9201"
INDEX_NAME = "my_db.products"
SAMPLE_SIZE = 10000

def extract_elasticsearch_ids_simple():
    # 기본 검색 쿼리 (정렬 없음)
    search_query = {
        "size": 10000,  # 최대 10,000개 (Elasticsearch 기본 제한)
        "query": {"match_all": {}},
        "_source": False
    }
    
    response = requests.post(
        f"{ES_URL}/{INDEX_NAME}/_search",
        headers={"Content-Type": "application/json"},
        json=search_query,
        timeout=60
    )
    
    if response.status_code == 200:
        result = response.json()
        ids = [hit["_id"] for hit in result.get("hits", {}).get("hits", [])]
        
        # 필요하다면 랜덤하게 섞기
        import random
        random.shuffle(ids)
        
        with open("elasticsearch_product_ids.json", "w") as f:
            json.dump(ids, f)
        
        print(f"{len(ids)}개 ID를 저장했습니다.")
        return ids
    else:
        print(f"오류 발생: {response.status_code} - {response.text}")
        return []

if __name__ == "__main__":
    extract_elasticsearch_ids_simple()