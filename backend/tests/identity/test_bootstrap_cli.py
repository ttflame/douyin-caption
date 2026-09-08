from app.cli import bootstrap_admin


def test_cli_has_no_password_argument() -> None:
    destinations = {action.dest for action in bootstrap_admin._parser()._actions}

    assert "password" not in destinations


def test_validation_error_does_not_echo_password(monkeypatch, capsys) -> None:
    secret = "short"
    monkeypatch.setattr("sys.argv", ["bootstrap-admin"])
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", secret)

    exit_code = bootstrap_admin.main()
    output = capsys.readouterr()

    assert exit_code == 1
    assert secret not in output.out
    assert secret not in output.err
    assert "validation requirements" in output.err
