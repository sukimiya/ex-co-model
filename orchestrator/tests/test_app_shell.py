import json
import urllib.request

from app.main import free_port, main


def test_free_port_returns_bindable_port():
    import socket
    p = free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", p))


def test_smoke_mode(tmp_path, capsys):
    rc = main(["--smoke", "--data-dir", str(tmp_path)])
    assert rc == 0
    assert "SMOKE OK" in capsys.readouterr().out
