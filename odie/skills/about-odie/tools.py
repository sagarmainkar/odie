"""The about-odie skill's tool: what Odie has right now, read live."""
from google.adk.tools import FunctionTool

from odie import about


async def odie_features() -> str:
    """Everything Odie can do right now, read live: built-in abilities, skills, connected apps, models and providers,
    voice, active trackers, what runs on its own, visual blocks, and how to add more."""
    return about.features()


TOOLS = [FunctionTool(odie_features)]
