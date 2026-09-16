"""Native button and offline download boundaries, without touching user files."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['NV_NATIVE_DATA']=tempfile.mkdtemp(prefix='seqara-io-native-')
sys.path[:0]=[str(ROOT/'native'),str(ROOT/'build-python')]
from seqara_navigation import download_allowed
import toolkit

class DesktopIOTests(unittest.TestCase):
 def test_local_downloads_work_offline_without_allowing_remote_downloads(self):
  origin='http://127.0.0.1:4321/'
  for url in (origin+'api/export','blob:'+origin+'uuid','data:text/plain;base64,YQ=='):
   self.assertTrue(download_allowed(url,origin,True),url)
  for url in ('https://example.com/file.pdf','blob:https://example.com/id','http://127.0.0.1:4322/file','file:///C:/file.pdf','blob:null/id',''):
   self.assertFalse(download_allowed(url,origin,True),url)
 def test_folder_failure_is_visible_and_existing_folder_launches(self):
  folder=Path(tempfile.mkdtemp(prefix='seqara-folder-'))
  with patch.object(toolkit,'stitch_msg_warning') as warning,patch.object(toolkit.os,'startfile',create=True) as launch:
   self.assertTrue(toolkit.open_local_folder(None,folder));launch.assert_called_once_with(str(folder.resolve()))
   launch.side_effect=OSError('fixture-shell-unavailable')
   self.assertFalse(toolkit.open_local_folder(None,folder));self.assertIn('fixture-shell-unavailable',warning.call_args.args[2])
   self.assertFalse(toolkit.open_local_folder(None,''))
   self.assertFalse(toolkit.open_local_folder(None,folder/'missing'))
 def test_invoice_open_without_file_has_feedback(self):
  # Drive the actual page handler with an empty file field, no Qt window needed.
  class Field:
   def text(self):return ''
  import types
  owner=types.SimpleNamespace(e_file=Field())
  page=next(v for v in vars(toolkit).values() if isinstance(v,type) and '_open_output' in v.__dict__ and 'e_file' in v._open_output.__code__.co_names)
  with patch.object(toolkit,'stitch_msg_warning') as warning:
   page._open_output(owner);warning.assert_called_once()

if __name__=='__main__':unittest.main()
