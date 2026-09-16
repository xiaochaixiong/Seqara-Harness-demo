"""Keep the DSH origin in its trusted view; dispatch local previews externally."""
from urllib.parse import urlsplit

def navigation_target(url, trusted, offline=False):
    parsed, host = urlsplit(url), urlsplit(trusted or '')
    if parsed.scheme not in ('http', 'https'):
        return 'embedded' if parsed.scheme in ('about', 'data', 'qrc', '') else 'blocked'
    local = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if offline and not local:
        return 'blocked'
    if (parsed.scheme, parsed.hostname, parsed.port) == (host.scheme, host.hostname, host.port):
        return 'embedded'
    return 'external'


def download_allowed(url, trusted, offline=False):
    """Offline still permits exporting bytes from the trusted local UI."""
    if not offline:
        return True
    if url.startswith('data:'):
        return True
    if url.startswith('blob:'):
        url = url[5:]
    try:
        parsed, host = urlsplit(url), urlsplit(trusted or '')
        return (parsed.scheme in ('http', 'https')
                and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
                and (parsed.scheme, parsed.hostname, parsed.port)
                == (host.scheme, host.hostname, host.port))
    except ValueError:
        return False
