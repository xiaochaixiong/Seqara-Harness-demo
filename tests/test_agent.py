"""Real official Agent loop, local deterministic SSE model, packaged business worker."""
import json, os, subprocess, tempfile, threading, unittest, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
class AgentTest(unittest.TestCase):
 def test_official_agent_uses_packaged_business_tool(self):
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    p=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append(p)
    tool=any(m.get('role')=='tool' for m in p['messages'])
    delta={'role':'assistant','content':'BUSINESS_AGENT_OK'} if tool else {'role':'assistant','tool_calls':[{'index':0,'id':'nv_test','type':'function','function':{'name':'toolkit_classify_invoice_text','arguments':json.dumps({'text':'快递邮寄服务费'},ensure_ascii=False)}}]}
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
    for choice in ({'index':0,'delta':delta,'finish_reason':None},{'index':0,'delta':{},'finish_reason':'stop' if tool else 'tool_calls'}):
     self.wfile.write(('data: '+json.dumps({'id':'local-test','object':'chat.completion.chunk','model':'deepseek-v4-flash','choices':[choice]},ensure_ascii=False)+'\n\n').encode())
    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with tempfile.TemporaryDirectory() as td:
    home=Path(td);patch=home/'tools.json';patch.write_text(json.dumps([{'insert':[{'id':'nv-tools','name':(ROOT/'runtime/toolkit-plugin/index.mjs').as_uri()}]}]))
    env={**os.environ,'DSH_HOME':str(home/'harness'),'NV_TOOLKIT_DATA_DIR':str(home/'business'),'NV_TOOLKIT_COMMAND':json.dumps([sys.executable,str(ROOT/'backend/worker.py')]),'DEEPSEEK_API_KEY':'local-test-key','DEEPSEEK_BASE_URL':f'http://127.0.0.1:{server.server_port}'}
    r=subprocess.run(['node',str(ROOT/'runtime/node_modules/@deepseek-ai/dsh/lib/bin.js'),'--profile','headless','--patch',str(patch),'Call toolkit_classify_invoice_text for the supplied example.'],env=env,cwd=td,capture_output=True,encoding='utf8',timeout=90)
    self.assertEqual(r.returncode,0,r.stderr);self.assertIn('BUSINESS_AGENT_OK',r.stdout)
    self.assertTrue(any('邮寄费' in str(m.get('content')) for p in seen for m in p['messages'] if m.get('role')=='tool'))
    self.assertIn('toolkit_invoices',{t['function']['name'] for t in seen[0]['tools']})
    tools={t['function']['name']:t['function'] for t in seen[0]['tools']}
    self.assertTrue({'toolkit_dashboard','toolkit_print'}.issubset(tools))
    self.assertIn('supplementary',tools['toolkit_dashboard']['parameters']['properties'])
    self.assertIn('ticket_threshold',tools['toolkit_invoices']['parameters']['properties'])
    self.assertEqual(tools['toolkit_print']['parameters']['properties']['confirmed']['type'],'boolean')
  finally:server.shutdown();server.server_close();thread.join(2)
if __name__=='__main__':unittest.main(verbosity=2)
