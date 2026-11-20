"""FastAPI dependencies for authentication and authorization."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .jwt_handler import decode_token

security = HTTPBearer()

ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1}


class CurrentUser:
    def __init__(self, user_id: str, username: str, role: str):
        self.user_id = user_id
        self.username = username
        self.role = role

    def has_role(self, minimum_role: str) -> bool:
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(minimum_role, 0)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return CurrentUser(
        user_id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
    )


def require_role(minimum_role: str):
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(minimum_role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return checker
