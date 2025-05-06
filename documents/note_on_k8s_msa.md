# A. what 

## a. definition 

fastapi(user / product / order) + mongodb + ELK on k8s, MSA

1. k8s에서 간단한 webapp + ELK for logging run
2. user / product / order modules 통신 테스트
3. api-gateway(nginx ingress controller)에서 각 모듈과 통신 테스트 
4. mongo-express에서 데이터 잘 들어왔는지 확인 
5. logstash, elastic cache에 log가 쌓였는지 확인 
6. kibana dashboard에서 로그 visualize

[resource](https://github.com/deshwalmahesh/fastapi-kubernetes/tree/main)


# B. test 
## a. how to start
```bash
minikube delete

minikube start --cpus=7 --memory=11500 --disk-size=40g

minikube addons enable ingress

./deploy.sh

kubectl get pod 
kubectl get service
minikube service ${service_name} --url
kubectl get logs ${pod_name}

minikube tunnel

minikube dashboard &
```

## b. mysql에 replica set 설정 
1. mysql-0 (primary, write)
2. mysql-1 (secondary, read)

이렇게 두개 생기는데(HA), write_db에 쓴다고 read_db에 sync가 안되기 때문에, 설정을 잡아줘야 sync 한다.

```bash
kubectl exec -it mysql-0 -- bash

mysql -u root -p
# 암호 입력 (root)

# step1) primary에서 복제 사용자 생성
CREATE USER 'replication'@'%' IDENTIFIED BY 'replication';
GRANT REPLICATION SLAVE ON *.* TO 'replication'@'%';
FLUSH PRIVILEGES;
```

mysql-0(primary)에서.. 
```bash
-- 바이너리 로그 활성화 확인
SHOW VARIABLES LIKE 'log_bin';
SHOW VARIABLES LIKE 'server_id';

# step2) mysql-1(primary)에서 File 명이랑 Position 을 복사한다.
-- 현재 바이너리 로그 파일과 위치 확인
SHOW MASTER STATUS;

+------------------+----------+--------------+------------------+-------------------+
| File             | Position | Binlog_Do_DB | Binlog_Ignore_DB | Executed_Gtid_Set |
+------------------+----------+--------------+------------------+-------------------+
| mysql-bin.000003 |     9276 |              |                  |                   |
+------------------+----------+--------------+------------------+-------------------+
1 row in set (0.00 sec)

...에서 mysql-bin.000003 을 복사!
position 9276도 복사!
```


mysql-1(secondary)에서..
```bash
# step3) primary에서 딴 file, log_pos를 입력한다.
-- Primary 연결 설정
CHANGE MASTER TO
    MASTER_HOST='mysql-0.mysql-headless',
    MASTER_USER='replication',
    MASTER_PASSWORD='replication',
    MASTER_LOG_FILE='mysql-bin.000003',  -- Primary에서 확인한 값
    MASTER_LOG_POS=9276;                     -- Primary에서 확인한 값

# step4) 복제 시작하면 master db 테이블에 있던 데이터를 slave db 테이블에 sync한다. (이제부터임. 이전 데이터는 sync 안함)
-- 복제 시작
START SLAVE;

-- 복제 상태 확인
SHOW SLAVE STATUS\G
```

## c. mongodb에 replica set 설정 

```bash
# admin 데이터베이스로 첫번째 pod에 접속
kubectl exec -it mongodb-stateful-0 -- mongosh -u $MONGO_INITDB_ROOT_USERNAME -p $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin

# Replica Set 초기화
# 안됬었는데 주소 바꾸고 재시도 해보자 
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongodb-stateful-0.mongodb-service.default.svc.cluster.local:27017" },
    { _id: 1, host: "mongodb-stateful-1.mongodb-service.default.svc.cluster.local:27017" },
    { _id: 2, host: "mongodb-stateful-2.mongodb-service.default.svc.cluster.local:27017" }
  ]
})

rs.status()
```




## c. test user module
```bash
minikube tunnel

# User Service (8001 포트로 포워딩)
kubectl port-forward service/user-service 8001:8000

http://localhost:8001/docs#/

minikube service mongo-express-service
id: admin
password: pass

# 유저 생성
curl -X POST http://localhost:8001/api/users/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "doohwan",
    "age": 20,
    "occupation": "developer",
    "learning": "k8s"
  }'

curl -X GET http://localhost:8001/api/users/id/67f79a1c4c3dd886d3eb859b

curl -X GET http://localhost:8001/api/users/doohwan

# 다른 터미널에서 테스트
curl -X GET http://localhost:8001/api/users/
```


## d. test product module
```bash
############################################################
############################################################
############################################################
# product test

# Product Service (8002 포트로 포워딩)
kubectl port-forward service/product-service 8002:8000

curl -X POST http://localhost:8002/api/products/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "ddd Apple 2025 MacBook Pro",
    "description": "최신 Apple MacBook Pro, M3 Max 칩, 16인치 Liquid Retina XDR 디스플레이",
    "brand": "Apple",
    "model": "MUW73LL/A",
    "sku": "MBP-16-M3-MAX",
    "upc": "195949185694",
    "color": "Space Gray",
    "category_ids": [1, 2, 4],
    "category_path": "1/2/4",
    "category_level": 3,
    "primary_category_id": 4,
    "category_breadcrumbs": ["전자제품", "컴퓨터", "노트북"],
    "price": {
      "amount": 3499.99,
      "currency": "USD"
    },
    "stock": 100, 
    "weight": {
      "value": 4.8,
      "unit": "POUND"
    },
    "dimensions": {
      "length": 14.01,
      "width": 9.77,
      "height": 0.66,
      "unit": "INCH"
    },
    "attributes": {
      "processor": "M3 Max",
      "ram": "32GB",
      "storage": "1TB SSD",
      "screen_size": "16 inch",
      "resolution": "3456 x 2234"
    },
    "variants": [
      {
        "id": "variant1",
        "sku": "MBP-16-M3-MAX-SG-32GB-1TB",
        "color": "Space Gray",
        "storage": "1TB",
        "price": {
          "amount": 3499.99,
          "currency": "USD"
        },
        "attributes": {
          "processor": "M3 Max",
          "ram": "32GB"
        },
        "inventory": 50
      },
      {
        "id": "variant2",
        "sku": "MBP-16-M3-MAX-SIL-32GB-1TB",
        "color": "Silver",
        "storage": "1TB",
        "price": {
          "amount": 3499.99,
          "currency": "USD"
        },
        "attributes": {
          "processor": "M3 Max",
          "ram": "32GB"
        },
        "inventory": 35
      }
    ],
    "images": [
      {
        "url": "https://example.com/macbook-pro-1.jpg",
        "main": true
      },
      {
        "url": "https://example.com/macbook-pro-2.jpg",
        "main": false
      }
    ]
  }'



curl -X GET http://localhost:8002/api/products/

product-service pod에 로그를 보면,

2025-04-09 05:57:46 INFO app Product created: P67f60c5af9dc66c37747ef8f product-service-deployment-5665df777c-zvgb7

이렇게 pid가 뜨고, 이걸로 GET요청을 넣으면, 

curl -X GET http://localhost:8002/api/products/P67fa37615a415218d868a076
```

## e. test order module
```bash
############################################################
############################################################
############################################################
# order test 
minikube tunnel

kubectl port-forward service/order-service 8003:8000

http://localhost:8003/docs#/

# case1) create order -> create payment 
ync url -X POST http://localhost:8003/api/orders/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "681873281feb45037e7c0f89",
    "items": [
      {
        "product_id": "68187370dcaaa7c74565a1fc",
        "quantity": 1
      }
    ]
  }'
 

# case2) create order -> create payment(fail!) -> rollback payment -> rollback order -> rollback product stock reserved
curl -X POST http://localhost:8003/api/orders/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "6809e8f9bdb0cf8790a01384",
    "items": [
      {
        "product_id": "P6809e908df4af07e566a3e88",
        "quantity": 10
      }
    ]
  }'


# 테스트
curl -X GET http://localhost:8003/api/orders/1
curl -X GET http://localhost:8003/api/orders/user/67f7b009803cf6478b3f502b
curl -X PUT http://localhost:8003/api/orders/1/status \
  -H "Content-Type: application/json" \
  -d '{
    "status": "SHIPPED"
  }'
```



## f. test category inside product module
```bash
############################################################
############################################################
############################################################
# category test

# Product Service (8002 포트로 포워딩)
kubectl port-forward service/product-service 8002:8000

# Create a top-level category
curl -X POST http://localhost:8002/api/categories/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Electronics"
  }'

curl -X POST http://localhost:8002/api/categories/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Laptops",
    "parent_id": 1
  }'

# get 
curl -X GET http://localhost:8002/api/categories/
curl -X GET http://localhost:8002/api/categories/1/
curl -X GET http://localhost:8002/api/categories/1/subcategories
```

## g. payment 모듈 테스트 
1. create_order() 하면,
2. category_product mysql database에 outbox 테이블에 write 되고,
3. 그걸 debezium이 outbox table 변화를 감지해서 kafka에 'order' 토픽에 'order_created' 이벤트로 메시지를 보내면,
4. payment module에서 해당 토픽을 subscribe해서 가져와서
5. create_payment()를 처리하고,
6. category_product mysql database에 payments 테이블을 업데이트 한다.

```bash
# 포트 열기
kubectl port-forward service/payment-service 8004:8000

# health check
curl -X GET http://localhost:8004/health

# 특정 결제의 모든 트랜잭션 조회
curl -X GET http://localhost:8004/api/payments/
```


## h. 각 모듈의 컨테이너에서 다른 모듈의 컨테이너와 통신하기
```bash
# product pod 이름 가져오기
POD_NAME=$(kubectl get pod -l app=product-service -o jsonpath="{.items[0].metadata.name}")

# pod 내부로 들어가기
kubectl exec -it $POD_NAME -- /bin/bash

# pod 내부에서 테스트 (curl이 없으면 설치)
apt-get update && apt-get install -y curl

curl http://localhost:8000/

# 또는 다른 서비스로 테스트
curl http://user-service:8000/

curl http://order-service:8000/
```


## i. api-gateway
```bash
minikube tunnel

minikube addons enable ingress

curl -v -H "Host: my-deployed-app.com" http://localhost:80/
curl -v -H "Host: my-deployed-app.com" http://localhost:80/api/products
curl -v -H "Host: my-deployed-app.com" http://localhost:80/api/users
curl -v -H "Host: my-deployed-app.com" http://localhost:80/api/orders
```


## j. mongodb stress test 

### step1) 디스크 용량 확보 
```bash 
# 1. 먼저 컨테이너 삭제 
minikube delete 

# 2. 도커 삭제 
docker system prune -a --volumes

# 3. k8s persistence 삭제 
kubectl get pv
kubectl get pvc
kubectl delete pv --all 
kubectl delete pvc --all 
```



### step2) 컨테이너 띄우기 
```bash
./test_elastic_search.sh

minikube tunnel
kubectl port-forward service/product-service 8002:8000 
curl -X GET http://localhost:8002/api/products/
```

### step3) mongodb 접속 
```bash
kubectl exec -it mongodb-stateful-0 -- mongoimport --db my_db --collection products --file /tmp/products.json --jsonArray --username username --password password --authenticationDatabase admin 

show dbs
use my_db
show collections
use products;

db.products.countDocuments()
db.products.find()
```

### step4) debezium 끄기 
bulk insert를 할껀데, 용량이 크다보니까, 대용량 .json파일을 mongodb & elastic search에 다이렉트로 import 할 계획임.

monstache가 켜져있으면, mongodb에 bulk insert를 하면, 얘가 elastic search로 옮기는 과정에서 OOM이 뜸.

```bash 
kubectl delete -f k8_config/monstache_depl_serv.yaml
```

### step5) fake data generate 

먼저 fake data를 만든다.
```bash 
npm install @faker-js/faker
cd faker.js
node generate-products.js
mv products.json faker.js/products.json
```

### step6) 100만개 상품 데이터를 mongodb container 내부로 복사 후 import 

먼저 파일을 컨테이너 내부로 복사한 후,
```bash 
kubectl cp faker.js/products.json mongodb-stateful-0:/tmp/products.json

kubectl exec -it mongodb-stateful-0 -- ls -la /tmp/ 

kubectl exec -it mongodb-stateful-0 -- cat /tmp/products.json | head -20
```

mongoimport로 대용량 .json 파일을 mongodb로 import 
```bash
kubectl exec -it mongodb-stateful-0 -- mongoimport --db my_db --collection products --file /tmp/products.json --jsonArray --username username --password password --authenticationDatabase admin
```

### step7) mongodb에 데이터 잘 들어갔는지 확인 
```bash
kubectl exec -it mongodb-stateful-0 -- mongosh -u username -p password --authenticationDatabase admin

show dbs
use my_db
show collections
db.products.countDocuments()
```


### step8) 단일 curl의 get_product() latency 측정 
```bash
curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nStartTransfer: %{time_starttransfer}s\nTotal: %{time_total}s\n" http://localhost:8002/api/products/mongodb/681308c41a83e18951fc9320
```
로컬 서버라서 DNS 조회(time_namelookup)는 거의 0에 가깝고,
실제로는 Connect, StartTransfer, Total이 주요 지표가 됩니다.


### step9) stress test를 위한 pid 가져오기 
```bash
cd stress_test
kubectl cp extract_sample_ids.js mongodb-stateful-0:/tmp/extract_sample_ids.js
kubectl exec -it mongodb-stateful-0 -- mongosh -u username -p password --authenticationDatabase admin --file /tmp/extract_sample_ids.js > product_ids.json
products.json 앞부분에 에러 메시지 지우기 
```

stress_test/product_ids.json에서 pid를 찾아 
mongodb 내부에서는 이렇게 검색
```bash
db.products.find({ _id: ObjectId('6813050e874120563f9ddd1f') })
db.products.find({ _id: ObjectId('681308c41a83e18951fc92d4') })

curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nStartTransfer: %{time_starttransfer}s\nTotal: %{time_total}s\n" http://localhost:8002/api/products/mongodb/681308c41a83e18951fc9320
DNS: 0.000010s
Connect: 0.000213s
StartTransfer: 0.068543s
Total: 0.068646s%
```

### step10) 동시요청 300개일 때 get_product() latency 측정 
```bash
cd stress_test

docker run -i --network host --volume $(pwd):/app -w /app grafana/k6 run product_load_test_mongodb.js
```


## k. elastic search에 stress test

### step1) kibana 띄우기 
```bash
minikube service kibana-service 
```

### step2) elastic search로 bulk insert 
```bash
# bulk insert를 위한 pip lib 설치 
pip install requests ijson tqdm 

#먼저 포트를 열고 
kubectl port-forward svc/elasticsearch-service 9201:9200 

# local에서 컨테이너로 보내기 
python faker.js/local_bulk_convert.py
```

### step3) kibana에 데이터가 잘 들어왔는지 확인
```bash
minikube service kibana-service 

http://127.0.0.1:62668/app/discover#/ 

click discover tap -> create data view
없으면 stack management -> data views -> create data view 

1. name: product
2. index pattern: my_db.products*
3. timestamp field: 적용 안한다 선택 (왜냐면 faker.js에서 가데이터 생성시 created_at 필드 없어서 인식을 못함)
click save data to kibana 

우상단에 refresh 버튼 누르면, 실시간으로 데이터 몇개 들어와있는지 알려줌 
```

### step4) curl로 확인하기 

```bash
먼저 kibana에서 product의 pid 하나 딴 다음,

curl -X GET http://localhost:8002/api/products/13vGipYBmLM9sfFoDGu8

curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nStartTransfer: %{time_starttransfer}s\nTotal: %{time_total}s\n" http://localhost:8002/api/products/2nvGipYBmLM9sfFoDGu8

DNS: 0.000012s
Connect: 0.000232s
StartTransfer: 0.184723s
Total: 0.184896s
```

어? 아까 mongodb에는 62ms 걸렸는데 elatic search는 18ms 걸리네?


### step5) 샘플 pid 10000개 가져오기 
```bash
cd stress_test

python extract_sample_ids_from_es.py
```

### step6) stress test 
```bash
docker run -i --network host --volume $(pwd):/app -w /app grafana/k6 run product_load_test_es.js
```


### step7) elastic search에 용량 얼마나 차지했는지 확인

100만개 상품데이터는 1.1GB
@elastic_depl_serv.yaml 에 8GB 잡았다.
```bash
# elatic search pod의 이름 따기
kubectl get pod

# Pod에 직접 접속해서
kubectl exec -it elasticsearch-deployment-6cc87f8677-98d99 -- bash

# 내부에서 API 호출
curl -X GET "localhost:9200/_cat/indices?v=true&pretty"

# 세부정보  
curl -X GET "localhost:9200/_nodes/stats?pretty"
```


## l. elastic search 검색 

### step1) create fake data & insert into elastic search
```bash
node faker.js/product-generator.js
mv products.json faker.js/product.json
minikube tunnel 
kubectl port-forward svc/elasticsearch-service 9201:9200
python faker.js/local_bulk_convert.py
```


### step2) create index & re-index 
```bash
kubectl port-forward service/product-service 8002:8000
curl -X POST http://localhost:8002/api/search/admin/create-index
curl -X POST http://localhost:8002/api/search/admin/reindex
```

### step3) 다양한 검색 
```bash
# 기본 검색 
curl -G "http://localhost:8002/api/search/basic" --data-urlencode "query=노트북" | grep title

# 가중치 검색 
curl -G "http://localhost:8002/api/search/weighted" --data-urlencode "query=삼성노트북"

# 자동 완성 검색 
curl -G "http://localhost:8002/api/search/autocomplete" --data-urlencode "prefix=삼"

# 퍼지 검색 
curl -G "http://localhost:8002/api/search/fuzzy" --data-urlencode "query=삼성노트북"

# 고급 검색 
curl -G "http://localhost:8002/api/search/advanced" \
  --data-urlencode "query=노트북" \
  --data-urlencode "brand=삼성" \
  --data-urlencode "min_price=1000" \
  --data-urlencode "max_price=2000000" \
  --data-urlencode "processor=i7" \
  --data-urlencode "ram=16GB"
```

### step4) new data to mongodb -> monstache -> elatic search 이 후, 부분 reindex 
1. 먼저 kibana를 통해 elastic search에 `my_db.products`에 총 몇개의 상품이 있는지 확인. (stack management -> data view -> my_db.products* -> save -> discover tab -> hit 갯수 확인)

2. 다음으로 kibana를 통해 elastic search에 인덱싱된 `product_search`가 몇개 있는지 확인 

3. create_product()로 상품을 만들면, monstache가 elastic search로 sync해준다.
```bash
# Product Service (8002 포트로 포워딩)
kubectl port-forward service/product-service 8002:8000

curl -X POST http://localhost:8002/api/products/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "ddd Apple 2025 MacBook Pro",
    "description": "최신 Apple MacBook Pro, M3 Max 칩, 16인치 Liquid Retina XDR 디스플레이",
    "brand": "Apple",
    "model": "MUW73LL/A",
    "sku": "MBP-16-M3-MAX",
    "upc": "195949185694",
    "color": "Space Gray",
    "category_ids": [1, 2, 4],
    "category_path": "1/2/4",
    "category_level": 3,
    "primary_category_id": 4,
    "category_breadcrumbs": ["전자제품", "컴퓨터", "노트북"],
    "price": {
      "amount": 3499.99,
      "currency": "USD"
    },
    "stock": 100, 
    "weight": {
      "value": 4.8,
      "unit": "POUND"
    },
    "dimensions": {
      "length": 14.01,
      "width": 9.77,
      "height": 0.66,
      "unit": "INCH"
    },
    "attributes": {
      "processor": "M3 Max",
      "ram": "32GB",
      "storage": "1TB SSD",
      "screen_size": "16 inch",
      "resolution": "3456 x 2234"
    },
    "variants": [
      {
        "id": "variant1",
        "sku": "MBP-16-M3-MAX-SG-32GB-1TB",
        "color": "Space Gray",
        "storage": "1TB",
        "price": {
          "amount": 3499.99,
          "currency": "USD"
        },
        "attributes": {
          "processor": "M3 Max",
          "ram": "32GB"
        },
        "inventory": 50
      },
      {
        "id": "variant2",
        "sku": "MBP-16-M3-MAX-SIL-32GB-1TB",
        "color": "Silver",
        "storage": "1TB",
        "price": {
          "amount": 3499.99,
          "currency": "USD"
        },
        "attributes": {
          "processor": "M3 Max",
          "ram": "32GB"
        },
        "inventory": 35
      }
    ],
    "images": [
      {
        "url": "https://example.com/macbook-pro-1.jpg",
        "main": true
      },
      {
        "url": "https://example.com/macbook-pro-2.jpg",
        "main": false
      }
    ]
  }'
```

4. kibana에서 `my_db.products`에 갯수가 1개 올라갔지만, `products_search`에는 갯수가 안올라간걸 확인한다.
5. 부분 reindex를 한다.
```bash
curl -X POST http://localhost:8002/api/search/admin/incremental-reindex
curl -X GET http://localhost:8002/api/search/admin/reindex-status
```

6. kibana에서 `products_search`에 갯수가 올라간걸 확인한다.
