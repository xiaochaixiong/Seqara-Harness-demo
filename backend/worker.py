"""Versioned JSON-lines business boundary shared by Desktop and DSH tools."""
from __future__ import annotations
import contextlib
import dataclasses
from datetime import date
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')
OUTPUT = sys.stdout
def emit(kind, **value):
    OUTPUT.write(json.dumps({'type': kind, **value}, ensure_ascii=False, default=str, allow_nan=False) + '\n')
    OUTPUT.flush()

def log(message):
    emit('progress', message=str(message))

def source(args, key='source', extensions=('.xlsx', '.xls')):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请先选择输入文件。')
    p = Path(value).expanduser().resolve(strict=True)
    if not p.is_file() or p.suffix.lower() not in extensions:
        raise ValueError('文件类型不支持：' + p.name)
    return p

def required(args, key, label):
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请填写' + label)
    if len(value) > 500_000:
        raise ValueError(label + '内容过长')
    return value.strip()

def number(args, key, default, low, high):
    value = float(args.get(key, default))
    if not low <= value <= high:
        raise ValueError('参数超出范围：' + key)
    return value

def run(name, args, home: Path):
    if name == 'presentation-reference':
        from presentation_reference import inspect_reference
        return inspect_reference(args)
    if name == 'presentation-source':
        from presentation_io import read_source
        return read_source(args)
    if name == 'presentation-verify':
        from presentation_io import verify_presentation
        return verify_presentation(args)
    config = Path(os.environ.get('NV_TOOLKIT_CONFIG_DIR', str(home)))
    config.mkdir(parents=True, exist_ok=True)
    import nv_cover_fill_core as covers
    covers.set_cover_fill_config_dir(str(config))
    home.mkdir(parents=True, exist_ok=True)
    out = home / 'outputs' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    # Legacy modules may use relative log paths; isolate them from the source tree.
    os.chdir(out)
    extra = {}
    if name == 'invoices':
        import nv_classify_core as core
        core.set_classify_config_dir(str(config))
        p = source(args)
        # .xls conversion in the original core writes beside its input; stage only that input.
        if p.suffix.lower() == '.xls':
            staged = out / 'input' / p.name
            staged.parent.mkdir(); shutil.copy2(p, staged); p = staged
        core.process(p, output_dir=out,
            base=number(args,'base',130000,1,1e10), jitter=number(args,'jitter',20000,0,1e10),
            seed=int(number(args,'seed',42,0,2**31-1)),
            company_name=required(args,'company','公司名称'),
            group_cover_prefix=required(args,'project','项目名称'),
            ticket_split_threshold=number(args,'ticket_threshold',700000,0,1e10),
            ticket_group_size=int(number(args,'ticket_group_size',240,1,100000)),
            cover_series=int(number(args,'cover_series',1,1,9999)),
            start_index_for_group=int(number(args,'start_index',2,1,99999)),
            enable_amount_fallback=bool(args.get('amount_fallback',True)),
            progress_cb=lambda done,total,msg: emit('progress',message=msg,percent=round(done/max(total,1)*100)))
    elif name in ('clean','statistics'):
        import nv_business_core as core
        errors=[]
        core.show_error=lambda title,msg: errors.append(msg)
        core.show_info=lambda title,msg: log(msg)
        core.LOG_DATA=str(out/'process.log'); core.INFO_LOG=str(out/'info.log')
        if name=='clean':
            core.match_and_clean(str(source(args)),str(source(args,'reimbursement')),str(out),None,
                fuzzy_threshold=int(number(args,'threshold',90,50,100)),
                output_basename='活动整理')
        else:
            core.generate_project_stat_tables(str(source(args)),str(out),None,
                output_filename='项目数据统计表.xlsx')
        if errors: raise ValueError('；'.join(errors))
    elif name in ('split','briefing'):
        from nv_briefing_core import ExcelSplitter, ReportGenerator
        p=source(args,extensions=('.xlsx',))
        if name=='split':
            result=ExcelSplitter(log).split(p,out)
            if not result['success']: raise ValueError('没有成功拆分的院校，请检查学校名称和表格内容。')
            extra={'count':result['success'],'failed':result['failed']}
        else:
            generator=ReportGenerator(log,split_by_activity=bool(args.get('split_by_activity',False)),
                full_content_mode=bool(args.get('full_content',False)))
            report = generator.generate(str(p),str(out))
            if not report['success']:
                raise ValueError('简报生成失败：' + '；'.join(report['failed'] or ['没有可用正文']))
            extra = {'briefing': report}
    elif name=='dashboard':
        import nv_dashboard_core as core
        p=source(args)
        reim=str(source(args,'reimbursement')) if args.get('reimbursement') else None
        supplementary=str(source(args,'supplementary')) if args.get('supplementary') else None
        snapshot=core.build_dashboard_snapshot(p,reim,home/'dashboard.sqlite3',supplementary)
        start=date.fromisoformat(args['start']+'-01') if args.get('start') else None
        end=None
        if args.get('end'):
            import calendar
            y,m=map(int,args['end'].split('-')); end=date(y,m,calendar.monthrange(y,m)[1])
        if start and end and start>end: raise ValueError('开始月份不能晚于结束月份。')
        view=core.filter_dashboard_snapshot(snapshot,core.DashboardFilter(start_date=start,end_date=end))
        extra={'dashboard':{'activities':view.activity_count,'schools':view.school_count,
            'teachers':view.teacher_total,'students':view.student_total,
            'months':view.months,'school_counts':view.school_counts,
            'school_month_counts':view.school_month_counts,'school_type_counts':view.school_type_counts,
            'records':[dataclasses.asdict(r) for r in view.activities],
            'unreimbursed':[dataclasses.asdict(r) for r in view.unreimbursed],
            'supports_reimbursement':snapshot.supports_reimbursement,
            'quality':[dataclasses.asdict(q) for q in snapshot.quality_issues],
            'experts':[{'name':e.expert_name,'invitation_count':e.invitation_count} for e in view.experts]}}
    elif name=='activity-plan':
        from nv_activity_plan_docx import save_activity_plan_to_docx
        save_activity_plan_to_docx(str(out/'活动方案.docx'),required(args,'project','项目名称'),
            required(args,'school','服务院校'),required(args,'activity_type','活动类型'),
            required(args,'period','活动周期'),'',required(args,'body','方案正文'))
    elif name=='delivery':
        import pandas as pd
        import nv_deepseek_core as ds
        ds.config_base_path=str(config)
        from nv_industry_delivery_core import save_delivery_report_docx
        df=pd.read_excel(source(args)) if args.get('source') else pd.DataFrame()
        ok=save_delivery_report_docx(str(out/'交付报告.docx'),required(args,'school','服务院校'),
            required(args,'year','年份'),required(args,'period','报告周期'),required(args,'body','报告正文'),
            df,[],True,bool(args.get('source')),log,lambda kind,title,msg: log(msg),
            str(Path(__file__).parent/'industry_delivery_cover_template.docx'))
        if not ok: raise ValueError('交付报告保存失败，请查看处理日志。')
    elif name=='print':
        import nv_auto_print_core as core
        p=source(args,extensions=('.docx','.doc','.pdf','.png','.jpg','.jpeg'))
        mode=args.get('mode','convert')
        if mode=='convert':
            if p.suffix.lower() not in ('.doc','.docx'): raise ValueError('转 PDF 请选择 Word 文档。')
            ok,message=core.docx_convert_to_pdf(p,out/(p.stem+'.pdf'),args.get('engine','word'),
                compact_one_page=False,flatten_float_pics=True)
            if not ok: raise ValueError(message)
        elif mode=='print':
            if args.get('confirmed') is not True: raise ValueError('请先确认打印文件与默认打印机。')
            ok=core.dispatch_print(p,core.find_sumatra_pdf(),None,log,True,'fit',False,
                args.get('engine','word'),True,'',True)
            if not ok: raise ValueError('未能提交打印任务，请检查 Word/WPS、SumatraPDF 和默认打印机。')
            extra={'message':'已提交至系统打印队列，请在打印机处核对。'}
        else: raise ValueError('未知打印操作')
    elif name=='classify_invoice_text':
        import nv_classify_core as core
        core.set_classify_config_dir(str(config)); core.load_keyword_learning_state()
        category,evidence=core.classify_keywords_first(required(args,'text','发票描述'))
        extra={'category':category or '未分类','evidence':evidence}
    else:
        raise ValueError('未知业务工具：'+name)
    artifacts=[str(p.resolve()) for p in out.iterdir() if p.suffix.lower() in ('.xlsx','.csv','.docx','.pdf')]
    if name not in ('dashboard','classify_invoice_text','print') and not artifacts:
        raise ValueError('任务没有生成文件，请查看日志并检查输入。')
    return {'artifacts':artifacts,'output_dir':str(out),**extra}

def main():
    request=json.loads(sys.stdin.readline(2_000_001))
    if not isinstance(request.get('args'),dict): raise ValueError('任务参数格式不正确')
    home=Path(os.environ['NV_TOOLKIT_DATA_DIR']).resolve()
    home.mkdir(parents=True,exist_ok=True)
    # The same lock covers UI jobs and Agent jobs, including keyword learning state.
    with open(home/'business.lock','a+b') as lock:
        if os.name=='nt':
            import msvcrt
            if lock.seek(0,2)==0: lock.write(b'0'); lock.flush()
            lock.seek(0)
            while True:
                try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1); break
                except OSError: time.sleep(.2)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX)
        with contextlib.redirect_stdout(sys.stderr):
            value=run(request['name'],request['args'],home)
        emit('result',value=value)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        emit('error',message=str(exc)); sys.exit(1)
