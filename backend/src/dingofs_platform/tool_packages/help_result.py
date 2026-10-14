def help_succeeded(tool, returncode, output):
    if returncode == 0:
        return True
    # These releases intentionally return a nonzero code after normal help.
    if 'Usage:' not in output or 'error while loading' in output:
        return False
    if tool == 'dingo-client' and returncode == 1:
        return 'dingo-client [OPTIONS]' in output and '<mountpoint>' in output
    if tool == 'dingo-cache' and returncode == 255:
        return 'dingo-cache [OPTIONS]' in output and '--id <cache_node_uuid>' in output
    return False
