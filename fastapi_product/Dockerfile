FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install protoc
# RUN apt-get update && apt-get install -y protobuf-compiler

# Copy proto files
COPY proto/ proto/
# Compile proto files
RUN python -m grpc_tools.protoc \
    --python_out=. \
    --grpc_python_out=. \
    --proto_path=proto \
    proto/*.proto
# # Copy proto files
# COPY proto/product.proto .

# # Compile proto files to app/grpc directory
# RUN mkdir -p app/grpc && \
#     python -m grpc_tools.protoc \
#         --python_out=app/grpc \
#         --grpc_python_out=app/grpc \
#         --proto_path=. \
#         product.proto

# Copy application code
COPY app/ app/

# Clean up proto files after compilation
# RUN rm -f product.proto

# Expose ports
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]