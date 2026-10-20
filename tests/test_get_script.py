"""scripts/get.sh, the one-line install: its checks run against stand-in commands (a fake uname, node, git…) placed
first on PATH, so the tests see what a Linux box, an Intel Mac or a Mac with an old Node would see. Nothing is installed
or fetched: each test calls one of the script's functions, with main() left out."""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "get.sh"


def functions_only() -> str:
    """The script without its last line (main "$@"), so sourcing it only defines the functions."""
    lines = SCRIPT.read_text().rstrip("\n").split("\n")
    assert lines[-1] == 'main "$@"'
    return "\n".join(lines[:-1])


def stand_in(folder: Path, name: str, body: str) -> None:
    command = folder / name
    command.write_text("#!/bin/bash\n" + body + "\n")
    command.chmod(0o755)


def call(function: str, stand_ins: Path) -> subprocess.CompletedProcess:
    """Run one of the script's functions with the stand-ins first on PATH and only the system's basics after them."""
    return subprocess.run(
        ["/bin/bash", "-c", functions_only() + "\n" + function],
        env={"PATH": f"{stand_ins}:/usr/bin:/bin"}, capture_output=True, text=True,
    )


def a_mac(folder: Path, system: str = "Darwin", chip: str = "arm64", macos: str = "15.2", kernel_chip: str | None = None) -> Path:
    """`chip` is what the shell's uname says; `kernel_chip` what the kernel says (sysctl), the same unless given."""
    stand_in(folder, "uname", f'if [ "$1" = "-m" ]; then echo {chip}; else echo {system}; fi')
    stand_in(folder, "sw_vers", f"echo {macos}")
    kernel = kernel_chip or chip
    # hw.optional.arm64 is 1 on Apple Silicon; on an Intel Mac the key doesn't exist and sysctl fails
    stand_in(folder, "sysctl", "echo 1" if kernel == "arm64" else "exit 1")
    return folder


def tools(folder: Path, git_works: bool = True, uv: bool = True, node: str | None = "v22.11.0") -> Path:
    stand_in(folder, "git", "exit 0" if git_works else "exit 1")
    if uv:
        stand_in(folder, "uv", "exit 0")
    if node:
        stand_in(folder, "node", f"echo {node}")
    return folder


def test_the_whole_script_waits_for_its_last_line():
    # A download cut short must run nothing: every step sits in main(), called only on the last line.
    body = functions_only()
    assert "\nmain() {" in body
    assert "\ncheck_computer\n" not in body and "\ninstall_tools\n" not in body


def test_an_apple_silicon_mac_on_a_recent_macos_goes_on(tmp_path):
    assert call("check_computer", a_mac(tmp_path)).returncode == 0


def test_linux_is_pointed_to_the_readme(tmp_path):
    result = call("check_computer", a_mac(tmp_path, system="Linux"))
    assert result.returncode == 1 and "mac-first-linux-today" in result.stderr


def test_an_intel_mac_stops(tmp_path):
    result = call("check_computer", a_mac(tmp_path, chip="x86_64"))
    assert result.returncode == 1 and "Apple Silicon" in result.stderr and "x86_64" in result.stderr


def test_an_apple_silicon_mac_in_a_rosetta_shell_goes_on(tmp_path):
    # The owner's laptop, 20 Oct 2026: uname said x86_64 from a Rosetta terminal and the install stopped on an M-series Mac.
    assert call("check_computer", a_mac(tmp_path, chip="x86_64", kernel_chip="arm64")).returncode == 0


def test_macos_13_stops(tmp_path):
    result = call("check_computer", a_mac(tmp_path, macos="13.6.1"))
    assert result.returncode == 1 and "macOS 14 or newer" in result.stderr


def test_nothing_is_missing_when_every_tool_is_there(tmp_path):
    result = call("missing_tools", tools(tmp_path))
    assert result.returncode == 0 and result.stdout.strip() == ""


def test_missing_uv_and_node_are_named_for_homebrew(tmp_path):
    result = call("missing_tools", tools(tmp_path, uv=False, node=None))
    assert result.stdout.split() == ["uv", "node"]


def test_apples_git_stub_counts_as_missing(tmp_path):
    # Without the Command Line Tools, /usr/bin/git is a stub whose git --version fails.
    result = call("missing_tools", tools(tmp_path, git_works=False))
    assert result.stdout.split() == ["git"]


def test_an_old_node_stops_instead_of_installing_a_second_one(tmp_path):
    result = call("missing_tools", tools(tmp_path, node="v18.19.0"))
    assert result.returncode == 1 and "brew upgrade node" in result.stderr


def test_without_homebrew_it_shows_how_to_get_it_and_installs_nothing(tmp_path):
    result = call("install_tools", tools(tmp_path, uv=False))
    assert result.returncode == 1
    assert "Odie needs: uv." in result.stdout and "brew.sh" in result.stdout


def test_with_homebrew_it_installs_only_whats_missing(tmp_path):
    folder = tools(tmp_path, uv=False, node=None)
    stand_in(folder, "brew", f'echo "$@" > {tmp_path}/brew-args')
    assert call("install_tools", folder).returncode == 0
    assert (tmp_path / "brew-args").read_text().split() == ["install", "uv", "node"]
