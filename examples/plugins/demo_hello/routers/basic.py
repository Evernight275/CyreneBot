from cyreneAI.api import CyreneRouter, Depends, text

router = CyreneRouter()


@router.command("/hello", aliases=["hi"])
async def hello(request, ctx):
    """Say hello."""
    name = request.command.args_text or "world"
    return f"Hello, {name}!"


@router.command("/providers")
async def providers(request, list_providers=Depends("providers")):
    provider_names = ", ".join(provider.name for provider in list_providers())
    return provider_names or "No providers"


@router.command("/asset")
async def asset(request, assets=Depends("assets")):
    content = await assets.read_text("prompts/hello.txt")
    return content.strip()
