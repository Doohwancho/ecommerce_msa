# what

fastAPI + mysql + mongodb + mongo-express + ELK(for logging) on k8s

step2) MSA 전환

- Monolithic FastAPI 서버 (users / products / orders)
- MongoDB (users, products)
- MySQL (categories, order)
- Nginx Ingress (API Gateway)
- K8s DNS (Service Discovery)
- gRPC (instead of httpx)
- ELK (logging)


step3) + message queue

- Monolithic FastAPI 서버 (users / products / orders)
- MongoDB (users, products)
- MySQL (categories, order)
- Nginx Ingress (API Gateway)
- K8s DNS (Service Discovery)
- gRPC (instead of httpx)
- ELK (logging)
- kafka

step4) + service mesh

- Monolithic FastAPI 서버 (users / products / orders)
- MongoDB (users, products)
- MySQL (categories, order)
- Nginx Ingress (API Gateway)
- K8s DNS (Service Discovery)
- gRPC (instead of httpx)
- ELK (logging)
- kafka (event queue)
- Istio + Envoy (service mesh for traffic 제어)

step5) + Circuit Breaker

- Monolithic FastAPI 서버 (users / products / orders)
- MongoDB (users, products)
- MySQL (categories, order)
- Nginx Ingress (API Gateway)
- K8s DNS (Service Discovery)
- gRPC (instead of httpx)
- ELK (logging)
- kafka (event queue)
- Istio + Envoy (service mesh for traffic 제어)
- Circuit Breaker (단순 retry 아닌 circuit breaker 패턴 적용)

step6) + Distributed Tracing

- Monolithic FastAPI 서버 (users / products / orders)
- MongoDB (users, products)
- MySQL (categories, order)
- Nginx Ingress (API Gateway)
- K8s DNS (Service Discovery)
- gRPC (instead of httpx)
- ELK (logging)
- kafka (event queue)
- Istio + Envoy (service mesh for traffic 제어)
- Circuit Breaker (단순 retry 아닌 circuit breaker 패턴 적용)
- Jaeger

# Index

- Q. 데이터를 어떻게 저장하지?
- Q. MSA 환경에서 컨테이너들이 어떻게 통신하지?
- Q. 분산시스템에서 transaction 처리?
- Q. read heavy app에서 optimization?
- Q. 분산시스템에서 reliability?

# A. 상품 데이터를 어떻게 저장하지?

## a-1. 제약사항

1. domain은 ecommerce
2. 100만개 이상 대규모 상품 데이터
3. read:write (for product) 비율이 9.9:0.1 이상인 read heavy app
4. nike같이 신발만 파는게 아닌, 아마존처럼 다양한 종류의 상품
5. 상품 주문 정보도 저장

## a-2. 어느 DB에 어느 데이터 구조로 저장하지?

보통 RDB에 상품데이터를 넣고 관리한다고 생각하는데,\
파는 상품 종류가 몇개 안되면, 테이블 컬럼 정의하기가 용이하지만,\
쿠팡같이 상품종류가 매우 다양하면 nosql에 밀어넣고 파싱해서 쓰는게 낫다.

예를들어, 신발 전문 쇼핑몰의 경우 테이블 컬럼 종류가 아무리 다양해봤자 몇십개 이내로 특정지을 수 있다.

하지만 쇼핑몰에서 신발, 스마트폰, 채소를 판다고 할 경우,\
이 3종류 상품에 모두 해당되는 컬럼을 만들면,\
null값이 들어가는 컬럼이 너무 많이 생겨서,\
메모리 용량 낭비가 너무 심해진다.

이럴 때 도메인을 잘 나누는 노하우가 필요해지고,\
어설프게 나누면 ecommerce에서 다뤄지는 모든 상품을 정확히 분류할 때 문제가 생긴다.

---

상품을 추가할 때, 새로운 필드를 하나 추가해야 하는 상황이라 치자.

RDB면 스키마 변경해야 하고 migration 해야하는게 부담스러울 수 있는 반면,\
Nosql은 비교적 자유롭다.

---

쿠팡같은 대규모 쇼핑몰은 등록된 상품 갯수만 100만개 이상이라고 하면,\
데이터를 쪼개서 여러 DB에 나눠서 저장하는 샤딩을 선택하는 경우가 있는데,\
RDB보다 nosql이 샤딩에 더 유리하다.

## a-3. 상품 카테고리 정보는 어디에 저장하는게 좋을까?

만약, 모든 상품 카탈로그 + 카테고리 데이터를 nosql에 저장한다면,

```sql
{
  "_id": "P123456",
  "name": "스마트폰 XYZ 모델",
  "description": "최신 스마트폰...",
  "price": 799.99,
  "attributes": { "color": "블랙", "storage": "128GB" },
  "variants": [...],
  "categories": [
    { "id": 42, "name": "전자제품", "level": 0, "path": "42" },
    { "id": 56, "name": "스마트폰", "level": 1, "path": "42/56" },
    { "id": 78, "name": "프리미엄 폰", "level": 2, "path": "42/56/78" }
  ],
  "primary_category_id": 56
}
```

이런식으로 저장되는데, 문제는 category 데이터가 중복이 많아진다는 것이다.

제약사항에서 100만 상품 이상을 가정했으니, 낭비되는 메모리가 엄청 많아질 것이다.

그러면 저 카테고리 부분만 따로 collection으로 빼서 이런식으로 만들면,

```sql
{
  "_id": "cat42",
  "name": "전자제품",
  "parent_id": null,
  "level": 0,
  "path": "cat42",
  "product_ids": ["P123", "P456", "P789", ...]
}
```

중복데이터는 감소하는데, 문제가 mongodb기준, 단일 문서 크기가 16MB로 제한되는데, 인기 있는 카테고리의 경우 product_ids 배열이 매우 커질 수 있고, 이 제한에 도달할 수 있다.

또한 product write/update할 때마다, 이 카테고리에 저 긴 product_ids 배열을 업데이트 해야하는데, 이 때 동시성 문제가 발생하거나 lock contention 때문에 느려질 수 있다.

또한 카테고리 갯수가 몇백개 이상되는 경우, 따로 path컬럼을 써서 최적화를 쓰는데, "1/4/13/" 이런식으로 되있는데,

MySQL에서는 WHERE path LIKE '1/4/%' 이런 쿼리 날리면 path 컬럼에 인덱스 걸어놓으면 효율적으로 인덱스 타고 찾아주는데,

mongodb는 기본적으로 regex로 단어찾는데, 이게 인덱스도 안타서 느림.
