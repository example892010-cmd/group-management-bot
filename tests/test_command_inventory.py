import ast
from pathlib import Path


def registered_commands():
    commands = set()
    app_dir = Path(__file__).parents[1] / "app"
    for path in (app_dir / "handlers.py", app_dir / "extra_handlers.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                for call in ast.walk(decorator):
                    if not isinstance(call, ast.Call):
                        continue
                    if isinstance(call.func, ast.Name) and call.func.id == "Command" and call.args:
                        if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                            commands.add(call.args[0].value)
    return commands


def test_requested_public_and_group_commands_are_registered():
    actual = registered_commands()
    expected = {
        "start", "help", "id", "info", "admins", "staff", "rules", "report", "ping",
        "ban", "unban", "kick", "mute", "unmute", "warn", "warnings", "resetwarns",
        "purge", "pin", "unpin", "promote", "demote", "setwelcome", "welcome",
        "resetwelcome", "setgoodbye", "goodbye", "resetgoodbye", "setrules", "filter",
        "stop", "filters", "save", "get", "notes", "antispam", "antiflood", "antilink",
        "antiforward", "antibot", "lock", "unlock", "locks", "settings", "setdescription",
        "settitle", "slowmode",
    }
    assert expected <= actual


def test_requested_owner_commands_are_registered():
    actual = registered_commands()
    expected = {
        "owner", "stats", "groups", "users", "broadcast", "blockgroup", "unblockgroup",
        "leave", "restart", "maintenance", "disablemaintenance", "logs", "clearcache", "backup",
    }
    assert expected <= actual
