from __future__ import annotations
"""
Cursor <-> Claude Code bidirectional tool name and argument mapping.

Cursor's native Agent mode returns tools like `read_file`, `run_terminal_command`
with Cursor-specific argument names. Claude Code expects `Read`, `Bash` with its
own argument schema. This module bridges both directions.
"""

import json

CURSOR_ENUM_TO_CLAUDE_CODE: dict[int, dict] = {
    5:  {'claude_name': 'Read',      'cursor_name': 'read_file'},
    6:  {'claude_name': None,        'cursor_name': 'list_dir'},
    7:  {'claude_name': 'Edit',      'cursor_name': 'edit_file'},
    8:  {'claude_name': 'Glob',      'cursor_name': 'file_search'},
    11: {'claude_name': None,        'cursor_name': 'delete_file'},
    13: {'claude_name': 'Read',      'cursor_name': 'read_file_v2'},
    15: {'claude_name': 'Bash',      'cursor_name': 'run_terminal_command'},
    16: {'claude_name': 'Write',     'cursor_name': 'create_file'},
    38: {'claude_name': 'Write',     'cursor_name': 'edit_file_v2'},
    39: {'claude_name': None,        'cursor_name': 'list_dir_v2'},
    40: {'claude_name': 'Read',      'cursor_name': 'read_file_v2'},
    41: {'claude_name': 'Grep',      'cursor_name': 'ripgrep_raw_search'},
    42: {'claude_name': 'Glob',      'cursor_name': 'glob_file_search'},
    1:  {'claude_name': 'Grep',      'cursor_name': 'codebase_search'},
    10: {'claude_name': 'WebSearch', 'cursor_name': 'web_search'},
}

CURSOR_NAME_ALIASES: dict[str, str] = {
    'run_terminal_cmd':  'run_terminal_command',
    'run_command':       'run_terminal_command',
    'terminal_command':  'run_terminal_command',
    'read_chunk':        'read_file',
    'semantic_search':   'codebase_search',
    'list_directory':    'list_dir',
    'search_files':      'file_search',
    'search_codebase':   'codebase_search',
    'apply_diff':        'edit_file',
    'apply_agent_diff':  'edit_file',
}

CURSOR_NAME_TO_CLAUDE_CODE: dict[str, dict] = {}

for _enum_val, _mapping in CURSOR_ENUM_TO_CLAUDE_CODE.items():
    if _mapping['claude_name']:
        CURSOR_NAME_TO_CLAUDE_CODE[_mapping['cursor_name']] = {
            'claude_name': _mapping['claude_name'],
            'cursor_enum': _enum_val,
        }

for _alias, _canonical in CURSOR_NAME_ALIASES.items():
    if _canonical in CURSOR_NAME_TO_CLAUDE_CODE:
        CURSOR_NAME_TO_CLAUDE_CODE[_alias] = CURSOR_NAME_TO_CLAUDE_CODE[_canonical]


def _normalize_cursor_name(name: str) -> str:
    return CURSOR_NAME_ALIASES.get(name, name)


def convert_cursor_args_to_claude_code(cursor_name: str, cursor_args: dict | str | None) -> dict:
    if isinstance(cursor_args, str):
        try:
            args = json.loads(cursor_args)
        except (json.JSONDecodeError, ValueError):
            args = {}
    else:
        args = cursor_args or {}

    canonical = _normalize_cursor_name(cursor_name)

    match canonical:
        case 'read_file' | 'read_file_v2':
            return {'path': args.get('target_file') or args.get('targetFile') or args.get('path') or args.get('file_path') or ''}

        case 'run_terminal_command':
            return {'command': args.get('command') or args.get('terminalCommand') or args.get('explanation') or ''}

        case 'edit_file_v2':
            return {'path': args.get('file_path') or args.get('path') or '', 'contents': args.get('contents') or ''}

        case 'create_file':
            return {
                'path': args.get('file_path') or args.get('path') or args.get('createFilePath') or '',
                'contents': args.get('contents') or args.get('file_text') or '',
            }

        case 'edit_file':
            return {
                'path': args.get('path') or args.get('file_path') or '',
                'old_string': args.get('old_string') or args.get('oldString') or '',
                'new_string': args.get('new_string') or args.get('newString') or '',
            }

        case 'file_search' | 'glob_file_search':
            return {'glob_pattern': args.get('globPattern') or args.get('searchQuery') or args.get('query') or args.get('pattern') or ''}

        case 'codebase_search' | 'ripgrep_raw_search':
            return {'pattern': args.get('searchQuery') or args.get('query') or args.get('pattern') or args.get('regex') or ''}

        case 'list_dir' | 'list_dir_v2':
            return {'path': args.get('target_directory') or args.get('targetDirectory') or args.get('path') or ''}

        case 'web_search':
            return {'search_term': args.get('query') or args.get('searchQuery') or args.get('search_term') or ''}

        case _:
            return args


def convert_cursor_tool_call_to_claude_code(cursor_tool_call: dict, valid_tool_names: list | None = None) -> dict | None:
    cursor_enum = cursor_tool_call.get('_cursor_tool_enum')
    func = cursor_tool_call.get('function') or {}
    cursor_name = func.get('name') or ''
    canonical_name = _normalize_cursor_name(cursor_name)

    mapping = (
        CURSOR_ENUM_TO_CLAUDE_CODE.get(cursor_enum)
        or CURSOR_NAME_TO_CLAUDE_CODE.get(cursor_name)
        or CURSOR_NAME_TO_CLAUDE_CODE.get(canonical_name)
    )

    if not mapping or not mapping.get('claude_name'):
        return None

    if valid_tool_names:
        valid_set = {n.lower() for n in valid_tool_names}
        if mapping['claude_name'].lower() not in valid_set:
            return None

    raw_args = func.get('arguments', '{}')
    try:
        cursor_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except (json.JSONDecodeError, ValueError):
        cursor_args = {}

    claude_args = convert_cursor_args_to_claude_code(
        mapping.get('cursor_name') or cursor_name,
        cursor_args,
    )

    return {
        'id': cursor_tool_call.get('id'),
        'type': 'function',
        'function': {
            'name': mapping['claude_name'],
            'arguments': json.dumps(claude_args),
        },
        '_cursor_tool_enum': cursor_enum,
        '_cursor_tool_name': cursor_name,
    }
