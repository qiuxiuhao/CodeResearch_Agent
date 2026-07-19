from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from backend.app.config.application import ApplicationConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cra")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="start the CodeResearch Agent API")
    serve_source = serve.add_mutually_exclusive_group(required=True)
    serve_source.add_argument("--config")
    serve_source.add_argument(
        "--profile",
        choices=("local", "team"),
        help="deprecated compatibility shortcut; prefer --config",
    )
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    config = subparsers.add_parser("config", help="validate application configuration")
    config.add_argument("action", choices=("validate",))
    config.add_argument("--config", required=True)
    doctor = subparsers.add_parser("doctor", help="validate runtime dependencies and services")
    doctor.add_argument("--config", required=True)
    models = subparsers.add_parser("models", help="prefetch or verify offline model assets")
    models.add_argument("action", choices=("prefetch", "verify"))
    models.add_argument("--config", required=True)
    models.add_argument("--include-optional", action="store_true")
    secret_parser = subparsers.add_parser("secrets", help="manage provider secrets")
    secret_parser.add_argument("action", choices=("set", "list", "delete"))
    secret_parser.add_argument("--config", required=True)
    secret_parser.add_argument("--provider")
    secret_parser.add_argument("--api-key")
    auth = subparsers.add_parser("auth", help="manage local identity bootstrap")
    auth.add_argument("action", choices=("bootstrap-token",))
    auth.add_argument("--config", required=True)
    auth.add_argument("--ttl-hours", type=int, default=24)
    inference = subparsers.add_parser("inference", help="run the shared CPU/CUDA inference runtime")
    inference.add_argument("--config", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(args, "config") or hasattr(args, "profile"):
        selected_config = getattr(args, "config", None)
        if selected_config is None:
            selected_config = (
                "config/local-cpu.yaml" if args.profile == "local"
                else "config/team-autodl-gpu.yaml"
            )
            print(
                "warning: --profile is deprecated; use --config instead",
                file=sys.stderr,
            )
        config_path = str(Path(selected_config).expanduser().resolve())
        os.environ["CRA_CONFIG_PATH"] = config_path
        config = ApplicationConfig.load(config_path)
        config.export_runtime_compatibility()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "backend.app.main:app", host=args.host or config.host,
            port=args.port or config.port, reload=False,
        )
        return 0
    if args.command == "config":
        print(json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    if args.command == "doctor":
        from .doctor import doctor_ok, run_doctor
        checks = run_doctor(config)
        print(json.dumps([item.model_dump() for item in checks], indent=2))
        return 0 if doctor_ok(checks) else 1
    if args.command == "models":
        from backend.app.retrieval.model_manager import prefetch_models, verify_models
        if args.action == "prefetch":
            lock_path = prefetch_models(
                config.model_manifest, config.compute.model_cache, device=config.compute.device,
                include_optional=args.include_optional,
            )
            print(lock_path)
            return 0
        errors = verify_models(config.compute.model_cache)
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
        return 0 if not errors else 1
    if args.command == "secrets":
        return _secrets_command(args)
    if args.command == "auth":
        from .auth import LocalIdentityService
        from .runtime import ControlPlaneRuntime
        runtime = ControlPlaneRuntime.build()
        if not isinstance(runtime.identity, LocalIdentityService):
            print("identity_unavailable", file=sys.stderr)
            return 1
        print(runtime.identity.create_bootstrap_token(ttl_hours=args.ttl_hours))
        return 0
    if args.command == "inference":
        socket_path = config.compute.inference_socket
        if socket_path is None:
            print("compute.inference_socket is required", file=sys.stderr)
            return 2
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        socket_path.parent.chmod(0o770)
        if socket_path.exists():
            socket_path.unlink()
        os.umask(0o117)
        import uvicorn
        uvicorn.run("backend.app.retrieval.inference_server:app", uds=str(socket_path), reload=False)
        return 0
    return 2


def _secrets_command(args: argparse.Namespace) -> int:
    from backend.app.settings.provider_registry import PROVIDERS
    from backend.app.settings.secret_store import configured_secret_store

    store = configured_secret_store()
    if args.action == "list":
        data = store.read()
        print(json.dumps({
            "revision": data.get("revision", 0),
            "providers": sorted(data.get("providers", {}).keys()),
        }, indent=2))
        return 0
    if not args.provider or args.provider not in PROVIDERS:
        print("--provider must name a registered provider", file=sys.stderr)
        return 2
    if args.action == "set":
        key = args.api_key or ""
        if not key:
            import getpass
            key = getpass.getpass("API key: ")
        if not key:
            print("API key is required", file=sys.stderr)
            return 2
        store.update_provider(
            args.provider, config={}, api_key=key, expected_revision=store.current_revision(),
        )
    else:
        store.delete_api_key(args.provider, expected_revision=store.current_revision())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
