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

# 결제 서비스 빌드
echo "Building payment service..."
docker build --no-cache -t fastapi-payment-service:latest ./fastapi_payment/.
docker tag fastapi-payment-service:latest doohwancho/fastapi-payment-service:latest
docker push doohwancho/fastapi-payment-service:latest



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
kubectl delete services mongo-express-service || true
kubectl delete services mongodb-service || true
kubectl delete services mysql-service || true
# kubectl delete services kibana-service || true
# kubectl delete services logstash-service || true
# kubectl delete services elasticsearch-service || true

# Delete Debezium resources
kubectl delete job register-debezium-connector --ignore-not-found=true
kubectl delete deployment debezium-connect --ignore-not-found=true
kubectl delete service debezium-connect --ignore-not-found=true

# Delete all StatefulSets
# kubectl delete  statefulset mongodb-stateful || true
kubectl delete statefulsets --all


# Build the Docker image
# docker build --no-cache -t fastapi-image-test-k8 ./fastapi_monolith/.

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
sleep 10  # Give Kubernetes some time to create the pod)


echo "Deploying Kafka..."
kubectl apply -f k8_configs/kafka_configmap.yaml
kubectl apply -f k8_configs/zookeeper_depl_serv.yaml
kubectl apply -f k8_configs/kafka_depl_serv.yaml


echo "Deploying MySQL..."
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
kubectl apply -f ./k8_configs/fastapi_payment_deployment.yaml
# kubectl apply -f ./k8_configs/fastapi_deployment_file.yaml # FastAPI Deployment pod
# kubectl apply -f ./k8_configs/fastapi_service_file.yaml # FastAPI service

# ELK
# kubectl apply -f k8_configs/logstash-config.yaml
# kubectl apply -f ./k8_configs/elastic_depl_serv.yaml # Elastic Search
# kubectl apply -f ./k8_configs/logstash_depl_serv.yaml  # Logstash
# kubectl apply -f ./k8_configs/kibana_depl_serv.yaml  # kibana dashboard


# --- DEBEZIUM DEPLOYMENT PHASE (Revised) ---
echo "Deploying Debezium Connect..."
# 1. Apply the Debezium Deployment and Service (ensure this file DOES NOT have the initContainer)
kubectl apply -f ./k8_configs/debezium-deployment.yaml

# 2. Wait for the Debezium Connect Deployment to be available and ready
echo "Waiting for Debezium Connect Deployment to be available..."
if ! kubectl wait --for=condition=Available deployment/debezium-connect --timeout=300s; then
  echo "ERROR: Debezium Connect Deployment did not become available in time."
  kubectl get pods -l app=debezium-connect
  kubectl describe deployment debezium-connect
  exit 1
fi
echo "Debezium Connect Deployment is available. Waiting a bit for service readiness..."
sleep 15 # Give the service endpoint a moment to stabilize after pods are ready

# 3. Apply the Connector Registration Job (ensure this file uses the correct service name: debezium-connect)
echo "Applying Debezium connector registration Job..."
kubectl apply -f ./k8_configs/register-connector-job.yaml # Assuming you named the job file this

# 4. Optional: Wait for the Job to complete
echo "Waiting for connector registration Job to complete..."
if ! kubectl wait --for=condition=complete job/register-debezium-connector --timeout=180s; then
   echo "WARNING: Connector registration Job did not complete successfully in time."
   # Attempt to get logs from the job's pod
   JOB_POD=$(kubectl get pods --selector=job-name=register-debezium-connector --output=jsonpath='{.items[0].metadata.name}' 2>/dev/null)
   if [ -n "$JOB_POD" ]; then
       echo "Logs from Job Pod ($JOB_POD):"
       kubectl logs $JOB_POD
   else
       echo "Could not find Job Pod to retrieve logs."
   fi
   # Decide if this is a fatal error or just a warning
   # exit 1 # Uncomment if registration failure should stop the script
else
   echo "Connector registration Job completed successfully."
   # Optional: Clean up the completed job if you don't need its logs/status later
   # echo "Deleting completed connector registration job..."
   # kubectl delete job register-debezium-connector --ignore-not-found=true
fi
# --- END DEBEZIUM DEPLOYMENT ---


kubectl apply -f ./k8_configs/ingress.yaml # Enable ingress for routing

echo "All deployments completed. Checking pod status:"

kubectl get pods
