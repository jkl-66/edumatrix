import bcrypt
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from config import CONFIG
from app.database import DBUser, run_db_op

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
    """创建 JWT 访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=CONFIG.auth_access_token_expire_minutes)
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
        # 本地开发/演示环境下，前台未集成登录时自动降级为默认的 demo-student 用户，防止 401 报错
        def get_or_create_demo(session):
            user = session.query(DBUser).filter(DBUser.username == "demo-student").first()
            if not user:
                user = DBUser(username="demo-student", hashed_password=get_password_hash("demo-password"))
                session.add(user)
                session.commit()
                session.refresh(user)
            return user
        return await run_db_op(get_or_create_demo)

    try:
        payload = jwt.decode(token, CONFIG.auth_secret_key, algorithms=[CONFIG.auth_algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    def fetch_user(session):
        return session.query(DBUser).filter(DBUser.username == username).first()

    user = await run_db_op(fetch_user)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    return user

def authenticate_user(db, username: str, password: str) -> Optional[DBUser]:
    """验证用户凭据并返回用户对象"""
    user = db.query(DBUser).filter(DBUser.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
