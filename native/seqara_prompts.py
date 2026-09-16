"""User-owned prompt library, independent of browser caches and workspaces."""
import json,os,uuid
from pathlib import Path

class PromptStore:
    def __init__(self,data):self.path=Path(data)/'prompt-library.json'
    def read(self):
        if not self.path.exists():return []
        value=json.loads(self.path.read_text('utf8'))
        if not isinstance(value,list):raise ValueError('提示词库格式异常，请保留文件并联系维护者。')
        return value
    def change(self,action,args):
        rows=self.read();key=args.get('id')
        if action=='upsert':
            name=str(args.get('name','')).strip();text=str(args.get('prompt','')).strip()
            if not name or not text:raise ValueError('请填写名称和提示词内容。')
            if len(name)>120 or len(text)>100000:raise ValueError('名称最多 120 字，提示词最多 100000 字。')
            item={'id':key or str(uuid.uuid4()),'name':name,'prompt':text}
            if key and not any(r['id']==key for r in rows):raise ValueError('此提示词已被删除，请重新添加。')
            rows=[item if r['id']==key else r for r in rows] if key else rows+[item]
        elif action=='delete':rows=[r for r in rows if r['id']!=key]
        else:raise ValueError('不支持的提示词操作。')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp')
        try:
            with temp.open('w',encoding='utf8') as file:
                json.dump(rows,file,ensure_ascii=False,indent=2);file.flush();os.fsync(file.fileno())
            os.replace(temp,self.path)
        finally:
            if temp.exists():temp.unlink()
        return rows
