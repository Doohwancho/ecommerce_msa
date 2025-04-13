# what

basic ecommerce msa experiment


## tech stacks
- 통신
  - step1) Nginx Ingress (API Gateway)
  - step1) K8s DNS (Service Discovery)
  - step4) gRPC (communication between containers)
  - step5) kafka (event queue)
  - step6) Istio + Envoy (service mesh for traffic 제어)
- database
  - step3) MongoDB (users, products)
  - step3) MySQL (categories, order)
- logging
  - step2) ELK (logging)
- error-handling
  - step7) Circuit Breaker (단순 retry 아닌 circuit breaker 패턴 적용)
  - step8) Jaeger (distributed tracing)


# Index

1. Q. 데이터를 어떻게 저장하지? 
  - 대규모 데이터를 다룰 때, 데이터의 특성과 DB의 장단점을 고려한 domain 나누기 
2. Q. MSA 환경에서 컨테이너들이 어떻게 통신하지? 
  - httpx(http 1.1)
  - grpc(http 2.0, multiplexing + types)
3. Q. 동기? 비동기?
  - msa에서 grpc는 비동기
  - async def 안에서 무조건 await를 써야함. 안쓰면 동기처럼 작동함
  - fastapi에서 동기 & 비동기, 코루틴, 메인루프?
TODO Q. kafka로 이벤트 담아 처리할 때 유실되지 않고 확실하게 처리하는 방법은?
  - outbox pattern
TODO Q. 분산시스템에서 transaction 처리? 
  - A->B->A 를 @Transactional 한다고 했을 때, B끝나고 A에서 터지면 B가 롤백이 안됨. (ex. 네트워크 장애, 서비스 장애, 데이터 불일치 등...)
  - 그렇다고 B요청에 blocking 걸자니 비효율
  - solution: if failed, do 보상 트랜젝션
  - 2 phase commit 
  - saga pattern
  - 글고 B요청만 필요한게 아니라, C,D요청도 있는 경우, B는 성공했는데 C가 실패한 경우, 모든 경우의 수를 if-else 분기처리해서 성공 / 실패 / 롤백 처리 등을 해야한다. 많은 예외케이스 고려해야한다.
TODO Q. 분산시스템에서 reliability?
  - sidecar: istio & envoy
  - circuit breaker: istio (or hystrix, Resilience4J) 에러발생시, 다른 값으로 대체해서 보냄 
  - 분산 트레이싱: jaeger
TODO Q. read heavy app에서 optimization?
  - elastic search에 indexing
  - 분산시스템에서 데이터 불일치문제 -> CAP theorem && PACELC theory
TODO Q. 배포 on aws
TODO Q. CICD
  - 무중단배포 



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



# B. 컨테이너끼리 어떻게 통신하지?
create_order()을 하면, user_validation() 해야해서 유저 모듈과 통신해야 한다.

## a. MSA 컨테이너 간 통신 프로토콜 비교 (JSON vs. HTTPx vs. gRPC)

| **기능**                | **JSON (HTTP/1.1)**                                                                 | **HTTPx (HTTP/2)**                                                                 | **gRPC**                                                                           |
|-------------------------|-------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| **데이터 포맷**         | 텍스트 기반 (JSON)                                                                  | 텍스트 기반 (JSON)                                                                | 바이너리 기반 (Protocol Buffers)                                                  |
| **프로토콜**            | HTTP/1.1                                                                           | HTTP/2                                                                            | HTTP/2                                                                            |
| **성능**                | 낮음: 텍스트 파싱 오버헤드                                                          | 중간: HTTP/2 멀티플렉싱 지원                                                     | 높음: 바이너리 직렬화 + HTTP/2 최적화                                             |
| **확장성**              | 제한적: 연결당 단일 요청                                                            | 개선됨: 멀티플렉싱 지원                                                          | 우수: 스트리밍 및 병렬 처리                                                       |
| **사용 편의성**          | 쉬움: RESTful API 표준                                                              | 쉬움: JSON 기반 + HTTP/2                                                         | 복잡함: Proto 파일 정의 필요                                                     |
| **언어 지원**           | 모든 언어                                                                          | 모든 언어                                                                        | 다중 언어 (공식 10+ 언어 지원)                                                   |
| **브라우저 지원**        | 완전 지원                                                                          | 완전 지원                                                                        | 제한적 (gRPC-Web 필요)                                                           |
| **실시간 통신**          | 불가능                                                                             | 제한적                                                                           | 지원: 단방향/양방향 스트리밍                                                     |
| **주요 장점**            | - 인간 친화적<br>- 디버깅 용이<br>- 널리 사용됨                                     | - HTTP/2 성능 개선<br>- 기존 JSON 호환                                           | - 고성능<br>- 강력한 타입 시스템<br>- 스트리밍 지원                              |
| **주요 단점**            | - 높은 지연 시간<br>- 데이터 크기 큼                                               | - 여전히 JSON 오버헤드 존재                                                      | - 학습 곡선 높음<br>- 브라우저 지원 제한                                         |
| **적합한 사례**          | - 외부 API<br>- 간단한 내부 통신                                                   | - 성능 개선이 필요한 REST API                                                    | - 고부하 서버 간 통신<br>- 실시간 데이터 처리                                    |


## b. **결론**
- **JSON (HTTP/1.1)**:  
  외부 클라이언트 노출, 간단한 통신, 빠른 개발이 필요할 때 선택.
- **HTTPx (HTTP/2)**:  
  기존 JSON API를 유지하면서 성능을 개선하려는 경우 사용.
- **gRPC**:  
  서버 간 고성능 통신, 실시간 스트리밍, 다중 언어 환경에서 권장.



# C. MSA에서 동기? 비동기?

## a. 전체 흐름 파악
이게 order_module에서 create_order()의 실행 흐름이다.(약식)
```
1. order_module.create_order() 
2. await validate_user() 
3. user_server.py가 요청 받음
4. user_service.validate_user() 호출 
5. DB I/O 실행 
```

Q. 여기서 어느 부분이 동기여야 하고 어느부분을 비동기로 처리해야 좋을까?


## b. 선행지식) 동기 vs 비동기 차이는?

1. 동기: 스레드가 작업 끝날 때 까지 기다림(다른 작업 수행 불가능)
2. 비동기: 스레드가 작업을 시작하고 기다리지 않고 딴일하러 감 

이 설명만 보면 무조건 비동기가 더 좋아보이는데 항상 그런건 아니다.

1. task생성하고 다른일하러 갈 때 task 전환 일어나니까 context switching cost가 있고,
2. 이 task들도 
3. queue 대기열에 넣고,
4. 우선순위 관리해서 스케쥴링 하고
5. 상태추적 하고 

....하면 CPU 오버헤드가 늘어난다.\
그래서 task가 ms단위로 너무 빨리 끝나는 일이면,\
이런거 다 해야하는 비동기보다 그냥 심플하게 기다리는 동기가 더 빠를 수 있다.

비동기 I/O는 
1. MSA같은 환경에서 컨테이너끼리 분리되어있는데, 네트워크 지연시간이 상대적으로 길거나,
2. 동시에 엄청 많은 요청(스레드풀의 스레드 숫자 이상)을 처리해야 할 때, 

동기보다 어 유리할 수 있다.


## c. 돌아와서, grpc 통신 부분은 동기? 비동기?
grpc는 동기, 비동기 2종류가 있는데, 보통 MSA에서는 비동기로 쓴다.

왜냐면 컨테이너끼리 통신하는데, 네트워크 장애 상황이 발생할 수 있다.

동기로 grpc 통신을 하면, 네트워크 장애, 지연, 상대 컨테이너가 죽었을 때, 무기한으로 기다려야 한다.

MSA를 쓰는 이유 중 하나가, 모듈간의 장애 격리인데,\
컨테이너 하나 터진다고 해서 다른 모듈에 영향을 주면 안되기 때문에,\
grpc는 비동기로 구현한다.


## d. 선행지식) fastapi에서 동기/비동기 처리 메커니즘

### d-1. 비동기 함수 (async def)

- FastAPI는 Uvicorn/Starlette 기반으로, 이들은 비동기 이벤트 루프를 사용합니다
- async def 함수는 메인 이벤트 루프에서 직접 실행됩니다
- I/O 작업에서 await 만나면 제어권을 이벤트 루프에 반환하고 다른 태스크를 처리합니다
- 이벤트 루프는 기본적으로 단일 스레드에서 실행됩니다

### d-2. 동기 함수 (def)

- FastAPI는 동기 함수를 만나면 자동으로 별도의 스레드풀로 오프로드합니다
- 이 작업은 메인 이벤트 루프를 차단하지 않도록 합니다
- 기본 스레드풀 크기는 CPU 코어 개수에 기반합니다
- 동기 함수가 완료되면 결과는 다시 이벤트 루프로 전달됩니다


## e. grpc 이후에 DB i/o 부분은 동기? 비동기?

### e-1. case1) 동기로 구현하는 경우 
```python
def validate_user(self, user_id):
    # 동기 DB 쿼리
    user = self.db_connection.find_one({"_id": user_id})
    return user is not None
```
실행 흐름:

1. gRPC 서버(비동기)가 이 함수 호출
2. 중요: FastAPI는 이 동기 함수를 스레드풀의 워커 스레드에 할당
3. 메인 이벤트 루프는 계속해서 다른 요청 처리 가능
4. 워커 스레드가 DB 쿼리 수행하며 I/O 동안 차단됨
5. 쿼리 완료 후 결과를 이벤트 루프(메인 스레드)로 반환
6. 이벤트 루프는 gRPC 응답 생성하여 반환

여기서 2번 부분에서,\
메인 스레드가 스레드풀한테 task할당할 때 context switching cost가 생긴다.


### e-2. case2) 비동기로 구현하는 경우
```python
async def validate_user(self, user_id):
    # 비동기 DB 쿼리
    user = await self.db_connection.find_one({"_id": user_id})
    return user is not None
```

실행 흐름:

1. gRPC 서버(비동기)가 이 함수 호출
2. 함수가 메인 이벤트 루프에서 직접 실행됨
3. DB 쿼리 시작하고 await에서 제어권 반환
4. 이벤트 루프는 다른 태스크 처리
5. DB 쿼리 완료 시 이벤트 루프가 함수 실행 재개
6. 결과를 gRPC 응답으로 반환

그래서 비동기는 동기와는 다르게
1. 별도 스레드 할당이 필요 없음
2. 컨텍스트 스위칭 오버헤드 없음
3. 단일 스레드가 여러 요청 효율적으로 처리


### e-3. Q. fastapi에서 동기 / 비동기 성능차이는?

1. 워커 스레드 오버헤드
  - 동기 함수는 스레드풀에 오프로드되어 스레드 전환 비용 발생
  - 비동기 함수는 메인 이벤트 루프에 머물러 이 오버헤드 없음
2. 리소스 사용량:
  - 동기 함수는 수행 중인 요청마다 별도 스레드 필요
  - 비동기 함수는 단일 스레드에서 많은 요청 처리 가능
3. 확장성:
  - 동기: 요청 수가 스레드풀 크기를 초과하면 큐잉 발생
  - 비동기: 메모리 제약 내에서 훨씬 많은 동시 요청 처리 가능


### e-4. 결론
OLTP 환경에 CRUD app은 비동기가 더 유리 
1. 대부분의 작업이 I/O 바운드 (DB 쿼리)
2. 많은 동시 요청 처리 필요
3. 각 요청의 처리 시간이 상대적으로 짧음

게다가 MSA에는 네트워크 통신도 중간에 껴있어서 비동기가 더 유리


### e-5. 기타
```
1. order_module.create_order() [?]
2. await validate_user() [비동기]
3. user_server.py가 요청 받음 [비동기]
4. user_service.validate_user() 호출 [비동기]
5. DB I/O 실행 [비동기]
```

Q. 2~5가 비동기인게 도출됬는데, 그러면 1은 동기로 만들어야 할까? 비동기로 해야할까?

A. 비동기로 해야한다.

2번에 비동기 함수 호출할 때, 결과값 반환을 기다려야 하니까 await 써야하는데,\
동기 함수 내부에서는 await를 못쓰고, 반드시 async def로 선언해주어야 한다고 한다.





# D. kafka로 이벤트 담아 처리할 때 유실되지 않고 확실하게 처리하는 방법은?