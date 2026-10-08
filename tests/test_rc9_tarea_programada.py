"""RC9: la tarea automatica corre con la sesion de quien inicia Windows."""
import re
from pathlib import Path

BAT = Path("packaging/windows_runtime/install_scheduled_task.bat").read_text(encoding="utf-8")
ISS = Path("packaging/inno/aiva_collector_setup.iss").read_text(encoding="utf-8")


def test_principal_es_el_grupo_usuarios_y_no_la_cuenta_que_instala():
    principal = re.search(r"\^<Principal id=\"Author\"\^>(.*?)\^</Principal\^>", BAT, re.S).group(1)
    assert "^<GroupId^>S-1-5-32-545^</GroupId^>" in principal
    assert "UserId" not in principal
    assert "InteractiveToken" not in principal
    assert "^<RunLevel^>LeastPrivilege^</RunLevel^>" in principal


def test_disparador_de_inicio_de_sesion_sin_usuario_fijo():
    trigger = re.search(r"\^<LogonTrigger\^>(.*?)\^</LogonTrigger\^>", BAT, re.S).group(1)
    assert "UserId" not in trigger
    assert "PT15M" in trigger


def test_la_tarea_sigue_sin_token_y_con_el_runner_silencioso():
    assert "aiva-collector-background.exe" in BAT
    assert "run-auto" in BAT
    assert not re.search(r"(?i)token|bearer", BAT.split("^<Arguments^>", 1)[1].split("^</Arguments^>", 1)[0])


def test_el_instalador_registra_la_tarea_elevado():
    # Elevado puede borrar tareas de versiones anteriores creadas por un administrador.
    line = next(line for line in ISS.splitlines() if "install_scheduled_task.bat" in line and line.startswith("Filename"))
    assert "runasoriginaluser" not in line
