"""Write-only machine credentials. Never include input values in errors."""

from cryptography.fernet import Fernet, InvalidToken
from dingofs_platform.errors import Problem


def _fernet(key: str) -> Fernet:
    if not key:
        raise Problem(
            503, "credential_key_missing", "尚未配置凭据加密密钥，请联系管理员"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        raise Problem(503, "credential_key_invalid", "凭据加密密钥配置无效") from None


def encrypt_password(value: str, key: str) -> str:
    return _fernet(key).encrypt(value.encode()).decode()


def decrypt_password(value: str, key: str) -> str:
    try:
        return _fernet(key).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError):
        raise Problem(
            503,
            "credential_decryption_failed",
            "无法解密 SSH 密码，请核对密钥或重新配置密码",
        ) from None


def credential_changes(data: dict, key: str) -> dict:
    data = dict(data)
    password = data.pop("ssh_password", None)
    clear = data.pop("clear_ssh_password", False)
    if clear and password:
        raise Problem(422, "credential_conflict", "设置密码和清除密码不能同时执行")
    if clear:
        data["ssh_password_ciphertext"] = None
    elif password:
        data["ssh_password_ciphertext"] = encrypt_password(password, key)
    return data
