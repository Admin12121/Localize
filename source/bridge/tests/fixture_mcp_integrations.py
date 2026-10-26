"""Real SDK fixture, deliberately exposes a tool the owner does not select."""
import asyncio
import os
from pathlib import Path
import sys
from mcp.server import MCPServer

server = MCPServer('integration-fixture', log_level='ERROR')

@server.tool()
def write_marker(path: str, text: str) -> str:
    Path(path).write_text(text, encoding='utf-8')
    return 'written'

@server.tool()
def unlisted() -> str:
    return 'must never be called'

@server.tool()
async def slow(path: str) -> str:
    Path(path).with_suffix('.pid').write_text(str(os.getpid()))
    await asyncio.sleep(15)
    Path(path).write_text('late')
    return 'late'

@server.tool()
def echo_secret() -> str:
    return os.environ.get('FIXTURE_SECRET', '')

@server.tool()
def large() -> str:
    return 'x' * 300_000

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--protocol-error':
        from mcp import MCPError
        from mcp.server.lowlevel import Server
        from mcp.server.stdio import stdio_server
        from mcp import types
        from mcp_types import HEADER_MISMATCH
        async def listed(context, params):
            return types.ListToolsResult(tools=[types.Tool(name='single_effect', input_schema={
                'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}),
                types.Tool(name='external_schema', input_schema={'type': 'object', '$ref': 'https://unconfigured.invalid/schema'})])
        async def called(context, params):
            with Path(params.arguments['path']).open('a') as stream: stream.write('x')
            raise MCPError(HEADER_MISMATCH, 'deliberate protocol error after side effect')
        lowlevel = Server('single-effect-fixture', on_list_tools=listed, on_call_tool=called)
        async def run_single():
            async with stdio_server() as (read, write):
                await lowlevel.run(read, write, lowlevel.create_initialization_options())
        asyncio.run(run_single())
    elif len(sys.argv) > 1:
        server.run('streamable-http', host='127.0.0.1', port=int(sys.argv[1]), json_response=True)
    else:
        server.run('stdio')
