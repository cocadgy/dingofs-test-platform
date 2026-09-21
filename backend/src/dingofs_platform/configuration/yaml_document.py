import io, re
from ruamel.yaml import YAML
from ruamel.yaml.tokens import AnchorToken, AliasToken, TagToken
from dingofs_platform.errors import Problem


def invalid(message="YAML 格式不支持或语法错误"):
    return Problem(422, "invalid_yaml", message)


def parse(text):
    if len(text.encode()) > 1048576:
        raise invalid("YAML 不能超过 1 MiB")
    yaml = YAML(typ="rt")
    yaml.allow_duplicate_keys = False
    yaml.preserve_quotes = True
    try:
        if any(
            isinstance(t, (AnchorToken, AliasToken, TagToken)) for t in yaml.scan(text)
        ):
            raise invalid()
        doc = yaml.load(text)
        if not isinstance(doc, dict):
            raise invalid("YAML 顶层必须是映射")
        inspect(doc)
        return yaml, doc
    except Problem:
        raise
    except Exception as exc:
        mark = getattr(exc, "problem_mark", None)
        details = {"line": mark.line + 1, "column": mark.column + 1} if mark else {}
        message = "YAML 语法错误" + (
            f"（第 {details['line']} 行，第 {details['column']} 列）" if details else ""
        )
        raise Problem(422, "invalid_yaml", message, details) from None


def inspect(value, depth=0):
    if depth > 50:
        raise invalid("YAML 嵌套过深")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key == "<<":
                raise invalid()
            if re.search(
                r"password|secret|token|private.?key|access.?key|(^|[._-])key$",
                key,
                re.I,
            ):
                raise invalid("不接受明文凭据，请使用 credential_ref 引用")
            inspect(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            inspect(item, depth + 1)
    elif isinstance(value, str) and re.search(
        r"PRIVATE KEY-----|[a-z]+://[^/\s:@]+:[^/\s@]+@|--(?:password|secret|token|rados[.]key)[=\s]",
        value,
        re.I,
    ):
        raise invalid("不接受明文凭据")


def merge(text, fields):
    if not fields or set(fields) - {
        "filesystem",
        "mount_root",
        "dingo_path",
        "vdbench_path",
    }:
        raise invalid("不支持的表单字段")
    yaml, doc = parse(text or "{}\n")
    for key, value in fields.items():
        if not isinstance(value, str) or not value or len(value) > 512 or "\n" in value:
            raise invalid("表单字段格式错误")
        if key != "filesystem" and not value.startswith("/"):
            raise invalid("路径必须为绝对路径")
        doc[key] = value
    output = io.StringIO()
    yaml.dump(doc, output)
    result = output.getvalue()
    parse(result)
    return result
