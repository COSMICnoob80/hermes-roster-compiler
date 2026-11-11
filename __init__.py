"""roster-compiler plugin — registration for the three roster tools."""

from __future__ import annotations

import logging

if __package__:
    from . import roster_compiler
else:  # loaded as a bare module when a test collector imports the repo root
    import roster_compiler

logger = logging.getLogger(__name__)

TOOLSET = "roster_compiler"

ROSTER_READ_SCHEMA = {
    "name": "roster_read",
    "description": (
        "Parse a hospital duty roster file (CSV or whitespace-aligned plain text) and "
        "return its ward, month and every shift entry as JSON. Use this first to see how "
        "the roster was understood before auditing or exporting it. Rows the parser cannot "
        "read are reported as warnings instead of being guessed at."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the roster file (.csv or .txt).",
            },
        },
        "required": ["path"],
    },
}

ROSTER_AUDIT_SCHEMA = {
    "name": "roster_audit",
    "description": (
        "Audit a hospital duty roster and return findings: uncovered shifts, double "
        "bookings (same person twice on the same shift), more than 6 consecutive working "
        "days, and a night shift followed by a morning or evening shift with no rest. "
        "Deterministic — the same file always yields the same findings."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the roster file (.csv or .txt).",
            },
        },
        "required": ["path"],
    },
}

ROSTER_EXPORT_SCHEMA = {
    "name": "roster_export",
    "description": (
        "Audit a hospital duty roster and write two files: a clean, sorted CSV schedule "
        "and a readable HTML exception report listing every problem. The input roster is "
        "never modified. Use after roster_audit when the user wants files to share."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the roster file to read (never modified).",
            },
            "out_path": {
                "type": "string",
                "description": (
                    "Where to write the clean CSV. The HTML report is written beside it "
                    "with the same name and an .html extension."
                ),
            },
        },
        "required": ["path", "out_path"],
    },
}


def register(ctx):
    """Wire the three roster tools into Hermes."""
    ctx.register_tool(
        name="roster_read",
        toolset=TOOLSET,
        schema=ROSTER_READ_SCHEMA,
        handler=roster_compiler.roster_read,
    )
    ctx.register_tool(
        name="roster_audit",
        toolset=TOOLSET,
        schema=ROSTER_AUDIT_SCHEMA,
        handler=roster_compiler.roster_audit,
    )
    ctx.register_tool(
        name="roster_export",
        toolset=TOOLSET,
        schema=ROSTER_EXPORT_SCHEMA,
        handler=roster_compiler.roster_export,
    )
    logger.debug("roster-compiler registered roster_read, roster_audit, roster_export")
