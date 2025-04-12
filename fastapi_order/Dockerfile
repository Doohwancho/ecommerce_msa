FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install protoc
RUN apt-get update && apt-get install -y protobuf-compiler

# Copy and compile proto files
COPY proto/ proto/

RUN python -m grpc_tools.protoc \
    --python_out=. \
    --grpc_python_out=. \
    --proto_path=proto \
    proto/*.proto

# Copy application code
COPY app/ app/

# Expose ports
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]