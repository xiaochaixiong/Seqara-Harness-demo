"""Application network preference; independent of operating-system Wi-Fi."""
import json, os, threading
_lock=threading.RLock()
_active=0
from pathlib import Path

def is_offline():
    return os.environ.get('SEQARA_OFFLINE') == '1'

def load(data):
    try:return json.loads((Path(data)/'network.json').read_text('utf8')).get('offline') is True
    except (OSError,ValueError):return False

def save(data,offline):
    with _lock:
        if offline and _active:raise OSError('仍有联网请求，请等待完成后重试')
        target=Path(data)/'network.json'
        temp=target.with_suffix('.tmp');temp.write_text(json.dumps({'offline':bool(offline)}),encoding='utf8');temp.replace(target)
        os.environ['SEQARA_OFFLINE']='1' if offline else '0'

OFFLINE_MESSAGE='当前为离线模式，本地工具仍可使用。请使用窗口顶部的联网开关恢复连接后重试。'


def install_requests_guard():
    import requests
    original=requests.sessions.Session.request
    if getattr(original,'_seqara_guard',False) is True:return
    def request(self,*args,**kwargs):
        global _active
        with _lock:
            if is_offline():raise requests.exceptions.ConnectionError(OFFLINE_MESSAGE)
            _active+=1
        try:return original(self,*args,**kwargs)
        finally:
            with _lock:_active-=1
    request._seqara_guard=True
    requests.sessions.Session.request=request
