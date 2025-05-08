#!/bin/bash

# 실패해도 계속 진행하도록 설정
set +e

echo "Copying proto files..."
cp proto/product.proto fastapi_product/proto/
    
# Clean up existing resources
echo "Cleaning up existing resources..."
kubectl delete deployments --all || true
kubectl delete services --all || true
kubectl delete ingress --all || true
kubectl delete pvc --all || true
kubectl delete pv --all || true
kubectl delete statefulsets --all || true

# Deploy MongoDB
echo "Deploying MongoDB..."
kubectl apply -f ./k8_configs/mongo_secrets.yaml
kubectl apply -f ./k8_configs/mongo_configmap.yaml
kubectl apply -f ./k8_configs/mongo_depl_serv.yaml

# Wait for MongoDB to be ready with timeout
echo "Waiting for MongoDB to be ready..."
kubectl wait --for=condition=Ready pod/mongodb-stateful-0 --timeout=180s
kubectl wait --for=condition=Ready pod/mongodb-stateful-1 --timeout=180s
echo "MongoDB readiness check completed with status $?"

# Initialize MongoDB Replica Set
echo "Initializing MongoDB Replica Set..."
kubectl exec -it mongodb-stateful-0 -- mongosh -u $MONGO_INITDB_ROOT_USERNAME -p $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin --eval '
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongodb-stateful-0.mongodb-service.default.svc.cluster.local:27017" },
    { _id: 1, host: "mongodb-stateful-1.mongodb-service.default.svc.cluster.local:27017" }
    { _id: 2, host: "mongodb-stateful-2.mongodb-service.default.svc.cluster.local:27017" }
  ]
})'

# Wait for Replica Set to be ready
echo "Waiting for Replica Set to be ready..."
sleep 10

# Deploy MySQL
echo "Deploying MySQL..."
kubectl apply -f ./k8_configs/mysql_depl_serv.yaml

# Wait for MySQL pod to exist before getting its name
echo "Checking for MySQL pods..."
sleep 10
kubectl get pods -l app=mysql

# Get MySQL pod name with fallback
MYSQL_POD=$(kubectl get pods -l app=mysql -o jsonpath="{.items[0].metadata.name}" 2>/dev/null || echo "mysql-pod-not-found")
echo "MySQL pod: $MYSQL_POD"

if [ "$MYSQL_POD" != "mysql-pod-not-found" ]; then
  echo "Waiting for MySQL to be ready..."
  kubectl wait --for=condition=Ready pod/$MYSQL_POD --timeout=180s
  echo "MySQL readiness check completed with status $?"
else
  echo "MySQL pod not found, skipping readiness check"
fi

echo "Deploying Kafka..."
kubectl apply -f k8_configs/kafka_configmap.yaml
kubectl apply -f k8_configs/zookeeper_depl_serv.yaml
kubectl apply -f k8_configs/kafka_depl_serv.yaml

# Deploy ELK Stack
echo "Deploying ELK Stack..."
kubectl apply -f k8_configs/logstash-config.yaml
kubectl apply -f ./k8_configs/elastic_depl_serv.yaml
kubectl apply -f ./k8_configs/logstash_depl_serv.yaml
kubectl apply -f ./k8_configs/kibana_depl_serv.yaml

# Wait for Elasticsearch with appropriate timeout
echo "Waiting up to 3 minutes for Elasticsearch to be ready..."
kubectl wait --for=condition=Ready pod -l app=elasticsearch --timeout=180s
ES_STATUS=$?
echo "Elasticsearch readiness check completed with status $ES_STATUS"

# If Elasticsearch is ready, wait for Logstash and Kibana
if [ $ES_STATUS -eq 0 ]; then
  echo "Waiting for Logstash to be ready..."
  kubectl wait --for=condition=Ready pod -l app=logstash --timeout=180s
  echo "Logstash readiness check completed with status $?"

  echo "Waiting for Kibana to be ready..."
  kubectl wait --for=condition=Ready pod -l app=kibana --timeout=180s
  echo "Kibana readiness check completed with status $?"
fi

# Deploy Monstache
echo "Deploying Monstache..."
kubectl apply -f ./k8_configs/monstache_depl_serv.yaml

# Wait for Monstache with timeout
echo "Waiting for Monstache to be ready..."
kubectl wait --for=condition=Ready pod -l app=monstache --timeout=180s
echo "Monstache readiness check completed with status $?"

# Deploy Product Service
echo "Deploying Product Service..."
kubectl apply -f ./k8_configs/fastapi_product_deployment.yaml

# Wait for Product Service with timeout
echo "Waiting for Product Service to be ready..."
kubectl wait --for=condition=Ready pod -l app=product-service --timeout=180s
echo "Product Service readiness check completed with status $?"

# Check if Ingress resources exist before applying
echo "Checking for Ingress resources..."
if kubectl get ingress &>/dev/null; then
  # Deploy Nginx API Gateway
  echo "Deploying Nginx API Gateway..."
  kubectl apply -f ./k8_configs/ingress.yaml

  # Wait for Ingress to be ready
  echo "Waiting for Ingress to be ready..."
  kubectl wait --for=condition=Ready ingress --all --timeout=180s
  echo "Ingress readiness check completed with status $?"
else
  echo "Ingress controller not detected, skipping Ingress deployment"
fi

echo "All services deployed successfully. Checking pod status:"
kubectl get pods