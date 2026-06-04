from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from contextlib import suppress
from pathlib import Path
from textwrap import dedent
from types import ModuleType
from typing import Any, Sequence

from cyreneAI.api.testing import PluginTestClient
from cyreneAI.core.errors.plugin import PluginError, PluginInputError
from cyreneAI.core.plugin.project import (
    PLUGIN_SIGNATURE_FILENAME,
    load_plugin_manifest,
    plugin_manifest_isolation_mode,
    plugin_project_content_hash,
    resolve_plugin_entrypoint,
    resolve_plugin_project_path,
    validate_plugin_project_signature,
)
from cyreneAI.core.schema.plugin import (
    PluginCapability,
    PluginCommandArgumentDefinition,
    PluginIsolationMode,
    PluginManifest,
    PluginSignatureStatus,
)

PLUGIN_TEMPLATE_NAMES = ("basic", "storage", "task", "event", "proactive", "llm")


class PluginInitError(ValueError):
    """Raised when a plugin project cannot be initialized safely."""


class PluginCheckError(ValueError):
    """Raised when a plugin project does not pass local checks."""


class PluginCheckReport:
    """Result returned by check_plugin_project."""

    def __init__(
        self,
        *,
        project_path: Path,
        manifest: PluginManifest,
        warnings: Sequence[str] = (),
    ) -> None:
        self.project_path = project_path
        self.manifest = manifest
        self.warnings = tuple(warnings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        try:
            project_path = init_plugin_project(
                args.path,
                plugin_id=args.plugin_id,
                name=args.name,
                description=args.description,
                author=args.author,
                template=args.template,
                force=args.force,
            )
        except PluginInitError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(f"Initialized CyreneAI plugin at {project_path}")
        return 0

    if args.command == "check":
        try:
            report = check_plugin_project(args.path)
        except PluginCheckError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        for warning in report.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        print(
            "Checked CyreneAI plugin "
            f"{report.manifest.plugin_id} at {report.project_path}"
        )
        return 0

    if args.command == "docs":
        try:
            content = generate_plugin_documentation(
                args.path,
                output_format=args.format,
            )
        except PluginCheckError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        if args.output is not None:
            Path(args.output).write_text(content, encoding="utf-8", newline="\n")
        else:
            print(content, end="")
        return 0

    if args.command == "sign":
        try:
            signature_path = sign_plugin_project(
                args.path,
                signed_by=args.signed_by,
            )
        except PluginCheckError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(f"Signed CyreneAI plugin at {signature_path}")
        return 0

    parser.print_help()
    return 2


def init_plugin_project(
    path: str | Path,
    *,
    plugin_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    author: str | None = None,
    template: str = "basic",
    force: bool = False,
) -> Path:
    project_path = Path(path)
    project_name = project_path.resolve().name
    if not project_name:
        raise PluginInitError("plugin path must include a directory name")

    resolved_plugin_id = plugin_id or _normalize_plugin_id(project_name)
    resolved_name = name or _humanize_name(project_name)
    resolved_description = description or "A CyreneAI plugin."
    resolved_template = _normalize_template(template)

    files = {
        "pyproject.toml": _pyproject_text(resolved_plugin_id),
        "plugin.json": _manifest_text(
            plugin_id=resolved_plugin_id,
            name=resolved_name,
            description=resolved_description,
            author=author,
            template=resolved_template,
        ),
        "main.py": _main_text(resolved_template),
        "tests/test_plugin.py": _test_text(resolved_template),
        "README.md": _readme_text(resolved_name, resolved_template),
    }

    _ensure_writable(project_path, files, force=force)
    project_path.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        target = project_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    return project_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cyrene-plugin",
        description="CyreneAI plugin SDK helper commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="create a minimal CyreneAI plugin project",
    )
    init_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="target plugin directory; defaults to the current directory",
    )
    init_parser.add_argument(
        "--plugin-id",
        help="plugin id for plugin.json; defaults to a normalized directory name",
    )
    init_parser.add_argument(
        "--name",
        help="display name for plugin.json; defaults to a humanized directory name",
    )
    init_parser.add_argument(
        "--description",
        help="description for plugin.json",
    )
    init_parser.add_argument(
        "--author",
        help="author field for plugin.json",
    )
    init_parser.add_argument(
        "--template",
        choices=PLUGIN_TEMPLATE_NAMES,
        default="basic",
        help="plugin template to generate",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite generated files if they already exist",
    )

    check_parser = subparsers.add_parser(
        "check",
        help="validate a CyreneAI plugin project",
    )
    check_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="plugin project directory or plugin.json; defaults to current directory",
    )

    docs_parser = subparsers.add_parser(
        "docs",
        help="generate plugin documentation from plugin metadata",
    )
    docs_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="plugin project directory or plugin.json; defaults to current directory",
    )
    docs_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="documentation output format",
    )
    docs_parser.add_argument(
        "--output",
        help="write documentation to a file instead of stdout",
    )

    sign_parser = subparsers.add_parser(
        "sign",
        help="write a local sha256 plugin signature metadata file",
    )
    sign_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="plugin project directory or plugin.json; defaults to current directory",
    )
    sign_parser.add_argument(
        "--signed-by",
        help="optional signer identity stored in signature metadata",
    )
    return parser


def check_plugin_project(path: str | Path) -> PluginCheckReport:
    project_path, manifest, plugin = _load_plugin_project(path)
    _check_manifest_capabilities(manifest, plugin)
    _check_plugin_setup(plugin, manifest)
    signature = _check_plugin_signature(project_path)
    return PluginCheckReport(
        project_path=project_path,
        manifest=manifest,
        warnings=[
            *_check_manifest_warnings(manifest, plugin),
            *_check_deployment_warnings(manifest, signature["status"]),
        ],
    )


def generate_plugin_documentation(
    path: str | Path,
    *,
    output_format: str = "markdown",
) -> str:
    project_path, manifest, plugin = _load_plugin_project(path)
    _check_manifest_capabilities(manifest, plugin)
    client = _build_test_client(plugin, manifest)
    if output_format == "json":
        return (
            json.dumps(
                _documentation_payload(project_path, manifest, client),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    if output_format != "markdown":
        raise PluginCheckError(f"unsupported docs format: {output_format}")
    return _documentation_markdown(manifest, client)


def sign_plugin_project(
    path: str | Path,
    *,
    signed_by: str | None = None,
) -> Path:
    project_path = _resolve_plugin_project_path(path)
    _load_manifest(project_path / "plugin.json")
    content_hash = plugin_project_content_hash(project_path)
    payload: dict[str, object] = {
        "algorithm": "sha256",
        "content_hash": content_hash,
    }
    if signed_by:
        payload["signed_by"] = signed_by
    signature_path = project_path / ".cyreneai-plugin-signature.json"
    signature_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return signature_path


def _load_plugin_project(path: str | Path) -> tuple[Path, PluginManifest, object]:
    project_path = _resolve_plugin_project_path(path)
    manifest = _load_manifest(project_path / "plugin.json")
    entrypoint = _resolve_entrypoint(project_path, manifest)
    module = _load_entrypoint_module(
        entrypoint=entrypoint,
        plugin_id=manifest.plugin_id,
        project_path=project_path,
    )
    plugin = _load_plugin_object(module, manifest)
    return project_path, manifest, plugin


def _ensure_writable(
    project_path: Path,
    files: dict[str, str],
    *,
    force: bool,
) -> None:
    existing = [
        str(project_path / relative_path)
        for relative_path in files
        if (project_path / relative_path).exists()
    ]
    if existing and not force:
        joined = ", ".join(existing)
        raise PluginInitError(f"target files already exist: {joined}")


def _resolve_plugin_project_path(path: str | Path) -> Path:
    try:
        return resolve_plugin_project_path(path)
    except PluginInputError as exc:
        raise PluginCheckError(str(exc)) from exc


def _load_manifest(path: Path) -> PluginManifest:
    try:
        return load_plugin_manifest(path)
    except PluginInputError as exc:
        raise PluginCheckError(str(exc)) from exc


def _resolve_entrypoint(project_path: Path, manifest: PluginManifest) -> Path:
    try:
        return resolve_plugin_entrypoint(project_path, manifest)
    except PluginInputError as exc:
        raise PluginCheckError(str(exc)) from exc


def _load_entrypoint_module(
    *,
    entrypoint: Path,
    plugin_id: str,
    project_path: Path,
) -> ModuleType:
    module_name = _module_name(plugin_id, entrypoint)
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise PluginCheckError(
            f"plugin {plugin_id} entrypoint {entrypoint} cannot be loaded"
        )

    module = importlib.util.module_from_spec(spec)
    project_path_text = str(project_path.resolve())
    sys.path.insert(0, project_path_text)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginCheckError(
            f"plugin {plugin_id} entrypoint {entrypoint} import failed: {exc}"
        ) from exc
    finally:
        sys.modules.pop(module_name, None)
        with suppress(ValueError):
            sys.path.remove(project_path_text)
    return module


def _load_plugin_object(module: ModuleType, manifest: PluginManifest) -> object:
    plugin = getattr(module, "plugin", None)
    if plugin is None:
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} entrypoint must define plugin"
        )
    configure = getattr(plugin, "configure", None)
    if not callable(configure):
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} object must support configure(manifest)"
        )
    setup = getattr(plugin, "setup", None)
    if not callable(setup):
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} object must support setup(context)"
        )
    try:
        configure(manifest)
    except Exception as exc:
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} configure(manifest) failed: {exc}"
        ) from exc
    return plugin


def _check_manifest_capabilities(
    manifest: PluginManifest,
    plugin: object,
) -> None:
    required: set[PluginCapability] = set()
    if manifest.commands or _route_count(plugin, "routes") > 0:
        required.add(PluginCapability.BOT_COMMAND)
    if manifest.tasks or _route_count(plugin, "tasks") > 0:
        required.add(PluginCapability.TASK)
    if manifest.events or _route_count(plugin, "events") > 0:
        required.add(PluginCapability.EVENT)
    if manifest.middlewares or _route_count(plugin, "middlewares") > 0:
        required.add(PluginCapability.MIDDLEWARE)

    declared = set(manifest.capabilities)
    missing = sorted(capability.value for capability in required - declared)
    if missing:
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} missing capabilities: {', '.join(missing)}"
        )


def _check_plugin_setup(plugin: object, manifest: PluginManifest) -> None:
    try:
        _build_test_client(plugin, manifest)
    except PluginError as exc:
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} setup failed: {exc}"
        ) from exc
    except Exception as exc:
        raise PluginCheckError(
            f"plugin {manifest.plugin_id} setup failed: {exc}"
        ) from exc


def _build_test_client(plugin: object, manifest: PluginManifest) -> PluginTestClient:
    return PluginTestClient(
        plugin,  # type: ignore[arg-type]
        manifest=manifest,
        dependencies={
            "llm": _FakeLLM(),
            "generate_image": _fake_generate_image,
            "providers": [],
            "provider_models": lambda provider_id: [],
        },
        enforce_permissions=True,
    )


class _FakeLLM:
    async def chat(self, prompt: str) -> str:
        return prompt


async def _fake_generate_image(request: object) -> None:
    return None


def _check_manifest_warnings(
    manifest: PluginManifest,
    plugin: object,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not manifest.enabled:
        warnings.append("plugin is disabled by manifest")
    if manifest.builtin:
        warnings.append("third-party plugin manifest marks builtin=true")
    if not manifest.capabilities:
        warnings.append("manifest declares no capabilities")
    return tuple(warnings)


def _check_deployment_warnings(
    manifest: PluginManifest,
    signature_status: PluginSignatureStatus,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if signature_status == PluginSignatureStatus.UNSIGNED:
        warnings.append(f"plugin has no {PLUGIN_SIGNATURE_FILENAME} signature file")

    isolation_mode = plugin_manifest_isolation_mode(manifest)
    if isolation_mode != PluginIsolationMode.IN_PROCESS:
        warnings.append(
            f"plugin requests isolation mode {isolation_mode.value}, "
            "but the current runtime only supports in_process"
        )
    return tuple(warnings)


def _check_plugin_signature(project_path: Path) -> dict[str, Any]:
    try:
        signature = validate_plugin_project_signature(project_path)
    except PluginInputError as exc:
        raise PluginCheckError(str(exc)) from exc

    if signature["status"] == PluginSignatureStatus.UNSUPPORTED:
        reason = str(signature.get("error", "unsupported signature algorithm"))
        algorithm = reason.removeprefix("unsupported signature algorithm: ")
        raise PluginCheckError(
            f"plugin signature uses unsupported algorithm: {algorithm}"
        )
    if signature["status"] == PluginSignatureStatus.INVALID:
        raise PluginCheckError(
            "plugin signature content_hash does not match plugin content"
        )
    return signature


def _route_count(plugin: object, attribute: str) -> int:
    value = getattr(plugin, attribute, ())
    try:
        return len(value)
    except TypeError:
        return 0


def _module_name(plugin_id: str, entrypoint: Path) -> str:
    safe_plugin_id = re.sub(r"[^a-zA-Z0-9_]", "_", plugin_id)
    return f"_cyreneai_plugin_check_{safe_plugin_id}_{abs(hash(str(entrypoint)))}"


def _normalize_template(value: str) -> str:
    template = value.strip().lower().replace("_", "-")
    if template not in PLUGIN_TEMPLATE_NAMES:
        joined = ", ".join(PLUGIN_TEMPLATE_NAMES)
        raise PluginInitError(f"unknown plugin template {value!r}; expected {joined}")
    return template


def _normalize_plugin_id(value: str) -> str:
    plugin_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()).strip("._-")
    plugin_id = plugin_id.replace("-", "_").lower()
    if not plugin_id:
        raise PluginInitError("plugin id cannot be empty")
    return plugin_id


def _humanize_name(value: str) -> str:
    words = re.split(r"[\s_.-]+", value.strip())
    return " ".join(word.capitalize() for word in words if word) or "CyreneAI Plugin"


def _manifest_text(
    *,
    plugin_id: str,
    name: str,
    description: str,
    author: str | None,
    template: str,
) -> str:
    capabilities, permissions = _template_capabilities_permissions(template)
    manifest: dict[str, object] = {
        "plugin_id": plugin_id,
        "name": name,
        "version": "0.1.0",
        "description": description,
        "entrypoint": "main.py",
        "author": author,
        "license": "MIT",
        "keywords": [],
        "capabilities": capabilities,
        "permissions": permissions,
        "metadata": {
            "isolation": {
                "mode": "in_process",
            },
        },
    }
    if author is None:
        manifest.pop("author")
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _template_capabilities_permissions(template: str) -> tuple[list[str], list[str]]:
    if template == "storage":
        return ["bot_command"], ["storage"]
    if template == "task":
        return ["bot_command", "task"], ["task"]
    if template == "event":
        return ["event"], []
    if template == "proactive":
        return ["bot_command", "event", "task"], [
            "storage",
            "task",
            "message_send",
        ]
    if template == "llm":
        return ["bot_command"], ["llm"]
    return ["bot_command"], []


def _main_text(template: str) -> str:
    if template == "storage":
        return dedent("""\
            from cyreneAI.api import CyreneBot, Depends


            plugin = CyreneBot()


            @plugin.command
            async def remember(name: str = "Cyrene", storage=Depends("storage")) -> str:
                await storage.set("name", name)
                return f"Remembered {name}."


            @plugin.command
            async def recall(storage=Depends("storage")) -> str:
                return await storage.get("name", "Nobody yet.")
            """)
    if template == "task":
        return dedent("""\
            from cyreneAI.api import CyreneBot, Depends
            from cyreneAI.core.schema.plugin import PluginTaskResult


            plugin = CyreneBot()


            @plugin.command
            async def schedule(tasks=Depends("tasks")) -> str:
                return await tasks.schedule_once(
                    "cleanup",
                    delay_seconds=1,
                    payload={"source": "command"},
                    key="cleanup",
                )


            @plugin.task("cleanup")
            async def cleanup(request) -> PluginTaskResult:
                return PluginTaskResult(metadata={"payload": request.payload})
            """)
    if template == "event":
        return dedent("""\
            from cyreneAI.api import CyreneBot
            from cyreneAI.core.schema.plugin import PluginEventResult


            plugin = CyreneBot()


            @plugin.event("message")
            async def on_message(event) -> PluginEventResult:
                return PluginEventResult(metadata={"text": event.text})
            """)
    if template == "proactive":
        return dedent("""\
            from cyreneAI.api import CyreneBot, Depends


            plugin = CyreneBot()


            @plugin.command
            async def status(storage=Depends("storage")) -> str:
                last_text = await storage.get("last_text", "none")
                return f"Last message: {last_text}"


            @plugin.event("message")
            async def on_message(event, storage=Depends("storage"), tasks=Depends("tasks")):
                if not event.text or event.text.startswith("/"):
                    return None
                await storage.set("last_text", event.text)
                await tasks.schedule_once(
                    "follow_up",
                    delay_seconds=30,
                    payload={"session_id": event.session_id},
                    key=f"follow_up:{event.session_id}",
                )


            @plugin.task("follow_up")
            async def follow_up(request, storage=Depends("storage"), outbox=Depends("outbox")):
                session_id = request.payload["session_id"]
                last_text = await storage.get("last_text", "")
                await outbox.send(session_id, text=f"Following up on: {last_text}")
            """)
    if template == "llm":
        return dedent("""\
            from cyreneAI.api import CyreneBot, Depends, Rest


            plugin = CyreneBot()


            @plugin.command
            async def ask(prompt: Rest[str], llm=Depends("llm")) -> str:
                return await llm.chat(prompt)
            """)
    return dedent("""\
        from cyreneAI.api import CyreneBot


        plugin = CyreneBot()


        @plugin.command
        async def hello(name: str = "world") -> str:
            return f"Hello, {name}!"
        """)


def _test_text(template: str) -> str:
    if template == "storage":
        return dedent("""\
            import asyncio

            from main import plugin
            from cyreneAI.api import PluginTestClient


            def test_storage_commands() -> None:
                async def run() -> None:
                    client = PluginTestClient(plugin, permissions=["storage"])

                    remember = await client.command("/remember Cyrene")
                    recall = await client.command("/recall")

                    assert remember.has_text("Remembered Cyrene.")
                    assert recall.has_text("Cyrene")

                asyncio.run(run())
            """)
    if template == "task":
        return dedent("""\
            import asyncio

            from main import plugin
            from cyreneAI.api import PluginTestClient


            def test_task_template() -> None:
                async def run() -> None:
                    client = PluginTestClient(plugin, permissions=["task"])

                    result = await client.command("/schedule")

                    assert result.has_text("test-task-1")
                    assert client.scheduled_tasks[0]["task_name"] == "cleanup"

                asyncio.run(run())
            """)
    if template == "event":
        return dedent("""\
            import asyncio

            from main import plugin
            from cyreneAI.api import PluginTestClient


            def test_event_template() -> None:
                async def run() -> None:
                    client = PluginTestClient(plugin)

                    result = await client.event("message", text="hello")

                    assert result.metadata == [{"text": "hello"}]

                asyncio.run(run())
            """)
    if template == "proactive":
        return dedent("""\
            import asyncio

            from main import plugin
            from cyreneAI.api import PluginTestClient


            def test_proactive_template() -> None:
                async def run() -> None:
                    client = PluginTestClient(
                        plugin,
                        permissions=["storage", "task", "message_send"],
                    )

                    await client.event("message", text="hello", session_id="s1")
                    await client.task("follow_up", payload={"session_id": "s1"})

                    assert client.scheduled_tasks[0]["task_name"] == "follow_up"
                    assert client.sent_messages[0]["text"] == "Following up on: hello"

                asyncio.run(run())
            """)
    if template == "llm":
        return dedent("""\
            import asyncio

            from main import plugin
            from cyreneAI.api import PluginTestClient


            class FakeLLM:
                async def chat(self, prompt: str) -> str:
                    return f"fake: {prompt}"


            def test_llm_template() -> None:
                async def run() -> None:
                    client = PluginTestClient(
                        plugin,
                        dependencies={"llm": FakeLLM()},
                        permissions=["llm"],
                    )
                    result = await client.command("/ask hello")

                    assert result.has_text("fake: hello")

                asyncio.run(run())
            """)
    return dedent("""\
        import asyncio

        from main import plugin
        from cyreneAI.api import PluginTestClient


        def test_hello_command() -> None:
            async def run() -> None:
                client = PluginTestClient(plugin)
                result = await client.command("/hello Cyrene")

                assert result.has_text("Hello, Cyrene!")

            asyncio.run(run())
        """)


def _readme_text(name: str, template: str) -> str:
    return dedent(f"""\
        # {name}

        CyreneAI {template} plugin project.

        ```bash
        cyrene-plugin check .
        cyrene-plugin docs .
        pytest
        ```
        """)


def _documentation_payload(
    project_path: Path,
    manifest: PluginManifest,
    client: PluginTestClient,
) -> dict[str, Any]:
    return {
        "project_path": str(project_path),
        "plugin": manifest.to_definition().model_dump(mode="json"),
        "commands": [command.model_dump(mode="json") for command in client.commands],
        "tasks": [task.model_dump(mode="json") for task in client.tasks],
        "events": [event.model_dump(mode="json") for event in client.events],
        "middlewares": [
            middleware.model_dump(mode="json") for middleware in client.middlewares
        ],
    }


def _documentation_markdown(
    manifest: PluginManifest,
    client: PluginTestClient,
) -> str:
    lines = [
        f"# {manifest.name}",
        "",
        manifest.description,
        "",
        f"- Plugin ID: `{manifest.plugin_id}`",
        f"- Version: `{manifest.version}`",
        f"- Capabilities: {_inline_list(value.value for value in manifest.capabilities)}",
        f"- Permissions: {_inline_list(value.value for value in manifest.permissions)}",
        "",
    ]
    _append_commands(lines, client.commands)
    _append_tasks(lines, client.tasks)
    _append_events(lines, client.events)
    _append_middlewares(lines, client.middlewares)
    return "\n".join(lines).rstrip() + "\n"


def _append_commands(
    lines: list[str],
    commands: list[Any],
) -> None:
    if not commands:
        return
    lines.extend(["## Commands", ""])
    for command in commands:
        lines.append(f"### `/{command.name}`")
        if command.description:
            lines.append(command.description)
        if command.usage:
            lines.append(f"- Usage: `{command.usage}`")
        if command.aliases:
            lines.append(f"- Aliases: {_inline_list(command.aliases)}")
        if command.admin_required:
            lines.append("- Admin required: yes")
        if command.arguments:
            lines.extend(
                [
                    "",
                    "| Name | Kind | Type | Required | Default | Description |",
                    "| --- | --- | --- | --- | --- | --- |",
                ]
            )
            for argument in command.arguments:
                lines.append(_argument_row(argument))
        lines.append("")


def _append_tasks(lines: list[str], tasks: list[Any]) -> None:
    if not tasks:
        return
    lines.extend(["## Tasks", ""])
    for task in tasks:
        schedule = "manual"
        if task.interval_seconds is not None:
            schedule = f"every {task.interval_seconds:g}s"
        elif task.daily_at is not None:
            schedule = f"daily at {task.daily_at}"
        lines.append(f"- `{task.name}`: {task.description or schedule}")


def _append_events(lines: list[str], events: list[Any]) -> None:
    if not events:
        return
    lines.extend(["", "## Events", ""])
    for event in events:
        lines.append(f"- `{event.event_type.value}`: {event.description or 'enabled'}")


def _append_middlewares(lines: list[str], middlewares: list[Any]) -> None:
    if not middlewares:
        return
    lines.extend(["", "## Middlewares", ""])
    for middleware in middlewares:
        lines.append(
            f"- `{middleware.middleware_type.value}`: "
            f"{middleware.description or 'enabled'}"
        )


def _argument_row(argument: PluginCommandArgumentDefinition) -> str:
    default = "" if argument.default is None else str(argument.default)
    description = argument.description.replace("|", "\\|")
    required = "yes" if argument.required else "no"
    return (
        f"| `{argument.name}` | {argument.kind.value} | `{argument.type}` | "
        f"{required} | `{default}` | {description} |"
    )


def _inline_list(values: Any) -> str:
    items = [str(value) for value in values]
    if not items:
        return "(none)"
    return ", ".join(f"`{item}`" for item in items)


def _pyproject_text(plugin_id: str) -> str:
    package_name = plugin_id.replace("_", "-")
    return dedent(f"""\
        [project]
        name = "{package_name}"
        version = "0.1.0"
        requires-python = ">=3.12"
        dependencies = ["cyreneai-plugin-sdk"]

        [dependency-groups]
        dev = ["pytest"]

        [tool.pytest.ini_options]
        pythonpath = ["."]
        """)


if __name__ == "__main__":
    raise SystemExit(main())
