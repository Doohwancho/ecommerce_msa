import asyncio

# Global variable to store the gRPC server task
grpc_task = None

def set_grpc_task(task):
    global grpc_task
    grpc_task = task

def get_grpc_task():
    return grpc_task 