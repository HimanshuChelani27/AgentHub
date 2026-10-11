"""Utilities: a small demo MCP server with safe, side-effect-free helpers."""

import ast
import operator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("utils", description="Calculator, clock and text helpers.", version="1.0.0")

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float:
    # Only numbers and arithmetic operators: never eval() user input.
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow) and abs(_eval(node.right)) > 100:
            raise ToolError("Exponent too large")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ToolError("Only numbers and + - * / % ** are allowed")


@mcp.tool()
def calculator(expression: str) -> dict[str, Any]:
    """Evaluate an arithmetic expression, e.g. '480000 * 0.18' or '(126000 + 315000) / 2'."""
    if len(expression) > 200:
        raise ToolError("Expression too long")
    try:
        result = _eval(ast.parse(expression, mode="eval"))
    except SyntaxError as e:
        raise ToolError(f"Invalid expression: {expression!r}") from e
    except ZeroDivisionError as e:
        raise ToolError("Division by zero") from e
    return {"expression": expression, "result": round(result, 6)}


@mcp.tool()
def current_time(timezone: str = "UTC") -> dict[str, Any]:
    """Current date and time in an IANA timezone, e.g. 'Asia/Kolkata'."""
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ToolError(f"Unknown timezone '{timezone}'") from e
    now = datetime.now(UTC).astimezone(tz)
    return {"timezone": timezone, "iso": now.isoformat(timespec="seconds"), "weekday": now.strftime("%A")}


@mcp.tool()
def word_count(text: str) -> dict[str, Any]:
    """Count words, characters and estimated reading time of a text."""
    words = len(text.split())
    return {"words": words, "characters": len(text), "reading_time_min": round(words / 230, 1)}
