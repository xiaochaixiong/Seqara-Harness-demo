"""Compatibility aliases for external callers; requests now use DeepSeek credentials only."""
from nv_deepseek_core import *
from nv_deepseek_core import (
    set_deepseek_config_dir as set_tongyi_config_dir,
    get_deepseek_api_settings_for_dialog as get_tongyi_api_settings_for_dialog,
    get_default_deepseek_model as get_default_tongyi_model,
    call_deepseek_api as call_tongyi_api,
)
