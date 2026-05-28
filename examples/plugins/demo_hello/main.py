from cyreneAI.plugin_api import CyreneBot, text


plugin = CyreneBot()


@plugin.command("/hello", aliases=["hi"])
async def hello(request, ctx):
    """Say hello."""
    name = request.command.args_text or "world"
    return text(request, f"Hello, {name}!")
