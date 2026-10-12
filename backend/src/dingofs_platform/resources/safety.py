"""Output redaction and product error detection, independent of transport."""

import json
import re

SENSITIVE = re.compile(
    r"(?:secret|password|passwd|credential|access.?key|(^|[._])ak$|(^|[._])sk$|(^|[._])key$|token)",
    re.I,
)


def redact(value, secrets=(), *, show_storage_keys=False):
    if isinstance(value, dict):
        return {
            k: v
            if show_storage_keys and k.lower() in {"ak", "sk"}
            else "[REDACTED]" if SENSITIVE.search(k)
            else redact(v, secrets, show_storage_keys=show_storage_keys)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, secrets, show_storage_keys=show_storage_keys) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        try:
            nested = json.loads(value)
            if isinstance(nested, (dict, list)):
                return json.dumps(redact(nested, secrets, show_storage_keys=show_storage_keys), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
        pattern = re.compile(
            r"(?i)((?<![\w])(?:--)?[\"']?(?:[\w.-]*(?:password|passwd|secret|access_?key|secret_?key|credential|token)|(?:s3[._])?(?:ak|sk)|(?:rados[._])?key)[\"']?\s*(?:[=:]\s*|\s+))"
            r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}]+)"
        )
        return pattern.sub(lambda match: match[1] + "[REDACTED]", value)
    return value


def product_failed(value):
    if not isinstance(value, dict):
        return False
    for field in ("error",):
        error = value.get(field)
        if isinstance(error, dict):
            for key in ("code", "errcode"):
                if key in error and error[key] not in (0, "0", "OK", "kOk", None):
                    return True
    if value.get("returncode", 0) != 0 or value.get("success") is False:
        return True
    return any(product_failed(value.get(k)) for k in ("result", "data"))
