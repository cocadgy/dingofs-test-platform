"""Remove known task credentials from text returned through the report proxy."""
import json

def redact_report(data:bytes,secrets:list[str])->bytes:
    for secret in secrets:
        if not secret:continue
        replacements={secret.encode(),json.dumps(secret,ensure_ascii=False)[1:-1].encode()}
        for value in sorted(replacements,key=len,reverse=True):
            data=data.replace(value,b'[REDACTED]')
    return data
