import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from config import CONFIG
from app.database import DBUser, run_db_op
from app.identity import normalize_role

# OAuth2 方案配置
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否与哈希密码匹配"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """对明文密码进行哈希处理"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT 访问令牌，包含用户角色"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=CONFIG.auth_access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, CONFIG.auth_secret_key, algorithm=CONFIG.auth_algorithm)
    return encoded_jwt

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> DBUser:
    """获取当前已认证用户的依赖项"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        if not CONFIG.demo_mode:
            raise credentials_exception
        def get_or_create_demo(session):
            user = session.query(DBUser).filter(DBUser.username == "demo-student").first()
            if not user:
                user = DBUser(username="demo-student", hashed_password=get_password_hash("demo-password"), role="student", display_name="演示学生")
                session.add(user)
                session.commit()
                session.refresh(user)
            return user
        return await run_db_op(get_or_create_demo)

    try:
        payload = jwt.decode(token, CONFIG.auth_secret_key, algorithms=[CONFIG.auth_algorithm])
        public_id: str = payload.get("uid") or payload.get("sub")
        username: str = payload.get("username")
        if public_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    def fetch_user(session):
        query = session.query(DBUser)
        user = query.filter(DBUser.public_id == public_id).first()
        # Compatibility with tokens issued before S1-001. New tokens never use
        # the username as their authority subject.
        if user is None and username:
            user = query.filter(DBUser.username == username).first()
        if user is None and public_id and not username:
            user = query.filter(DBUser.username == public_id).first()
        return user

    user = await run_db_op(fetch_user)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    return user

async def get_current_teacher(user: DBUser = Depends(get_current_user)) -> DBUser:
    """教师权限依赖：仅允许教师角色访问"""
    if normalize_role(user.role) not in {"teacher", "admin", "assistant"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅教师可访问此接口",
        )
    return user


def enforce_student_access(requested_student_id: str | None, user: DBUser) -> str:
    """Resolve a student scope from the authenticated user instead of trusting input."""
    requested = str(requested_student_id or "").strip()
    if requested == "default":
        requested = ""
    if user.role == "teacher":
        if not requested:
            raise HTTPException(status_code=400, detail="student_id 不能为空")
        return requested
    if requested and requested != user.username:
        raise HTTPException(status_code=403, detail="无权访问其他学生的数据")
    return user.username


async def enforce_request_student_scope(
    student_id: str | None = None,
    user: DBUser = Depends(get_current_user),
) -> DBUser:
    """Authenticate a route and validate path/query student_id when present."""
    # Body-scoped routes resolve their target after parsing JSON. Do not reject
    # a teacher before the handler has had a chance to read that target.
    if student_id is not None:
        enforce_student_access(student_id, user)
    elif user.role != "teacher":
        enforce_student_access(None, user)
    return user

def authenticate_user(db, username: str, password: str) -> Optional[DBUser]:
    """验证用户凭据并返回用户对象"""
    user = db.query(DBUser).filter(DBUser.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
