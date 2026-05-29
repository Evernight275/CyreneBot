from cyreneAI.api import CyreneBot

from routers.basic import router as basic_router


plugin = CyreneBot()
plugin.include_router(basic_router)
