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

## b. erd (mysql)
categories & products & orders & order_items

```sql
categories
----------
category_id (PK)
name
parent_id (FK -> categories.category_id)
level
path

category_products
----------------
product_id (PK) -> MongoDB product collection 참조
category_id (PK, FK -> categories.category_id)
is_primary (Boolean)

orders
------
order_id (PK)
user_id
status (enum: 'pending', 'processing', 'completed', 'cancelled')
total_amount
created_at
updated_at

order_items
----------
order_item_id (PK)
order_id (FK -> orders.order_id)
product_id (FK -> category_products.product_id)
quantity
price_at_order
created_at
```




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

## b. test user module
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


## c. test product module
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
    "title": "Apple 2023 MacBook Pro",
    "description": "최신 Apple MacBook Pro, M3 Max 칩, 16인치 Liquid Retina XDR 디스플레이",
    "brand": "Apple",
    "model": "MUW73LL/A",
    "sku": "MBP-16-M3-MAX",
    "upc": "195949185694",
    "color": "Space Gray",
    "category_ids": [1, 2, 4],
    "primary_category_id": 4,
    "category_breadcrumbs": ["전자제품", "컴퓨터", "노트북"],
    "price": {
      "amount": 3499.99,
      "currency": "USD"
    },
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

curl -X GET http://localhost:8002/api/products/P67f60c5af9dc66c37747ef8f
```

## d. test order module
```bash
############################################################
############################################################
############################################################
# order test 
minikube tunnel

kubectl port-forward service/order-service 8003:8000

http://localhost:8003/docs#/

curl -X POST http://localhost:8003/api/orders/ \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user 생성하고 나온 id 적기 (ex. 67f7b009803cf6478b3f502b)",
    "items": [
      {
        "product_id": "product 생성하고 나온 id 적기(ex. P67f7b01746aa16726c1d3660)",
        "quantity": 2
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



## e. test category inside product module
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

## f. 각 모듈의 컨테이너에서 다른 모듈의 컨테이너와 통신하기
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

## g. api-gateway
```bash
minikube tunnel

minikube addons enable ingress

curl -v -H "Host: my-deployed-app.com" http://localhost:80/
curl -v -H "Host: my-deployed-app.com" http://localhost:80/api/products
curl -v -H "Host: my-deployed-app.com" http://localhost:80/api/users
curl -v -H "Host: my-deployed-app.com" http://localhost:80/api/orders
```