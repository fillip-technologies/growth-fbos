from fastapi import HTTPException, status

# Define service-specific HTTP exceptions following this pattern:
#
# class OrderNotFoundError(HTTPException):
#     def __init__(self) -> None:
#         super().__init__(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail={"code": "ORDER_NOT_FOUND", "message": "Order not found", "status": 404},
#         )
