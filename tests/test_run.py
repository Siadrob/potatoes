import socket

import run


def test_needs_install_follows_requirements(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("flask\n")
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    assert run.needs_install(venv_dir, req)                       # jamais installé
    (venv_dir / ".requirements.sha256").write_text(run.requirements_hash(req))
    assert not run.needs_install(venv_dir, req)                   # à jour
    req.write_text("flask\npandas\n")
    assert run.needs_install(venv_dir, req)                       # requirements modifié


def test_free_port_skips_busy_ports():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert run.free_port(port) != port


def test_venv_python_path(tmp_path):
    path = run.venv_python(tmp_path)
    assert path.name in ("python", "python.exe") and tmp_path in path.parents
