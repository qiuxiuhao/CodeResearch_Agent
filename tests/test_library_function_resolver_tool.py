from __future__ import annotations

from backend.app.tools.library_function_resolver_tool import resolve_library_function


def test_resolve_library_function_aliases():
    aliases = {
        "F": "torch.nn.functional",
        "np": "numpy",
        "Image": "PIL.Image",
        "rearrange": "einops.rearrange",
    }

    assert resolve_library_function("F.relu", aliases).canonical_name == "torch.nn.functional.relu"
    assert resolve_library_function("np.array", aliases).canonical_name == "numpy.array"
    assert resolve_library_function("Image.open", aliases).canonical_name == "PIL.Image.open"
    assert resolve_library_function("rearrange", aliases).canonical_name == "einops.rearrange"


def test_resolve_library_function_known_root():
    resolved = resolve_library_function("torch.randn", {})

    assert resolved.canonical_name == "torch.randn"
    assert resolved.category == "pytorch"


def test_resolve_library_function_keeps_existing_alias_capabilities():
    aliases = {
        "F": "torch.nn.functional",
        "nn": "torch.nn",
        "np": "numpy",
        "Image": "PIL.Image",
        "rearrange": "einops.rearrange",
    }

    assert resolve_library_function("F.relu", aliases).canonical_name == "torch.nn.functional.relu"
    assert resolve_library_function("nn.Linear", aliases).canonical_name == "torch.nn.Linear"
    assert resolve_library_function("np.array", aliases).canonical_name == "numpy.array"
    assert resolve_library_function("Image.open", aliases).canonical_name == "PIL.Image.open"
    assert resolve_library_function("rearrange", aliases).canonical_name == "einops.rearrange"
