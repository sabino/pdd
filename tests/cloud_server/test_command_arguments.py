from unittest.mock import patch

import pytest

from pdd.server.jobs import _build_subprocess_command_args
from pdd.server.routes.commands import _build_pdd_command_args


@pytest.mark.parametrize("command", ["sync", "generate", "fix"])
@pytest.mark.parametrize(
    ("builder", "executable_lookup"),
    [
        (_build_subprocess_command_args, "pdd.server.jobs._find_pdd_executable"),
        (_build_pdd_command_args, "pdd.server.routes.commands._find_pdd_executable"),
    ],
)
def test_remote_positional_arguments_preserve_global_option_order(
    builder, executable_lookup, command
):
    with patch(executable_lookup, return_value="/test/pdd"):
        assert builder(command, {"args": ["--help"]}, {"local": True}) == [
            "/test/pdd",
            "--local",
            command,
            "--help",
        ]


def test_named_positional_arguments_keep_the_existing_contract():
    with patch("pdd.server.jobs._find_pdd_executable", return_value="/test/pdd"):
        assert _build_subprocess_command_args(
            "generate", {"prompt_file": "module.prompt"}, {"local": True}
        ) == ["/test/pdd", "--local", "generate", "module.prompt"]
