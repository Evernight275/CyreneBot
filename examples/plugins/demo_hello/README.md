# Demo Hello Plugin

Minimal CyreneBot plugin project.

```text
demo_hello/
  plugin.json
  main.py
  routers/
  assets/
```

`plugin.json` declares the plugin project metadata. `main.py` declares local bot routes.

```python
from cyreneAI.api import CyreneBot
from routers.basic import router as basic_router

plugin = CyreneBot()
plugin.include_router(basic_router)
```

Routers hold commands:

```python
from cyreneAI.api import CyreneRouter, text

router = CyreneRouter()

@router.command("/hello", aliases=["hi"])
async def hello(request, ctx):
    """Say hello."""
    name = request.command.args_text or "world"
    return text(request, f"Hello, {name}!")
```

Complex plugins can split routes with prefixes:

```python
from cyreneAI.api import CyreneRouter, Depends

admin_router = CyreneRouter(prefix="/sf", admin_required=True)

@admin_router.command("/ban", aliases=["b"])
async def ban(request, store=Depends("storage")):
    ...
```

Handlers can declare host-managed dependencies when they need runtime abilities:

```python
from cyreneAI.api import CyreneBot, Depends, text

plugin = CyreneBot()

@plugin.command("/providers")
async def providers(request, list_providers=Depends("providers")):
    """List providers."""
    provider_names = ", ".join(provider.name for provider in list_providers())
    return text(request, provider_names or "No providers")
```

Dependencies are permission checked by the host. For example, `Depends("providers")`
requires the plugin manifest to declare `provider_read`.

Plugin assets are read-only files packaged with the plugin project:

```python
@plugin.command("/asset")
async def asset(request, assets=Depends("assets")):
    content = await assets.read_text("prompts/hello.txt")
    return text(request, content.strip())
```

`Depends("assets")` requires the plugin manifest to declare `assets`.
