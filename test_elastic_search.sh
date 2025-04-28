#!/bin/bash

set -e # Stop on error

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

# Wait for MongoDB to be ready
echo "Waiting for MongoDB to be ready..."
kubectl wait --for=condition=Ready pod/mongodb-stateful-0 --timeout=180s

# Deploy MySQL
echo "Deploying MySQL..."
kubectl apply -f ./k8_configs/mysql_depl_serv.yaml

# Wait for MySQL to be ready
echo "Waiting for MySQL to be ready..."
MYSQL_POD=$(kubectl get pods -l app=mysql -o jsonpath="{.items[0].metadata.name}")
kubectl wait --for=condition=Ready pod/$MYSQL_POD --timeout=300s

# Deploy Kafka
echo "Deploying Kafka..."
kubectl apply -f k8_configs/kafka_configmap.yaml
kubectl apply -f k8_configs/zookeeper_depl_serv.yaml

# Wait for Zookeeper to be ready first
echo "Waiting for Zookeeper to be ready..."
kubectl wait --for=condition=Ready pod -l app=zookeeper --timeout=300s

# Then deploy Kafka
kubectl apply -f k8_configs/kafka_depl_serv.yaml

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
kubectl wait --for=condition=Ready pod -l app=kafka --timeout=300s

# Create Kafka topic
echo "Creating Kafka topic..."
kubectl exec -it $(kubectl get pods -l app=kafka -o jsonpath="{.items[0].metadata.name}") -- \
  /opt/kafka/bin/kafka-topics.sh --create --topic order --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1

# Deploy ELK Stack
echo "Deploying ELK Stack..."
kubectl apply -f k8_configs/logstash-config.yaml
kubectl apply -f ./k8_configs/elastic_depl_serv.yaml
kubectl apply -f ./k8_configs/logstash_depl_serv.yaml
kubectl apply -f ./k8_configs/kibana_depl_serv.yaml

# Wait for ELK components to be ready
echo "Waiting for ELK components to be ready..."
kubectl wait --for=condition=Ready pod -l app=elasticsearch --timeout=300s
kubectl wait --for=condition=Ready pod -l app=logstash --timeout=300s
kubectl wait --for=condition=Ready pod -l app=kibana --timeout=300s

# Deploy Monstache
echo "Deploying Monstache..."
kubectl apply -f ./k8_configs/monstache_depl_serv.yaml

# Wait for Monstache to be ready
echo "Waiting for Monstache to be ready..."
kubectl wait --for=condition=Ready pod -l app=monstache --timeout=300s

# Deploy Product Service
echo "Deploying Product Service..."
kubectl apply -f ./k8_configs/fastapi_product_deployment.yaml

# Wait for Product Service to be ready
echo "Waiting for Product Service to be ready..."
kubectl wait --for=condition=Ready pod -l app=product-service --timeout=300s

# Deploy Nginx API Gateway
echo "Deploying Nginx API Gateway..."
kubectl apply -f ./k8_configs/ingress.yaml

# Wait for Ingress to be ready
echo "Waiting for Ingress to be ready..."
kubectl wait --for=condition=Ready ingress --all --timeout=300s

echo "All services deployed successfully. Checking pod status:"
kubectl get pods 