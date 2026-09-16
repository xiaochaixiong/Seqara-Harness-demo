import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
import seqara_network as network
import requests
class NetworkTests(unittest.TestCase):
 def test_offline_blocks_requests_before_transport_and_persists(self):
  with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=False):
   network.save(folder,True);self.assertTrue(network.load(folder))
   with patch.object(requests.sessions.Session,'request',side_effect=AssertionError('transport reached')):
    network.install_requests_guard()
    with self.assertRaises(requests.ConnectionError):requests.get('https://example.invalid')
   network.save(folder,False);self.assertFalse(network.load(folder))
 def test_switch_refuses_inflight_request_and_online_is_restored(self):
  with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'SEQARA_OFFLINE':'0'}):
   def transport(*a,**k):
    with self.assertRaises(OSError):network.save(folder,True)
    return 'allowed'
   with patch.object(requests.sessions.Session,'request',side_effect=transport):
    network.install_requests_guard();self.assertEqual(requests.get('https://example.invalid'),'allowed')
   network.save(folder,True);self.assertTrue(network.load(folder))
 def test_ai_calls_return_offline_reason(self):
  import nv_deepseek_core as api
  with patch.dict(os.environ,{'SEQARA_OFFLINE':'1'}),patch.object(requests,'get',side_effect=AssertionError('network')),patch.object(requests,'post',side_effect=AssertionError('network')):
   self.assertIn('离线模式',api.test_api_connection('test','deepseek-v4-flash')[1])
   self.assertIn('离线模式',api.call_deepseek_api('test')[1])
if __name__=='__main__':unittest.main()
