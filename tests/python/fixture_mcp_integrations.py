"""Real SDK fixture, deliberately exposes a tool the owner does not select."""
import asyncio
import os
from pathlib import Path
import sys
import time
time.sleep(float(os.environ.get("FIXTURE_STARTUP_DELAY", "0")))
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
    if len(sys.argv) > 1 and sys.argv[1] == '--discovery':
        from mcp.server.lowlevel import Server
        from mcp.server.stdio import stdio_server
        from mcp import types
        async def listed(context, params):
            with Path(os.environ['FIXTURE_DISCOVERY_LOG']).open('a') as stream:stream.write('list\n')
            page=int(params.cursor or '0')
            cursor=str(page+1) if page+1<int(os.environ.get('FIXTURE_PAGES','1')) else None
            return types.ListToolsResult(tools=[types.Tool(name='write_marker',description=os.environ.get('FIXTURE_SECRET','fixture'),input_schema={'type':'object','properties':{},'additionalProperties':False})],next_cursor=cursor)
        async def called(context, params):
            return types.CallToolResult(content=[types.TextContent(type='text',text='ok')])
        lowlevel=Server('discovery-fixture',on_list_tools=listed,on_call_tool=called)
        async def run_discovery():
            async with stdio_server() as (read,write):
                await lowlevel.run(read,write,lowlevel.create_initialization_options())
        asyncio.run(run_discovery())
    elif len(sys.argv) > 1 and sys.argv[1] == '--protocol-error':
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
