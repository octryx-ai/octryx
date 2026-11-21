"""Built-in connector preset definitions."""

from app.services.tool_config.presets_cloud import TOOL_CONFIG_PRESETS_CLOUD
from app.services.tool_config.presets_ops import TOOL_CONFIG_PRESETS_OPS
from app.services.tool_config.presets_scm import TOOL_CONFIG_PRESETS_SCM
from app.services.tool_config.presets_work import TOOL_CONFIG_PRESETS_WORK

TOOL_CONFIG_PRESETS = {
    **TOOL_CONFIG_PRESETS_WORK,
    **TOOL_CONFIG_PRESETS_SCM,
    **TOOL_CONFIG_PRESETS_CLOUD,
    **TOOL_CONFIG_PRESETS_OPS,
}
