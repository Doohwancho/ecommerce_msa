#!/bin/bash

set -e # Stop on error

# kubectl delete all --all # Delete all the pods and services running

# Remove the Docker images
# docker rmi fastapi-image-test-k8 || true # || true means if error comes, skip onto next process
# docker rmi doohwancho/fastapi-image-test-k8 || true


# 프로토 파일을 각 서비스 디렉토리에 복사
echo "Copying proto files..."
cp proto/user.proto fastapi_user/proto/
cp proto/product.proto fastapi_product/proto/
cp proto/order.proto fastapi_order/proto/
cp proto/user.proto fastapi_order/proto/
cp proto/product.proto fastapi_order/proto/

# 사용자 서비스 빌드
echo "Building user service..."
docker build --no-cache -t fastapi-user-service:latest ./fastapi_user/.
docker tag fastapi-user-service:latest doohwancho/fastapi-user-service:latest
docker push doohwancho/fastapi-user-service:latest

# 상품 서비스 빌드
echo "Building product service..."
docker build --no-cache -t fastapi-product-service:latest ./fastapi_product/.
docker tag fastapi-product-service:latest doohwancho/fastapi-product-service:latest
docker push doohwancho/fastapi-product-service:latest

# 주문 서비스 빌드
echo "Building order service..."
docker build --no-cache -t fastapi-order-service:latest ./fastapi_order/.
docker tag fastapi-order-service:latest doohwancho/fastapi-order-service:latest
docker push doohwancho/fastapi-order-service:latest



# Delete all the Kubernetes deployments
# kubectl delete deployment fastapi-deployment || true
# kubectl delete deployment mongo-express-deployment || true
# kubectl delete deployment kibana-deployment || true
# kubectl delete deployment logstash-deployment || true
# kubectl delete deployment elasticsearch-deployment || true
kubectl delete deployments --all
# kubectl delete services user-service product-service order-service || true

# Delete MySQL PVC and PV
echo "Deleting MySQL PVC and PV..."
kubectl delete pvc mysql-pv-claim || true
kubectl delete pv mysql-pv-volume || true

# Delete all Ingress resources
echo "Deleting existing Ingress resources..."
# kubectl delete ingress ingress-routing
kubectl delete ingress --all || true


# Delete the Services
kubectl delete services fastapi-app-service || true
kubectl delete services mongo-express-service || true
kubectl delete services mongodb-service || true
kubectl delete services mysql-service || true
# kubectl delete services kibana-service || true
# kubectl delete services logstash-service || true
# kubectl delete services elasticsearch-service || true

# Delete all StatefulSets
# kubectl delete  statefulset mongodb-stateful || true
kubectl delete statefulsets --all


# Build the Docker image
docker build --no-cache -t fastapi-image-test-k8 ./fastapi_monolith/.

# Tag and push the Docker image
docker tag fastapi-image-test-k8 doohwancho/fastapi-image-test-k8
docker push doohwancho/fastapi-image-test-k8

# Apply all the files in stepwise manner
# kubectl apply -f ./k8_configs/storage-class.yaml
kubectl apply -f ./k8_configs/mongo_secrets.yaml # secrets
kubectl apply -f ./k8_configs/mongo_configmap.yaml # Configs
kubectl apply -f ./k8_configs/mongo_depl_serv.yaml # DB should be run first. One files has deployment and service

# Wait for MongoDB StatefulSet to create the pod
echo "Waiting for MongoDB pod to be created..."
sleep 10  # Give Kubernetes some time to create the pod

# Check if the pod exists before waiting for it to be ready
POD_EXISTS=false
for i in {1..10}; do
  if kubectl get pod mongodb-stateful-0 >/dev/null 2>&1; then
    POD_EXISTS=true
    break
  fi
  echo "Waiting for MongoDB pod to be created... attempt $i/10"
  sleep 5
done

if [ "$POD_EXISTS" = true ]; then
  echo "MongoDB pod created, waiting for it to be ready..."
  kubectl wait --for=condition=Ready pod/mongodb-stateful-0 --timeout=180s
else
  echo "ERROR: MongoDB pod was not created within the timeout period."
  kubectl get pods
  exit 1
fi


kubectl apply -f ./k8_configs/mysql_depl_serv.yaml

# MySQL 파드가 생성되고 준비될 때까지 기다리기
echo "Deploying MySQL. Waiting for MySQL pod to be created..."
sleep 10  # MySQL 파드 생성을 위한 대기 시간

# MySQL 파드가 존재하는지 확인
MYSQL_POD_EXISTS=false
for i in {1..15}; do  # 시도 횟수 증가 (최대 15번)
  if kubectl get pods -l app=mysql --no-headers 2>/dev/null | grep -q .; then
    MYSQL_POD_EXISTS=true
    MYSQL_POD=$(kubectl get pods -l app=mysql -o jsonpath="{.items[0].metadata.name}")
    break
  fi
  echo "Waiting for MySQL pod to be created... attempt $i/15"
  sleep 10  # 대기 시간 증가
done

if [ "$MYSQL_POD_EXISTS" = true ]; then
  echo "MySQL pod ${MYSQL_POD} created, waiting for it to be ready..."
  # 타임아웃 시간 증가 (5분)
  kubectl wait --for=condition=Ready pod/$MYSQL_POD --timeout=300s
  echo "MySQL pod is ready."
else
  echo "WARNING: MySQL pod was not created within the timeout period."
  echo "Current pods:"
  kubectl get pods
  echo "Continuing anyway, but services may not function correctly..."
fi



# Both databases are ready, now deploy the rest
echo "All databases are ready. Deploying remaining services..."



# Then deploy the next service (e.g., Mongo Express)
kubectl apply -f ./k8_configs/mongo_express_depl_serv.yaml # One file for both deployment and service

# run the rest
kubectl apply -f ./k8_configs/fastapi_user_deployment.yaml
kubectl apply -f ./k8_configs/fastapi_product_deployment.yaml
kubectl apply -f ./k8_configs/fastapi_order_deployment.yaml
# kubectl apply -f ./k8_configs/fastapi_deployment_file.yaml # FastAPI Deployment pod
# kubectl apply -f ./k8_configs/fastapi_service_file.yaml # FastAPI service

# ELK
# kubectl apply -f k8_configs/logstash-config.yaml
# kubectl apply -f ./k8_configs/elastic_depl_serv.yaml # Elastic Search
# kubectl apply -f ./k8_configs/logstash_depl_serv.yaml  # Logstash
# kubectl apply -f ./k8_configs/kibana_depl_serv.yaml  # kibana dashboard
kubectl apply -f ./k8_configs/ingress.yaml # Enable ingress for routing

echo "All deployments completed. Checking pod status:"

kubectl get pods
