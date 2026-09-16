import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
from seqara_settings import SettingsStore,prepare_shared_config,atomic_json
class SettingsTests(unittest.TestCase):
 def test_migration_preserves_conflict_and_is_idempotent(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);atomic_json(root/'native/invoice_classify_defaults.json',{'company_name':'原生'});atomic_json(root/'business/invoice_classify_defaults.json',{'company_name':'Agent'})
   result=prepare_shared_config(root);self.assertEqual(result['preserved'],['invoice_classify_defaults.json']);self.assertEqual(json.loads((root/'native/invoice_classify_defaults.json').read_text('utf8'))['company_name'],'原生');self.assertEqual(prepare_shared_config(root),result);self.assertTrue((root/'config-backups/v037-agent-rules/invoice_classify_defaults.json').exists())
 def test_key_is_redacted_and_preserved_on_other_edits(self):
  with tempfile.TemporaryDirectory() as td:
   atomic_json(Path(td)/'api_config.json',{'deepseek_api_key':'test-only-secret','custom':'kept'})
   store=SettingsStore(td);r=store.read('connection');self.assertNotIn('test-only-secret',json.dumps(r));store.save('connection',{'deepseek_model':'deepseek-v4-flash'},r['revision']);v=json.loads((Path(td)/'api_config.json').read_text('utf8'));self.assertEqual(v['deepseek_api_key'],'test-only-secret');self.assertEqual(v['custom'],'kept')
 def test_conflicting_revision_and_invalid_data_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   store=SettingsStore(td);r=store.read('defaults');store.save('defaults',{'company_name':'甲','group_prefix':'乙'},r['revision'])
   with self.assertRaises(ValueError):store.save('defaults',{'company_name':'丙','group_prefix':'丁'},r['revision'])
   r=store.read('tickets')
   with self.assertRaises(ValueError):store.save('tickets',{'公司':[]},r['revision'])
   self.assertFalse((Path(td)/'ticket_company_schools.json').exists())
if __name__=='__main__':unittest.main()
