import subprocess
from unittest.mock import patch, MagicMock
from tools.pip_install import pip_install


def test_pip_install_uv_timeout_no_fallback():
    with patch("shutil.which", return_value="/bin/uv"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="uv", timeout=120)) as mock_run:
        res = pip_install.invoke({"packages": "nonexistent-pkg"})
        assert "uv pip install timed out" in res
        # Only uv was run, not pip fallback
        assert mock_run.call_count == 1


def test_pip_install_uv_fatal_error_no_fallback():
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stderr = "error: package 'nonexistent-pkg' not found in registry"
    mock_res.stdout = ""

    with patch("shutil.which", return_value="/bin/uv"), \
         patch("subprocess.run", return_value=mock_res) as mock_run:
        res = pip_install.invoke({"packages": "nonexistent-pkg"})
        assert "EXIT CODE: 1" in res
        assert "not found" in res
        # Did not fall back to pip
        assert mock_run.call_count == 1


def test_pip_install_uv_unknown_error_falls_back_to_pip():
    mock_uv_fail = MagicMock()
    mock_uv_fail.returncode = 2
    mock_uv_fail.stderr = "unrecognized option"
    mock_uv_fail.stdout = ""

    mock_pip_ok = MagicMock()
    mock_pip_ok.returncode = 0
    mock_pip_ok.stderr = ""
    mock_pip_ok.stdout = "Successfully installed"

    with patch("shutil.which", return_value="/bin/uv"), \
         patch("subprocess.run", side_effect=[mock_uv_fail, mock_pip_ok]) as mock_run:
        res = pip_install.invoke({"packages": "some-pkg"})
        assert "Successfully installed" in res
        assert mock_run.call_count == 2

